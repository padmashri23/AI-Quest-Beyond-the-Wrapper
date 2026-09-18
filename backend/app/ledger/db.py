"""Encrypted immutable revisions, evidence, artifacts and HMAC-chained audit events.

Triggers reject record changes. Administrators holding the signing key are outside
this trust boundary; retain exported checkpoints independently in production.
"""
from __future__ import annotations
import base64
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import uuid
from ..security import canonical, decrypt, digest, encrypt, sign
from ..schemas import AgentLogEntry, LedgerEntry, RunSummary

_DEFAULT = Path(__file__).resolve().parents[2] / "data" / "ledger.db"
_override: ContextVar[Path | None] = ContextVar('ledger_path', default=None)


@contextmanager
def using(path: Path):
    """Scope maintenance to a snapshot without changing the live process environment."""
    token = _override.set(path.resolve())
    try:
        yield
    finally:
        _override.reset(token)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _path():
    path = _override.get() or Path(os.getenv("LEDGER_PATH", str(_DEFAULT)))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class _Connection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _conn():
    conn = sqlite3.connect(_path(), timeout=30, factory=_Connection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA secure_delete=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS revisions (
          run_id TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL,
          body TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(run_id, revision));
        CREATE TABLE IF NOT EXISTS artifacts (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, kind TEXT NOT NULL,
          object_id TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS artifact_lookup ON artifacts(run_id,kind,object_id,id);
        CREATE TABLE IF NOT EXISTS documents (
          document_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, filename TEXT NOT NULL,
          sha256 TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, actor TEXT NOT NULL,
          action TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL,
          previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL, signature TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users (
          username TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL,
          password_hash TEXT NOT NULL, created_at TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username),
          csrf TEXT NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS login_attempts (address TEXT PRIMARY KEY, failures INTEGER, until REAL);
    """)
    for table in ("revisions", "artifacts", "documents", "audit_events"):
        for operation in ("UPDATE", "DELETE"):
            conn.execute(f"CREATE TRIGGER IF NOT EXISTS prevent_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'Append-only record'); END")
    return conn


@contextmanager
def transaction():
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _event(conn, run_id, actor, action, payload):
    last = conn.execute("SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
    previous = last[0] if last else "0" * 64
    ts = now()
    hashed = digest({"run_id": run_id, "actor": actor, "action": action, "created_at": ts, "payload": payload, "previous_hash": previous})
    conn.execute("INSERT INTO audit_events(run_id,actor,action,created_at,payload,previous_hash,event_hash,signature) VALUES (?,?,?,?,?,?,?,?)",
                 (run_id, actor, action, ts, encrypt(canonical(payload)), previous, hashed, sign(hashed)))
    return hashed


def event(run_id, actor, action, payload):
    with transaction() as conn:
        return _event(conn, run_id, actor, action, payload)


def _snapshot(conn, summary, entries, actor, expected_revision=None):
    last = conn.execute("SELECT MAX(revision) FROM revisions WHERE run_id=?", (summary.run_id,)).fetchone()[0] or 0
    if expected_revision is not None and expected_revision != last:
        raise ValueError("Inventory changed. Reload before saving.")
    summary.revision = last + 1
    body = {"summary": summary.model_dump(mode="json"), "entries": [e.model_dump(mode="json") for e in entries]}
    hashed = digest(body)
    conn.execute("INSERT INTO revisions VALUES (?,?,?,?,?)", (summary.run_id, summary.revision, now(), encrypt(canonical(body)), hashed))
    _event(conn, summary.run_id, actor, "inventory.revised" if last else "inventory.created",
           {"revision": summary.revision, "snapshot_sha256": hashed})
    return hashed


def save_run(summary, entries, log, actor="system", expected_revision=None, files=None):
    with transaction() as conn:
        hashed = _snapshot(conn, summary, entries, actor, expected_revision)
        for entry in log:
            _artifact(conn, summary.run_id, "agent_log", uuid.uuid4().hex, entry.model_dump(mode="json"), actor)
        for filename, content in files or []:
            _document(conn, summary.run_id, filename, content, actor)
    return hashed


def _read_snapshot(run_id, revision=None):
    with _conn() as conn:
        row = conn.execute("SELECT body FROM revisions WHERE run_id=?" + (" AND revision=?" if revision else "") + " ORDER BY revision DESC LIMIT 1",
                           (run_id, revision) if revision else (run_id,)).fetchone()
    return json.loads(decrypt(row[0])) if row else None


def get_run(run_id):
    body = _read_snapshot(run_id)
    return RunSummary.model_validate(body["summary"]) if body else None


def list_runs():
    with _conn() as conn:
        rows = conn.execute("SELECT body FROM revisions r WHERE revision=(SELECT MAX(revision) FROM revisions WHERE run_id=r.run_id) ORDER BY created_at DESC").fetchall()
    return [RunSummary.model_validate(json.loads(decrypt(row[0]))["summary"]) for row in rows]


def get_entries(run_id):
    body = _read_snapshot(run_id)
    return [LedgerEntry.model_validate(e) for e in body["entries"]] if body else []


def get_entry(run_id, line_id):
    return next((e for e in get_entries(run_id) if e.item.line_id == line_id), None)


def _artifact(conn, run_id, kind, object_id, body, actor):
    cursor = conn.execute("INSERT INTO artifacts(run_id,kind,object_id,body,created_at) VALUES (?,?,?,?,?)", (run_id, kind, object_id, encrypt(canonical(body)), now()))
    _event(conn, run_id, actor, f"{kind}.saved", {"id": object_id, "artifact_id": cursor.lastrowid, "body_sha256": digest(body)})


def put_artifact(run_id, kind, object_id, body, actor):
    with transaction() as conn:
        _artifact(conn, run_id, kind, object_id, body, actor)
    return body


def artifacts(run_id, kind):
    with _conn() as conn:
        rows = conn.execute("SELECT a.object_id,a.body,a.created_at FROM artifacts a WHERE run_id=? AND kind=? AND id=(SELECT MAX(id) FROM artifacts WHERE run_id=a.run_id AND kind=a.kind AND object_id=a.object_id) ORDER BY id", (run_id, kind)).fetchall()
    return [{"id": r[0], **json.loads(decrypt(r[1])), "saved_at": r[2]} for r in rows]


def get_artifact(run_id, kind, object_id):
    return next((x for x in artifacts(run_id, kind) if x["id"] == object_id), None)


def append_log(run_id, log):
    with transaction() as conn:
        for entry in log:
            _artifact(conn, run_id, "agent_log", uuid.uuid4().hex, entry.model_dump(mode="json"), "system")


def get_log(run_id):
    return [AgentLogEntry.model_validate(row) for row in artifacts(run_id, "agent_log")]


def save_narrative(run_id, jurisdiction, source, text, created_at):
    put_artifact(run_id, "narrative", f"{get_run(run_id).revision}:{jurisdiction}", {"source": source, "text": text}, "system")


def get_narrative(run_id, jurisdiction):
    row = get_artifact(run_id, "narrative", f"{get_run(run_id).revision}:{jurisdiction}")
    return (row["source"], row["text"]) if row else None


def update_findings(summary):
    save_run(summary, get_entries(summary.run_id), [], expected_revision=summary.revision)


def delete_run(run_id):
    raise ValueError("Audit inventories cannot be deleted. Create a correcting revision.")


def document_id(run_id, filename, content):
    return hashlib.sha256(run_id.encode() + filename.encode() + content).hexdigest()


def _document(conn, run_id, filename, content, actor):
    doc_id = document_id(run_id, filename, content)
    sha = hashlib.sha256(content).hexdigest()
    conn.execute("INSERT OR IGNORE INTO documents VALUES (?,?,?,?,?,?)", (doc_id, run_id, encrypt(filename), sha, encrypt(base64.b64encode(content)), now()))
    _event(conn, run_id, actor, "evidence.retained", {"document_id": doc_id, "sha256": sha})
    return doc_id


def add_document(run_id, filename, content, actor):
    with transaction() as conn:
        return _document(conn, run_id, filename, content, actor)


def documents(run_id):
    with _conn() as conn:
        rows = conn.execute("SELECT document_id,filename,sha256,created_at FROM documents WHERE run_id=?", (run_id,)).fetchall()
    return [{"document_id": r[0], "filename": decrypt(r[1]), "sha256": r[2], "created_at": r[3]} for r in rows]


def get_document(run_id, doc_id):
    with _conn() as conn:
        row = conn.execute("SELECT filename,content,sha256 FROM documents WHERE run_id=? AND document_id=?", (run_id, doc_id)).fetchone()
    if not row:
        return None
    data = base64.b64decode(decrypt(row[1]))
    if hashlib.sha256(data).hexdigest() != row[2]:
        raise ValueError("Evidence integrity check failed")
    return decrypt(row[0]), data


def audit(run_id=None):
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM audit_events" + (" WHERE run_id=?" if run_id else "") + " ORDER BY id", (run_id,) if run_id else ()).fetchall()
    return [{**dict(row), "payload": json.loads(decrypt(row["payload"]))} for row in rows]


def verify():
    previous = "0" * 64
    events = audit()
    errors = []
    snapshot_refs, artifact_refs, document_refs = set(), {}, {}
    for row in events:
        body = {k: row[k] for k in ("run_id", "actor", "action", "created_at", "payload", "previous_hash")}
        if row["previous_hash"] != previous or digest(body) != row["event_hash"] or not hmac.compare_digest(sign(row["event_hash"]), row["signature"]):
            errors.append(f"Audit event {row['id']} failed verification")
        previous = row["event_hash"]
        p = row["payload"]
        if "snapshot_sha256" in p:
            snapshot_refs.add((row["run_id"], p["revision"], p["snapshot_sha256"]))
        if "artifact_id" in p:
            artifact_refs[p["artifact_id"]] = p["body_sha256"]
        if "document_id" in p:
            document_refs[p["document_id"]] = p["sha256"]
    with _conn() as conn:
        stored_snapshots=set()
        for row in conn.execute("SELECT run_id,revision,body,digest FROM revisions"):
            stored_snapshots.add((row[0],row[1],row[3]))
            if digest(json.loads(decrypt(row[2]))) != row[3] or (row[0], row[1], row[3]) not in snapshot_refs:
                errors.append(f"Inventory {row[0]} revision {row[1]} changed")
        stored_artifacts=set()
        for row in conn.execute("SELECT id,body FROM artifacts"):
            stored_artifacts.add(row[0])
            if artifact_refs.get(row[0]) != digest(json.loads(decrypt(row[1]))):
                errors.append(f"Artifact {row[0]} changed")
        stored_documents=set()
        for row in conn.execute("SELECT document_id,content,sha256 FROM documents"):
            stored_documents.add(row[0])
            if hashlib.sha256(base64.b64decode(decrypt(row[1]))).hexdigest() != row[2] or document_refs.get(row[0]) != row[2]:
                errors.append(f"Evidence {row[0]} changed")
    if snapshot_refs-stored_snapshots: errors.append('Referenced inventory revisions are missing')
    if set(artifact_refs)-stored_artifacts: errors.append('Referenced artifacts are missing')
    if set(document_refs)-stored_documents: errors.append('Referenced evidence is missing')
    return {"valid": not errors, "events": len(events), "head": previous, "errors": errors, "verified_at": now()}


def migrate_legacy():
    """Baseline old inventories, explicitly without original-document authenticity."""
    with transaction() as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "runs" not in tables:
            return 0
        count = 0
        for row in conn.execute("SELECT run_id,summary FROM runs").fetchall():
            if conn.execute("SELECT 1 FROM revisions WHERE run_id=?", (row[0],)).fetchone():
                continue
            summary = RunSummary.model_validate_json(decrypt(row[1]))
            entries = [LedgerEntry.model_validate_json(decrypt(r[0])) for r in conn.execute("SELECT entry FROM entries WHERE run_id=?", (row[0],))]
            _snapshot(conn, summary, entries, "legacy-migration")
            for log in conn.execute("SELECT entry FROM agent_log WHERE run_id=?", (row[0],)).fetchall():
                _artifact(conn, row[0], "agent_log", uuid.uuid4().hex, json.loads(decrypt(log[0])), "legacy-migration")
            count += 1
        for table, columns in {"runs": ["summary"], "entries": ["entry"], "agent_log": ["entry"], "narratives": ["text"]}.items():
            if table not in tables:
                continue
            for col in columns:
                for row in conn.execute(f"SELECT rowid,{col} FROM {table}").fetchall():
                    if not row[1].startswith("enc:v1:"):
                        conn.execute(f"UPDATE {table} SET {col}=? WHERE rowid=?", (encrypt(row[1]), row[0]))
    return count
