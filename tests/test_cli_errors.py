"""CLI exit codes and error paths. No network calls."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from geo_tracker.adapters import EventPayload
from geo_tracker.cli import main
from conftest import make_raw


def test_summary_missing_run_id_returns_nonzero(db: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(["summary", "--db", str(db), "--run-id", "999"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_summary_missing_db_returns_nonzero_and_creates_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    """Regression: summary created an empty DB, then crashed on `no such table`."""
    db = tmp_path / "missing.db"
    assert main(["summary", "--db", str(db)]) == 1
    assert "database not found" in capsys.readouterr().err
    assert not db.exists()


def test_reparse_missing_db(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    db = tmp_path / "missing.db"
    assert main(["reparse", "--db", str(db)]) == 1
    assert not db.exists()


def test_reparse_missing_self_domains(db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    rc = main(["reparse", "--db", str(db), "--self-domains", str(tmp_path / "nope.yaml")])
    assert rc == 2
    assert "missing config file" in capsys.readouterr().err


def test_run_rejects_concurrent_below_one(capsys: pytest.CaptureFixture[str]):
    assert main(["run", "--concurrent", "0"]) == 2
    assert "--concurrent" in capsys.readouterr().err


def test_run_rejects_unknown_engine(capsys: pytest.CaptureFixture[str]):
    assert main(["run", "--engines", "openai,openia"]) == 2
    assert "openia" in capsys.readouterr().err


def _workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    (tmp_path / "prompts.yaml").write_text("- q1\n- q2\n", encoding="utf-8")
    (tmp_path / "self_domains.yaml").write_text("- example.com\n", encoding="utf-8")
    return [
        "--db", str(tmp_path / "t.db"),
        "--prompts", str(tmp_path / "prompts.yaml"),
        "--self-domains", str(tmp_path / "self_domains.yaml"),
        "--env", str(tmp_path / ".env"),
    ]


def _fake_query(results: dict[str, EventPayload]):
    async def query(self: Any, prompt: str) -> EventPayload:
        return results.get(self.name, results["*"])
    return query


def test_run_exits_one_when_a_cell_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]):
    ok = EventPayload(response_text="x", raw_response=make_raw("https://example.com/a"),
                      fetch_status="ok")
    bad = EventPayload(response_text="", fetch_status="timeout", fetch_error="timed out")
    monkeypatch.setattr("geo_tracker.adapters.engines.EngineAdapter.query",
                        _fake_query({"gemini": bad, "*": ok}))
    rc = main(["run", *_workspace(tmp_path, monkeypatch)])
    out = capsys.readouterr()
    assert rc == 1
    assert "2 of 8 cells failed" in out.err

    assert main(["summary", "--db", str(tmp_path / "t.db")]) == 0
    text = capsys.readouterr().out
    assert "gemini" in text and "2 failed, not counted" in text


def test_run_exits_zero_when_all_cells_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ok = EventPayload(response_text="x", raw_response=make_raw("https://example.com/a"),
                      fetch_status="ok")
    monkeypatch.setattr("geo_tracker.adapters.engines.EngineAdapter.query",
                        _fake_query({"*": ok}))
    assert main(["run", "--engines", "openai", *_workspace(tmp_path, monkeypatch)]) == 0


def test_run_bad_prompts_file_writes_no_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]):
    args = _workspace(tmp_path, monkeypatch)
    (tmp_path / "prompts.yaml").write_text("[]\n", encoding="utf-8")
    assert main(["run", *args]) == 2
    assert "no prompts" in capsys.readouterr().err
    assert not (tmp_path / "t.db").exists()
