"""Cookie sessions, CSRF, rate-limited login and role enforcement."""
from __future__ import annotations
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from .ledger import db
from .security import password_hash, password_matches, production

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=12, max_length=256)
    display_name: str = Field(default="", max_length=100)


def public_user(row):
    return {k: row[k] for k in ("username", "display_name", "role")}


def create_user(username, password, display_name, role, bootstrap=False):
    if role not in {"admin", "analyst", "reviewer", "auditor"}:
        raise ValueError("Invalid role")
    encoded = password_hash(password)
    with db.transaction() as conn:
        if bootstrap and conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise HTTPException(409, "Workspace is already initialized")
        conn.execute("INSERT INTO users VALUES (?,?,?,?,?,0)", (username.lower(), display_name or username, role, encoded, db.now()))
        db._event(conn, "workspace", "bootstrap" if bootstrap else "admin", "user.created", {"username": username.lower(), "role": role})


@router.get("/status")
def status(request: Request):
    with db._conn() as conn:
        initialized = bool(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    local=not production() and request.client and request.client.host in {'127.0.0.1','::1','testclient'}
    return {"initialized": initialized, "local_setup_allowed": bool(local), "deployment": "production" if production() else "local"}


@router.post("/setup")
def setup(body: Credentials, request: Request):
    if production() or not request.client or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "First administrator must be provisioned with the admin CLI")
    create_user(body.username, body.password, body.display_name, "admin", bootstrap=True)
    return {"ok": True}


@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    address = request.client.host if request.client else "unknown"
    now = time.time()
    with db.transaction() as conn:
        attempt = conn.execute("SELECT failures,until FROM login_attempts WHERE address=?", (address,)).fetchone()
        if attempt and attempt[0] >= 8 and attempt[1] > now:
            raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
        user = conn.execute("SELECT * FROM users WHERE username=? AND disabled=0", (body.username.lower(),)).fetchone()
        valid = user and password_matches(body.password, user["password_hash"])
        if not valid:
            if not user:
                password_hash(body.password)  # comparable password work for unknown users
            failures = attempt[0] + 1 if attempt and attempt[1] > now else 1
            conn.execute("INSERT OR REPLACE INTO login_attempts VALUES (?,?,?)", (address, failures, now + 900))
        else:
            conn.execute("DELETE FROM login_attempts WHERE address=?", (address,))
            conn.execute("DELETE FROM sessions WHERE expires<?", (now,))
            token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions VALUES (?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["username"], csrf, now + 28800))
            db._event(conn, "workspace", user["username"], "session.started", {})
    if not valid:
        raise HTTPException(401, "Invalid credentials")
    response.set_cookie("copilot_session", token, httponly=True, secure=production(), samesite="strict", max_age=28800, path="/")
    return {**public_user(user), "csrf": csrf}


def authenticate(request: Request):
    token = request.cookies.get("copilot_session", "")
    with db._conn() as conn:
        user = conn.execute("SELECT u.*,s.csrf FROM sessions s JOIN users u ON s.username=u.username WHERE s.token_hash=? AND s.expires>? AND u.disabled=0", (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
    if not user:
        raise HTTPException(401, "Sign in to your workspace")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), user["csrf"]):
            raise HTTPException(403, "Session verification failed. Refresh and retry.")
    request.state.user = public_user(user)
    return user


def require(request: Request, *roles):
    user = getattr(request.state, "user", None)
    if not user or user["role"] not in roles:
        raise HTTPException(403, "Your role cannot perform this action")
    return user


@router.get("/me")
def me(request: Request):
    user = authenticate(request)
    return {**public_user(user), "csrf": user["csrf"]}


@router.post("/logout")
def logout(request: Request, response: Response):
    authenticate(request)
    with db.transaction() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(request.cookies.get("copilot_session", "").encode()).hexdigest(),))
    response.delete_cookie("copilot_session", path="/")
    return {"ok": True}


class UserCreate(Credentials):
    role: str


@router.get("/users")
def users(request: Request):
    require(request, "admin")
    with db._conn() as conn:
        return [public_user(r) for r in conn.execute("SELECT * FROM users ORDER BY username")]


@router.post("/users")
def add_user(body: UserCreate, request: Request):
    require(request, "admin")
    try:
        create_user(body.username, body.password, body.display_name, body.role)
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise HTTPException(422, str(exc))
        raise HTTPException(409, "Username is already registered")
    return {"ok": True}
