"""Single-tenant encryption and audit signatures. Production keys are external."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from cryptography.fernet import Fernet


def production() -> bool:
    return os.getenv("APP_ENV", "development") == "production"


def secret(name: str) -> bytes:
    configured = os.getenv(name)
    file = os.getenv(name + '_FILE')
    if configured and file:
        raise RuntimeError(f'Configure only one of {name} or {name}_FILE')
    if file:
        configured = Path(file).read_text(encoding='utf-8').strip()
        if not configured:
            raise RuntimeError(f'{name}_FILE is empty')
    if configured:
        value = configured.encode()
    else:
        if production():
            raise RuntimeError(f"{name} must be supplied by the production secret manager")
        directory = Path(os.getenv("KEY_DIR", str(Path(__file__).resolve().parents[1] / "data" / ".keys")))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / name.lower()
        try:
            with path.open("xb") as f:
                f.write(Fernet.generate_key())
            path.chmod(0o600)
        except FileExistsError:
            pass
        value = path.read_bytes().strip()
    if len(base64.urlsafe_b64decode(value)) != 32:
        raise RuntimeError(f"{name} must be a 32-byte URL-safe base64 key")
    return value


def encrypt(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return "enc:v1:" + Fernet(secret("DATA_ENCRYPTION_KEY")).encrypt(raw).decode()


def decrypt(value: str) -> str:
    if not value.startswith("enc:v1:"):
        return value  # legacy migration reader only
    return Fernet(secret("DATA_ENCRYPTION_KEY")).decrypt(value[7:].encode()).decode()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sign(value: str) -> str:
    return hmac.new(secret("AUDIT_SIGNING_KEY"), value.encode(), hashlib.sha256).hexdigest()


def password_hash(password: str, salt: str | None = None) -> str:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must contain 12–256 characters")
    salt = salt or secrets.token_hex(16)
    result = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000)
    return f"pbkdf2_sha256$600000${salt}${result.hex()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        return hmac.compare_digest(password_hash(password, stored.split("$")[2]), stored)
    except (ValueError, IndexError):
        return False
