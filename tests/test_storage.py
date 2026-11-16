"""Storage layer: round trip, NUL bytes, atomic writes, mentions, migrations."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from geo_tracker.mentions import MATCHER_VERSION, Brand, Mention
from geo_tracker.parser import Citation
from geo_tracker.storage import (
    connect,
    init_db,
    latest_parse_id,
    record_event,
    start_parse,
    start_run,
)


def _cite(url: str = "https://example.com/a", snippet: str | None = "s") -> Citation:
    return Citation(parser_version=1, cited_url=url, cited_domain="example.com",
                    rank=1, snippet=snippet, is_self=True)


def test_round_trip_with_nul_bytes(db: Path):
    run_id = start_run(db, label="t1", config={"k": "v\x00bad"})
    parse_id = start_parse(db, run_id=run_id, parser_version=1, self_domains=["example.com"])
    event_id = record_event(
        db, run_id=run_id, parse_id=parse_id, prompt="hello", engine="perplexity",
        model="perplexity/sonar-pro", fetch_status="ok", fetch_error=None,
        response_text="reply with \x00nul\x00", raw_response={"junk": "x\x00y"},
        latency_ms=1234, citations=[_cite(snippet="snip\x00pet")],
    )
    with connect(db) as conn:
        ev = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        cit = conn.execute("SELECT * FROM citations").fetchone()
    assert ev["response_text"] == "reply with nul"
    assert cit["snippet"] == "snippet"
    assert cit["parse_id"] == parse_id


def test_record_event_is_atomic(db: Path):
    """A failed citation insert must not leave a bare event row behind."""
    run_id = start_run(db, label=None, config={})
    parse_id = start_parse(db, run_id=run_id, parser_version=1, self_domains=[])
    bad = Citation(parser_version=1, cited_url=None,  # type: ignore[arg-type]
                   cited_domain="x", rank=1, snippet=None, is_self=False)
    with pytest.raises(sqlite3.IntegrityError):
        record_event(
            db, run_id=run_id, parse_id=parse_id, prompt="p", engine="e", model="m",
            fetch_status="ok", fetch_error=None, response_text="t", raw_response={},
            latency_ms=1, citations=[bad],
        )
    with connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


V01_SCHEMA = """
CREATE TABLE runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL,
    label TEXT, config_json TEXT);
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER NOT NULL,
    prompt TEXT NOT NULL, engine TEXT NOT NULL, model TEXT NOT NULL,
    fetch_status TEXT NOT NULL, fetch_error TEXT, response_text TEXT,
    raw_response_json TEXT, latency_ms INTEGER,
    ts TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE citations (id INTEGER PRIMARY KEY AUTOINCREMENT, event_id INTEGER NOT NULL,
    parser_version INTEGER NOT NULL, cited_url TEXT NOT NULL, cited_domain TEXT NOT NULL,
    rank INTEGER NOT NULL, snippet TEXT, is_self INTEGER NOT NULL DEFAULT 0);
INSERT INTO runs VALUES (1, '2025-01-01', 'old', '{}');
INSERT INTO events(run_id, prompt, engine, model, fetch_status, response_text, raw_response_json)
    VALUES (1, 'p', 'perplexity', 'perplexity/sonar-pro', 'ok', 'x', '{}');
INSERT INTO citations(event_id, parser_version, cited_url, cited_domain, rank, is_self)
    VALUES (1, 1, 'https://example.com/a', 'example.com', 1, 1);
"""


def make_v01_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(V01_SCHEMA)
    conn.commit()
    conn.close()
    return path


def test_init_db_migrates_v01_ledger_without_touching_rows(tmp_path: Path):
    db = make_v01_db(tmp_path / "old.db")
    init_db(db)
    init_db(db)  # idempotent
    with connect(db) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(citations)")}
        row = conn.execute("SELECT parse_id, cited_url FROM citations").fetchone()
        assert latest_parse_id(conn, 1) is None
    assert "parse_id" in cols
    assert row["parse_id"] is None
    assert row["cited_url"] == "https://example.com/a"


def test_latest_parse_id_scopes(db: Path):
    r1 = start_run(db, label=None, config={})
    p1 = start_parse(db, run_id=r1, parser_version=1, self_domains=[])
    p_all = start_parse(db, run_id=None, parser_version=1, self_domains=[])
    r2 = start_run(db, label=None, config={})
    p2 = start_parse(db, run_id=r2, parser_version=1, self_domains=[])
    p1b = start_parse(db, run_id=r1, parser_version=1, self_domains=[])
    with connect(db) as conn:
        # r1: its own reparse is newest. r2: the all-runs parse predates r2.
        assert latest_parse_id(conn, r1) == p1b
        assert latest_parse_id(conn, r2) == p2
    assert p1 < p_all < p2 < p1b


def test_mentions_round_trip_tied_to_a_parse(db: Path):
    run_id = start_run(db, label=None, config={})
    parse_id = start_parse(db, run_id=run_id, parser_version=1, self_domains=[],
                           brands=[Brand(name="Acme", aliases=("Acme", "acme.io"))])
    record_event(
        db, run_id=run_id, parse_id=parse_id, prompt="p", engine="e", model="m",
        fetch_status="ok", fetch_error=None, response_text="Acme\x00", raw_response={},
        latency_ms=1, mentions=[Mention(brand="Acme", count=2, first_match="Ac\x00me")],
    )
    with connect(db) as conn:
        m = conn.execute("SELECT * FROM mentions").fetchone()
        p = conn.execute("SELECT * FROM parses WHERE id = ?", (parse_id,)).fetchone()
    assert (m["parse_id"], m["brand"], m["n"], m["first_match"]) == (parse_id, "Acme", 2, "Acme")
    assert m["matcher_version"] == MATCHER_VERSION
    assert json.loads(p["brands_json"]) == [{"name": "Acme", "aliases": ["Acme", "acme.io"]}]
    assert p["matcher_version"] == MATCHER_VERSION


def test_parse_without_brands_stores_null(db: Path):
    """NULL means "not measured". It must differ from "measured, no mentions"."""
    run_id = start_run(db, label=None, config={})
    parse_id = start_parse(db, run_id=run_id, parser_version=1, self_domains=[])
    with connect(db) as conn:
        p = conn.execute("SELECT brands_json, matcher_version FROM parses WHERE id = ?",
                         (parse_id,)).fetchone()
    assert p["brands_json"] is None and p["matcher_version"] is None


def test_init_db_migrates_v02_ledger(tmp_path: Path):
    """A v0.2 ledger has `parses` without the brand columns and no `mentions` table."""
    db = make_v01_db(tmp_path / "v02.db")
    conn = sqlite3.connect(db)
    conn.executescript(V02_PARSES)
    conn.commit()
    conn.close()
    init_db(db)
    init_db(db)
    with connect(db) as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(parses)")}
        row = conn.execute("SELECT * FROM parses").fetchone()
        assert conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0] == 0
    assert {"brands_json", "matcher_version"} <= cols
    assert row["self_domains_json"] == '["example.com"]'
    assert row["brands_json"] is None


V02_PARSES = """
CREATE TABLE parses (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
    run_id INTEGER REFERENCES runs(id), parser_version INTEGER NOT NULL,
    self_domains_json TEXT NOT NULL);
INSERT INTO parses VALUES (1, '2026-01-01', 1, 1, '["example.com"]');
"""
