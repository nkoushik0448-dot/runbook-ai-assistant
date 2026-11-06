"""Query / triage history logging to a local SQLite file.

Every /ask, /ask-ai and /triage request is logged with a timestamp,
its type, the raw input, the matched runbook ids, and the top score.
Entries of type "ask-ai" also record the model that answered (e.g.
"llama3.2:3b"). This is the observability part of the project: an
on-call engineer can see what was asked, what was matched, and what
was not matched.

The database file (history.db) is gitignored — it is local runtime
state, not source data.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    type TEXT NOT NULL,
    input TEXT NOT NULL,
    matched_runbook_ids TEXT NOT NULL,
    top_score INTEGER NOT NULL,
    model TEXT
);
"""


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute(_SCHEMA)
    # Migrate DBs created before the model column existed (used by
    # /ask-ai entries to record which LLM answered).
    columns = [row[1] for row in conn.execute("PRAGMA table_info(history)")]
    if "model" not in columns:
        conn.execute("ALTER TABLE history ADD COLUMN model TEXT")
    conn.commit()
    return conn


def log_entry(
    *,
    entry_type: str,
    input_text: str,
    matched_runbook_ids: list[str],
    top_score: int,
    model: str | None = None,
    db_path: Path | str = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Persist one history entry and return it as a dict.

    model records which LLM answered (e.g. "llama3.2:3b") for
    entry_type "ask-ai"; it is None for ask / triage entries.
    """
    conn = init_db(db_path)
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "INSERT INTO history (timestamp, type, input, matched_runbook_ids, top_score, model)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, entry_type, input_text, ",".join(matched_runbook_ids), top_score, model),
        )
        conn.commit()
        return {
            "id": cur.lastrowid,
            "timestamp": timestamp,
            "type": entry_type,
            "input": input_text,
            "matched_runbook_ids": matched_runbook_ids,
            "top_score": top_score,
            "model": model,
        }
    finally:
        conn.close()


def list_entries(
    limit: int = 100, db_path: Path | str = DEFAULT_DB_PATH
) -> list[dict[str, Any]]:
    """List history entries, newest first."""
    conn = init_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id, timestamp, type, input, matched_runbook_ids, top_score, model"
            " FROM history ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row[0],
            "timestamp": row[1],
            "type": row[2],
            "input": row[3],
            "matched_runbook_ids": [s for s in row[4].split(",") if s],
            "top_score": row[5],
            "model": row[6],
        }
        for row in rows
    ]
