"""SQLite audit ledger. Append-only by convention: runs are never mutated after insert,
only narratives and log entries are added. Rows are stored as JSON so the ledger schema
never lags behind the Pydantic models."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

from ..schemas import AgentLogEntry, Finding, LedgerEntry, RunSummary

_DEFAULT = Path(__file__).resolve().parents[2] / "data" / "ledger.db"


def _path() -> Path:
    p = Path(os.getenv("LEDGER_PATH", str(_DEFAULT)))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_path())
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, created_at TEXT, summary TEXT);
        CREATE TABLE IF NOT EXISTS entries (run_id TEXT, line_id TEXT, entry TEXT, PRIMARY KEY (run_id, line_id));
        CREATE TABLE IF NOT EXISTS agent_log (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, entry TEXT);
        CREATE TABLE IF NOT EXISTS narratives (run_id TEXT, jurisdiction TEXT, source TEXT, text TEXT, created_at TEXT, PRIMARY KEY (run_id, jurisdiction));
        """
    )
    return c


def save_run(summary: RunSummary, entries: list[LedgerEntry], log: list[AgentLogEntry]) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?)", (summary.run_id, summary.created_at, summary.model_dump_json()))
        c.executemany("INSERT OR REPLACE INTO entries VALUES (?,?,?)", [(summary.run_id, e.item.line_id, e.model_dump_json()) for e in entries])
        c.executemany("INSERT INTO agent_log (run_id, entry) VALUES (?,?)", [(summary.run_id, l.model_dump_json()) for l in log])


def append_log(run_id: str, log: list[AgentLogEntry]) -> None:
    with _conn() as c:
        c.executemany("INSERT INTO agent_log (run_id, entry) VALUES (?,?)", [(run_id, l.model_dump_json()) for l in log])


def update_findings(summary: RunSummary) -> None:
    with _conn() as c:
        c.execute("UPDATE runs SET summary=? WHERE run_id=?", (summary.model_dump_json(), summary.run_id))


def list_runs() -> list[RunSummary]:
    with _conn() as c:
        rows = c.execute("SELECT summary FROM runs ORDER BY created_at DESC").fetchall()
    return [RunSummary.model_validate_json(r[0]) for r in rows]


def get_run(run_id: str) -> Optional[RunSummary]:
    with _conn() as c:
        row = c.execute("SELECT summary FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return RunSummary.model_validate_json(row[0]) if row else None


def get_entries(run_id: str) -> list[LedgerEntry]:
    with _conn() as c:
        rows = c.execute("SELECT entry FROM entries WHERE run_id=? ORDER BY line_id", (run_id,)).fetchall()
    return [LedgerEntry.model_validate_json(r[0]) for r in rows]


def get_entry(run_id: str, line_id: str) -> Optional[LedgerEntry]:
    with _conn() as c:
        row = c.execute("SELECT entry FROM entries WHERE run_id=? AND line_id=?", (run_id, line_id)).fetchone()
    return LedgerEntry.model_validate_json(row[0]) if row else None


def get_log(run_id: str) -> list[AgentLogEntry]:
    with _conn() as c:
        rows = c.execute("SELECT entry FROM agent_log WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
    return [AgentLogEntry.model_validate_json(r[0]) for r in rows]


def save_narrative(run_id: str, jurisdiction: str, source: str, text: str, created_at: str) -> None:
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO narratives VALUES (?,?,?,?,?)", (run_id, jurisdiction, source, text, created_at))


def get_narrative(run_id: str, jurisdiction: str) -> Optional[tuple[str, str]]:
    with _conn() as c:
        row = c.execute("SELECT source, text FROM narratives WHERE run_id=? AND jurisdiction=?", (run_id, jurisdiction)).fetchone()
    return (row[0], row[1]) if row else None


def delete_run(run_id: str) -> None:
    with _conn() as c:
        for t in ("runs", "entries", "agent_log", "narratives"):
            c.execute(f"DELETE FROM {t} WHERE run_id=?", (run_id,))
