"""Reparse and summary read one interpretation per run."""

from __future__ import annotations

from pathlib import Path

import pytest

from geo_tracker.mentions import Brand, find_mentions
from geo_tracker.parser import parse_citations
from geo_tracker.reparse import reparse
from geo_tracker.storage import connect, record_event, start_parse, start_run
from geo_tracker.summarize import print_summary, summarize_run
from conftest import make_raw
from test_storage import make_v01_db


def _seed(db: Path, self_domains: set[str], brands: list[Brand] | None = None) -> int:
    run_id = start_run(db, label="w1", config={})
    parse_id = start_parse(db, run_id=run_id, parser_version=1, self_domains=self_domains,
                           brands=brands)
    cells = [
        ("perplexity", "ok", make_raw("https://example.com/a", "https://other.com/b"),
         "Acme on acme.io"),
        ("openai", "ok", make_raw("https://other.com/c"), "Globex"),
        ("openai", "error", {}, "Acme"),
    ]
    for engine, status, raw, text in cells:
        record_event(
            db, run_id=run_id, parse_id=parse_id, prompt="p", engine=engine, model="m",
            fetch_status=status, fetch_error=None if status == "ok" else "HTTP 500",
            response_text=text, raw_response=raw, latency_ms=1,
            citations=parse_citations(raw, self_domains) if status == "ok" else [],
            mentions=find_mentions(text, brands or []) if status == "ok" else [],
        )
    return run_id


def _domains(summary: dict) -> dict[str, int]:
    return {r["cited_domain"]: r["n"] for r in summary["top_domains"]}


def test_summary_counts_failed_cells_apart(db: Path):
    run_id = _seed(db, {"example.com"})
    s = summarize_run(db, run_id)
    assert s["engines"]["perplexity"] == {
        "ok": 1, "failed": 0, "cells_citing_self": 1, "self_citations": 1,
        "cells_mentioning": None}
    assert s["engines"]["openai"] == {
        "ok": 1, "failed": 1, "cells_citing_self": 0, "self_citations": 0,
        "cells_mentioning": None}
    assert s["brands"] is None
    assert _domains(s) == {"other.com": 2, "example.com": 1}


def test_reparse_with_same_parser_version_does_not_double_count(db: Path, self_domains_file: Path):
    """Regression: summary took MAX(parser_version), and a reparse without a
    version bump appended rows with the same version. Every count doubled."""
    run_id = _seed(db, {"example.com"})
    reparse(db, self_domains_file)
    reparse(db, self_domains_file, run_id=run_id)
    assert _domains(summarize_run(db, run_id)) == {"other.com": 2, "example.com": 1}


def test_reparse_applies_new_self_domains(db: Path, tmp_path: Path):
    run_id = _seed(db, set())
    assert summarize_run(db, run_id)["engines"]["perplexity"]["self_citations"] == 0
    sd = tmp_path / "sd.yaml"
    sd.write_text("- https://www.other.com\n", encoding="utf-8")
    result = reparse(db, sd)
    assert result["events_reparsed"] == 2
    s = summarize_run(db, run_id)
    assert s["parse_id"] == result["parse_id"]
    assert s["engines"]["openai"]["self_citations"] == 1
    with connect(db) as conn:  # append-only: the first parse is still there
        assert conn.execute("SELECT COUNT(DISTINCT parse_id) FROM citations").fetchone()[0] == 2


def test_reparse_rolls_back_on_corrupt_raw_response(db: Path, self_domains_file: Path):
    run_id = _seed(db, {"example.com"})
    with connect(db) as conn:
        conn.execute("UPDATE events SET raw_response_json = 'not json' WHERE engine = 'openai'")
        n_parses = conn.execute("SELECT COUNT(*) FROM parses").fetchone()[0]
        n_cites = conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0]
    with pytest.raises(ValueError, match="not valid JSON"):
        reparse(db, self_domains_file, run_id=run_id)
    with connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM parses").fetchone()[0] == n_parses
        assert conn.execute("SELECT COUNT(*) FROM citations").fetchone()[0] == n_cites


def test_reparse_unknown_run_id(db: Path, self_domains_file: Path):
    with pytest.raises(ValueError, match="not found"):
        reparse(db, self_domains_file, run_id=99)


def test_summary_and_reparse_on_v01_ledger(tmp_path: Path, self_domains_file: Path):
    db = make_v01_db(tmp_path / "old.db")
    s = summarize_run(db, 1)
    assert s["parse_id"] is None
    assert _domains(s) == {"example.com": 1}
    # The stored v0.1 raw response ({}) has no citations, so the new parse has none.
    result = reparse(db, self_domains_file)
    assert summarize_run(db, 1)["parse_id"] == result["parse_id"]
    assert _domains(summarize_run(db, 1)) == {}


def test_summary_missing_db_is_not_created(tmp_path: Path):
    db = tmp_path / "missing.db"
    assert "not found" in summarize_run(db)["error"]
    assert not db.exists()


def test_summary_no_runs(db: Path):
    assert summarize_run(db)["error"] == "no runs yet"


def _mention_rows(db: Path, parse_id: int) -> list[tuple[str, int]]:
    with connect(db) as conn:
        rows = conn.execute(
            """SELECT e.engine, m.n FROM mentions m JOIN events e ON m.event_id = e.id
               WHERE m.parse_id = ? ORDER BY e.engine""", (parse_id,)).fetchall()
    return [tuple(r) for r in rows]


