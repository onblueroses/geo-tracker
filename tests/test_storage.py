"""Storage layer round-trip + NUL-byte stripping."""

import tempfile
from pathlib import Path

from geo_tracker.parser import Citation
from geo_tracker.storage import init_db, insert_citations, insert_event, start_run


def test_round_trip_with_nul_bytes():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "test.db"
        init_db(db)
        run_id = start_run(db, label="t1", config={"k": "v\x00bad"})
        event_id = insert_event(
            db,
            run_id=run_id,
            prompt="hello",
            engine="perplexity",
            model="perplexity/sonar-pro",
            fetch_status="ok",
            fetch_error=None,
            response_text="reply with \x00nul\x00",
            raw_response={"choices": [], "junk": "x\x00y"},
            latency_ms=1234,
        )
        n = insert_citations(
            db,
            event_id,
            [
                Citation(
                    parser_version=1,
                    cited_url="https://example.com/a",
                    cited_domain="example.com",
                    rank=1,
                    snippet="snip\x00pet",
                    is_self=True,
                )
            ],
        )
        assert n == 1
        assert run_id == 1
        assert event_id == 1
