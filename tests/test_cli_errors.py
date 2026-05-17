"""CLI error-path tests for findings Codex flagged on v0.1.0."""

import tempfile
from pathlib import Path


from geo_tracker.cli import main
from geo_tracker.storage import init_db


def test_summary_missing_run_id_returns_nonzero_with_message(capsys):
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "t.db"
        init_db(db)
        rc = main(["summary", "--db", str(db), "--run-id", "999"])
        captured = capsys.readouterr()
    assert rc == 1
    assert "not found" in captured.err.lower() or "no runs" in captured.err.lower()


def test_run_rejects_concurrent_below_one(capsys):
    rc = main(["run", "--concurrent", "0"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "--concurrent" in captured.err
