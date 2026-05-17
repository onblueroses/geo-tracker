"""SQLite-backed append-only ledger.

Three tables:
  - runs:          one row per `geo-tracker run` invocation
  - events:        one row per (run, prompt, engine) call, with raw_response
  - citations:     one row per (event, cited_url), with parser_version tag

The schema is append-only by design. If you change the parser, bump
parser.PARSER_VERSION and re-parse historical events into new citation rows —
old rows stay around so you can compare interpretations over time.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from geo_tracker.parser import Citation


def _strip_nul(value):
    """SQLite TEXT rejects embedded NUL bytes; strip recursively."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _strip_nul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nul(v) for v in value]
    return value


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    label TEXT,
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    prompt TEXT NOT NULL,
    engine TEXT NOT NULL,
    model TEXT NOT NULL,
    fetch_status TEXT NOT NULL,
    fetch_error TEXT,
    response_text TEXT,
    raw_response_json TEXT,
    latency_ms INTEGER,
    ts TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);
CREATE INDEX IF NOT EXISTS idx_events_engine ON events(engine);

CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id),
    parser_version INTEGER NOT NULL,
    cited_url TEXT NOT NULL,
    cited_domain TEXT NOT NULL,
    rank INTEGER NOT NULL,
    snippet TEXT,
    is_self INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_citations_event ON citations(event_id);
CREATE INDEX IF NOT EXISTS idx_citations_domain ON citations(cited_domain);
"""


@contextmanager
def connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def start_run(db_path: Path, label: str | None, config: dict) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO runs(started_at, label, config_json) VALUES(?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                label,
                json.dumps(_strip_nul(config)),
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid


def insert_event(
    db_path: Path,
    *,
    run_id: int,
    prompt: str,
    engine: str,
    model: str,
    fetch_status: str,
    fetch_error: str | None,
    response_text: str,
    raw_response: dict,
    latency_ms: int,
) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO events(run_id, prompt, engine, model, fetch_status,
                fetch_error, response_text, raw_response_json, latency_ms)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                _strip_nul(prompt),
                engine,
                model,
                fetch_status,
                _strip_nul(fetch_error),
                _strip_nul(response_text),
                json.dumps(_strip_nul(raw_response)),
                latency_ms,
            ),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid


def insert_citations(
    db_path: Path, event_id: int, citations: Iterable[Citation]
) -> int:
    n = 0
    with connect(db_path) as conn:
        for c in citations:
            conn.execute(
                """INSERT INTO citations(event_id, parser_version, cited_url,
                    cited_domain, rank, snippet, is_self)
                   VALUES(?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    c.parser_version,
                    _strip_nul(c.cited_url),
                    _strip_nul(c.cited_domain),
                    c.rank,
                    _strip_nul(c.snippet),
                    1 if c.is_self else 0,
                ),
            )
            n += 1
    return n
