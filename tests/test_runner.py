"""Runner: one fail-closed event row per cell. No network calls."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from geo_tracker import runner
from geo_tracker.adapters import EventPayload
from geo_tracker.mentions import Brand
from geo_tracker.storage import connect, start_parse, start_run
from conftest import make_raw


class FakeAdapter:
    name = "fake"
    model = "fake-model"

    def __init__(self, result: EventPayload | Exception) -> None:
        self.result = result

    async def query(self, prompt: str) -> EventPayload:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _run_cell(db: Path, adapter: FakeAdapter) -> tuple[tuple[str, str, int], list[Any]]:
    run_id = start_run(db, label="t", config={})
    parse_id = start_parse(db, run_id=run_id, parser_version=1, self_domains=["example.com"])
    result = asyncio.run(
        runner._run_cell(db, run_id, parse_id, adapter, "p", {"example.com"},
                         asyncio.Semaphore(1))
    )
    with connect(db) as conn:
        rows = conn.execute(
            "SELECT fetch_status, fetch_error, raw_response_json FROM events WHERE run_id = ?",
            (run_id,),
        ).fetchall()
    return result, rows


def test_ok_cell_writes_event_and_citations(db: Path):
    ok = EventPayload(response_text="x", raw_response=make_raw("https://example.com/a"),
                      fetch_status="ok")
    (engine, status, n), rows = _run_cell(db, FakeAdapter(ok))
    assert (engine, status, n) == ("fake", "ok", 1)
    assert [r["fetch_status"] for r in rows] == ["ok"]


def test_parse_failure_writes_one_parse_error_row(db: Path):
    """Regression: a parser crash left an `ok` row with zero citations plus an
    `error` row. The `ok` row read as "answered, cited nothing"."""
    ok = EventPayload(response_text="x", raw_response=make_raw("https://example.com/a"),
                      fetch_status="ok")
    with patch("geo_tracker.runner.parse_citations", side_effect=RuntimeError("boom")):
        (_, status, n), rows = _run_cell(db, FakeAdapter(ok))
    assert (status, n) == ("parse_error", 0)
    assert [r["fetch_status"] for r in rows] == ["parse_error"]
    assert "boom" in rows[0]["fetch_error"]
    assert "example.com" in rows[0]["raw_response_json"]  # kept for inspection


def test_adapter_exception_writes_error_row(db: Path):
    (_, status, _), rows = _run_cell(db, FakeAdapter(RuntimeError("adapter broke")))
    assert status == "error"
    assert [r["fetch_status"] for r in rows] == ["error"]
    assert "adapter broke" in rows[0]["fetch_error"]


def test_storage_failure_falls_back_to_error_row(db: Path):
    ok = EventPayload(response_text="x", raw_response=make_raw("https://example.com/a"),
                      fetch_status="ok")
    real = runner.record_event
    calls = {"n": 0}

    def flaky(*args: Any, **kwargs: Any) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real(*args, **kwargs)

    with patch("geo_tracker.runner.record_event", side_effect=flaky):
        (_, status, n), rows = _run_cell(db, FakeAdapter(ok))
    assert (status, n) == ("error", 0)
    assert [r["fetch_status"] for r in rows] == ["error"]
    assert "disk full" in rows[0]["fetch_error"]


def test_load_prompts_rejects_bad_entries(tmp_path: Path):
    p = tmp_path / "prompts.yaml"
    p.write_text("- good question\n- 42\n", encoding="utf-8")
    with pytest.raises(ValueError, match="entry 1"):
        runner.load_prompts(p)
    p.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no prompts"):
        runner.load_prompts(p)
    p.write_text("prompts:\n  - '  padded  '\n", encoding="utf-8")
    assert runner.load_prompts(p) == ["padded"]
    with pytest.raises(FileNotFoundError):
        runner.load_prompts(tmp_path / "missing.yaml")


def test_ok_cell_writes_mentions_for_its_parse(db: Path):
    ok = EventPayload(response_text="Acme and acme.io, not Acmeville.",
                      raw_response=make_raw(), fetch_status="ok")
    brands = [Brand(name="Acme", aliases=("Acme", "acme.io"))]
    run_id = start_run(db, label="t", config={})
    parse_id = start_parse(db, run_id=run_id, parser_version=1, self_domains=[], brands=brands)
    asyncio.run(runner._run_cell(db, run_id, parse_id, FakeAdapter(ok), "p", set(),
                                 asyncio.Semaphore(1), brands))
    with connect(db) as conn:
        rows = conn.execute("SELECT parse_id, brand, n FROM mentions").fetchall()
    assert [tuple(r) for r in rows] == [(parse_id, "Acme", 2)]


def test_failed_cell_writes_no_mentions(db: Path):
    bad = EventPayload(response_text="Acme", fetch_status="error", fetch_error="HTTP 500")
    brands = [Brand(name="Acme", aliases=("Acme",))]
    run_id = start_run(db, label="t", config={})
    parse_id = start_parse(db, run_id=run_id, parser_version=1, self_domains=[], brands=brands)
    asyncio.run(runner._run_cell(db, run_id, parse_id, FakeAdapter(bad), "p", set(),
                                 asyncio.Semaphore(1), brands))
    with connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0] == 0


def test_matcher_failure_writes_one_parse_error_row(db: Path):
    ok = EventPayload(response_text="Acme", raw_response=make_raw(), fetch_status="ok")
    brands = [Brand(name="Acme", aliases=("Acme",))]
    run_id = start_run(db, label="t", config={})
    parse_id = start_parse(db, run_id=run_id, parser_version=1, self_domains=[], brands=brands)
    with patch("geo_tracker.runner.find_mentions", side_effect=RuntimeError("boom")):
        _, status, _ = asyncio.run(runner._run_cell(
            db, run_id, parse_id, FakeAdapter(ok), "p", set(), asyncio.Semaphore(1), brands))
    assert status == "parse_error"
    with connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0] == 0
