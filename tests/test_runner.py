"""Regression tests for findings Codex flagged on v0.1.0."""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch


from geo_tracker.parser import extract_domain
from geo_tracker.reparse import _normalize_self_domains


def test_self_domain_normalization_preserves_words_starting_with_w():
    """Regression: `.lstrip("www.")` ate the 'w', 'a', 'l' from "walmart.com".

    `lstrip` strips a CHAR SET, not a prefix string. Use removeprefix or
    extract_domain instead.
    """
    raw = ["walmart.com", "webflow.com", "www2.example.com", "www.example.com"]
    norm = _normalize_self_domains(raw)
    assert "walmart.com" in norm  # was "almart.com" with lstrip
    assert "webflow.com" in norm  # was "ebflow.com"
    assert "www2.example.com" in norm  # was "2.example.com"
    assert "example.com" in norm  # www. correctly stripped


def test_self_domain_normalization_accepts_full_urls():
    raw = ["https://docs.example.com/api", "http://www.example.com"]
    norm = _normalize_self_domains(raw)
    assert "docs.example.com" in norm
    assert "example.com" in norm


def test_extract_domain_consistency():
    """extract_domain is the canonical normalizer; both runner and reparse use it."""
    assert extract_domain("https://www.walmart.com/foo") == "walmart.com"
    assert extract_domain("https://www.webflow.com") == "webflow.com"


def test_run_inserts_error_row_on_unexpected_exception():
    """Codex finding: a parser/storage exception inside _run_cell should still
    produce a row, not silently lose the cell."""
    from geo_tracker import runner as runner_mod
    from geo_tracker.adapters.base import EventPayload
    from geo_tracker.storage import connect, init_db

    class _FakeAdapter:
        name = "fake"
        model = "fake-model"

        async def query(self, prompt):
            return EventPayload(
                response_text="x",
                raw_response={"will": "crash parser"},
                latency_ms=10,
                fetch_status="ok",
            )

    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        init_db(db)
        from geo_tracker.storage import start_run

        run_id = start_run(db, label="t", config={})
        sem = asyncio.Semaphore(1)

        # Patch parse_citations to raise.
        with patch(
            "geo_tracker.runner.parse_citations", side_effect=RuntimeError("boom")
        ):
            engine, status, n = asyncio.run(
                runner_mod._run_cell(
                    db, run_id, _FakeAdapter(), "p", {"example.com"}, sem
                )
            )
        assert engine == "fake"
        assert status == "error"
        with connect(db) as conn:
            rows = conn.execute(
                "SELECT engine, fetch_status, fetch_error FROM events WHERE run_id=?",
                (run_id,),
            ).fetchall()
        # First row = ok insert before the exception, second = error fallback.
        # Or just the error row, depending on where the patch lands.
        # The contract: at least one error row exists for this cell.
        assert any(
            r["fetch_status"] == "error" and "boom" in (r["fetch_error"] or "")
            for r in rows
        )