def test_reparse_recomputes_mentions_without_double_counts(db: Path, self_domains_file: Path,
                                                           tmp_path: Path):
    _seed(db, {"example.com"})
    brands = tmp_path / "brands.yaml"
    brands.write_text("- name: Acme\n  aliases: [acme.io]\n", encoding="utf-8")
    first = reparse(db, self_domains_file, brands_path=brands)
    second = reparse(db, self_domains_file, brands_path=brands)
    assert first["mentions_appended"] == second["mentions_appended"] == 1
    # The seeded perplexity answer is "Acme on acme.io". The failed cell is skipped.
    assert _mention_rows(db, first["parse_id"]) == [("perplexity", 2)]
    assert _mention_rows(db, second["parse_id"]) == [("perplexity", 2)]
    brands.write_text("- Globex\n", encoding="utf-8")
    third = reparse(db, self_domains_file, brands_path=brands)
    assert _mention_rows(db, third["parse_id"]) == [("openai", 1)]


def test_reparse_without_brands_records_not_measured(db: Path, self_domains_file: Path):
    _seed(db, {"example.com"})
    result = reparse(db, self_domains_file)
    assert result["brands"] is None
    with connect(db) as conn:
        assert conn.execute("SELECT brands_json FROM parses WHERE id = ?",
                            (result["parse_id"],)).fetchone()[0] is None


ACME = [Brand(name="Acme", aliases=("Acme", "acme.io"))]


def test_summary_counts_mentions_in_ok_cells_only(db: Path):
    """The failed openai cell says "Acme" but must not count as a mention."""
    run_id = _seed(db, {"example.com"}, brands=ACME)
    s = summarize_run(db, run_id)
    assert s["brands"] == ["Acme"]
    assert s["engines"]["perplexity"]["cells_mentioning"] == 1
    assert s["engines"]["openai"]["cells_mentioning"] == 0
    assert s["engines"]["openai"]["failed"] == 1


def test_summary_mentions_follow_the_latest_parse(db: Path, self_domains_file: Path,
                                                  tmp_path: Path):
    run_id = _seed(db, {"example.com"}, brands=ACME)
    brands = tmp_path / "brands.yaml"
    brands.write_text("- Acme\n", encoding="utf-8")
    reparse(db, self_domains_file, brands_path=brands)
    reparse(db, self_domains_file, brands_path=brands)
    s = summarize_run(db, run_id)
    assert {e: d["cells_mentioning"] for e, d in s["engines"].items()} == {
        "perplexity": 1, "openai": 0}
    brands.write_text("- Globex\n", encoding="utf-8")
    reparse(db, self_domains_file, run_id=run_id, brands_path=brands)
    s = summarize_run(db, run_id)
    assert {e: d["cells_mentioning"] for e, d in s["engines"].items()} == {
        "perplexity": 0, "openai": 1}
    reparse(db, self_domains_file)  # no brands: the latest parse did not measure
    s = summarize_run(db, run_id)
    assert s["brands"] is None
    assert s["engines"]["openai"]["cells_mentioning"] is None


def test_summary_counts_a_cell_once_for_many_mentions(db: Path):
    run_id = start_run(db, label=None, config={})
    brands = ACME + [Brand(name="Globex", aliases=("Globex",))]
    parse_id = start_parse(db, run_id=run_id, parser_version=1, self_domains=[], brands=brands)
    text = "Acme, acme.io and Globex."
    record_event(db, run_id=run_id, parse_id=parse_id, prompt="p", engine="openai", model="m",
                 fetch_status="ok", fetch_error=None, response_text=text, raw_response={},
                 latency_ms=1, mentions=find_mentions(text, brands))
    assert summarize_run(db, run_id)["engines"]["openai"]["cells_mentioning"] == 1


def test_v01_run_shows_mentions_as_not_measured(tmp_path: Path):
    db = make_v01_db(tmp_path / "old.db")
    s = summarize_run(db, 1)
    assert s["brands"] is None
    assert s["engines"]["perplexity"]["cells_mentioning"] is None


def test_print_summary_shows_mentions_next_to_citations(db: Path,
                                                         capsys: pytest.CaptureFixture[str]):
    run_id = _seed(db, {"example.com"}, brands=ACME)
    print_summary(summarize_run(db, run_id))
    out = capsys.readouterr().out
    assert "brands: Acme" in out
    lines = {ln.split()[0]: ln for ln in out.splitlines() if ln.startswith("  ") and "/" in ln}
    assert lines["openai"].split()[1:] == ["0", "/", "1", "0", "0", "/", "1",
                                           "(1", "failed,", "not", "counted)"]
    assert lines["perplexity"].split()[1:] == ["1", "/", "1", "1", "1", "/", "1"]


def test_print_summary_marks_mentions_not_measured(db: Path,
                                                    capsys: pytest.CaptureFixture[str]):
    run_id = _seed(db, {"example.com"})
    print_summary(summarize_run(db, run_id))
    out = capsys.readouterr().out
    assert "brands: not measured" in out
    perplexity = next(ln for ln in out.splitlines() if ln.startswith("  perplexity") and "/" in ln)
    assert perplexity.split()[1:] == ["1", "/", "1", "1", "-"]
