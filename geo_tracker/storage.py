"""SQLite-backed append-only ledger.

Five tables:
  - runs:       one row per `geo-tracker run` invocation
  - events:     one row per (run, prompt, engine) call, with raw_response
  - parses:     one row per parse pass (the first pass of a run, or a reparse)
  - citations:  one row per (event, cited_url, parse), with parser_version
  - mentions:   one row per (event, brand, parse) for each brand the answer names

The schema is append-only by design. Nothing is updated or deleted. A
reparse adds a new parse row and new citation and mention rows. Readers use
the latest parse that covers a run, so a reparse never counts a row twice.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from geo_tracker.mentions import MATCHER_VERSION, Brand, Mention, brands_config
from geo_tracker.parser import Citation


def _strip_nul(value: Any) -> Any:
    """SQLite TEXT rejects embedded NUL bytes. Strip them recursively."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {k: _strip_nul(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nul(v) for v in value]
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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

-- run_id NULL means the parse covered every run that existed at created_at.
-- brands_json NULL means the parse did not measure brand mentions.
CREATE TABLE IF NOT EXISTS parses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    run_id INTEGER REFERENCES runs(id),
    parser_version INTEGER NOT NULL,
    self_domains_json TEXT NOT NULL,
    brands_json TEXT,
    matcher_version INTEGER
);

CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id),
    parser_version INTEGER NOT NULL,
    cited_url TEXT NOT NULL,
    cited_domain TEXT NOT NULL,
    rank INTEGER NOT NULL,
    snippet TEXT,
    is_self INTEGER NOT NULL DEFAULT 0,
    parse_id INTEGER REFERENCES parses(id)
);
CREATE INDEX IF NOT EXISTS idx_citations_event ON citations(event_id);
CREATE INDEX IF NOT EXISTS idx_citations_domain ON citations(cited_domain);

CREATE TABLE IF NOT EXISTS mentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id),
    parse_id INTEGER NOT NULL REFERENCES parses(id),
    matcher_version INTEGER NOT NULL,
    brand TEXT NOT NULL,
    n INTEGER NOT NULL,
    first_match TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mentions_event ON mentions(event_id);
CREATE INDEX IF NOT EXISTS idx_mentions_parse ON mentions(parse_id);
"""


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open the ledger. Commit on success, roll back on any exception."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, decl in columns.items():
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db(db_path: Path) -> None:
    """Create the tables. Add the newer columns to a ledger from v0.1 or v0.2."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        _add_missing_columns(conn, "citations", {"parse_id": "INTEGER REFERENCES parses(id)"})
        _add_missing_columns(
            conn, "parses", {"brands_json": "TEXT", "matcher_version": "INTEGER"}
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_citations_parse ON citations(parse_id)"
        )


def start_run(db_path: Path, label: str | None, config: dict[str, Any]) -> int:
    with connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO runs(started_at, label, config_json) VALUES(?, ?, ?)",
            (_now(), label, json.dumps(_strip_nul(config))),
        )
        assert cur.lastrowid is not None
        return cur.lastrowid


def insert_parse(
    conn: sqlite3.Connection,
    *,
    run_id: int | None,
    parser_version: int,
    self_domains: Iterable[str],
    brands: Iterable[Brand] | None = None,
) -> int:
    """Add a parse row. `brands=None` records that mentions were not measured."""
    cur = conn.execute(
        """INSERT INTO parses(created_at, run_id, parser_version, self_domains_json,
            brands_json, matcher_version)
           VALUES(?, ?, ?, ?, ?, ?)""",
        (
            _now(),
            run_id,
            parser_version,
            json.dumps(sorted(self_domains)),
            None if brands is None else json.dumps(_strip_nul(brands_config(brands))),
            None if brands is None else MATCHER_VERSION,
        ),
    )
    assert cur.lastrowid is not None
    return cur.lastrowid


def start_parse(
    db_path: Path,
    *,
    run_id: int | None,
    parser_version: int,
    self_domains: Iterable[str],
    brands: Iterable[Brand] | None = None,
) -> int:
    with connect(db_path) as conn:
        return insert_parse(
            conn,
            run_id=run_id,
            parser_version=parser_version,
            self_domains=self_domains,
            brands=brands,
        )


def insert_event(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    prompt: str,
    engine: str,
    model: str,
    fetch_status: str,
    fetch_error: str | None,
    response_text: str,
    raw_response: dict[str, Any],
    latency_ms: int,
) -> int:
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
    conn: sqlite3.Connection,
    event_id: int,
    parse_id: int,
    citations: Iterable[Citation],
) -> int:
    n = 0
    for c in citations:
        conn.execute(
            """INSERT INTO citations(event_id, parse_id, parser_version, cited_url,
                cited_domain, rank, snippet, is_self)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                parse_id,
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


def insert_mentions(
    conn: sqlite3.Connection,
    event_id: int,
    parse_id: int,
    mentions: Iterable[Mention],
) -> int:
    n = 0
    for m in mentions:
        conn.execute(
            """INSERT INTO mentions(event_id, parse_id, matcher_version, brand, n, first_match)
               VALUES(?, ?, ?, ?, ?, ?)""",
            (event_id, parse_id, MATCHER_VERSION, _strip_nul(m.brand), m.count,
             _strip_nul(m.first_match)),
        )
        n += 1
    return n


def record_event(
    db_path: Path,
    *,
    run_id: int,
    parse_id: int,
    prompt: str,
    engine: str,
    model: str,
    fetch_status: str,
    fetch_error: str | None,
    response_text: str,
    raw_response: dict[str, Any],
    latency_ms: int,
    citations: Iterable[Citation] = (),
    mentions: Iterable[Mention] = (),
) -> int:
    """Write one event, its citations and its mentions in one transaction."""
    with connect(db_path) as conn:
        event_id = insert_event(
            conn,
            run_id=run_id,
            prompt=prompt,
            engine=engine,
            model=model,
            fetch_status=fetch_status,
            fetch_error=fetch_error,
            response_text=response_text,
            raw_response=raw_response,
            latency_ms=latency_ms,
        )
        insert_citations(conn, event_id, parse_id, citations)
        insert_mentions(conn, event_id, parse_id, mentions)
        return event_id


def latest_parse_id(conn: sqlite3.Connection, run_id: int) -> int | None:
    """Return the newest parse that covers this run, or None for a v0.1 run.

    A run's own first parse is created when the run starts. Any parse with a
    NULL run_id and a higher id was made later and covered every run.
    """
    first = conn.execute(
        "SELECT MIN(id) AS pid FROM parses WHERE run_id = ?", (run_id,)
    ).fetchone()["pid"]
    row = conn.execute(
        """SELECT MAX(id) AS pid FROM parses
           WHERE run_id = ? OR (run_id IS NULL AND id > ?)""",
        (run_id, first if first is not None else 0),
    ).fetchone()
    return row["pid"]
