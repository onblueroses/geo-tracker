"""Re-parse historical raw responses into new citation rows.

Use when you change `self_domains.yaml` or bump `parser.PARSER_VERSION`. The
old citation rows stay. One reparse adds one parse row and its citation rows
in a single transaction. `summarize` reads the latest parse per run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from geo_tracker.parser import PARSER_VERSION, parse_citations
from geo_tracker.runner import load_self_domains
from geo_tracker.storage import connect, insert_citations, insert_parse


def reparse(
    db_path: Path, self_domains_path: Path, run_id: int | None = None
) -> dict[str, Any]:
    """Re-parse every `ok` event in scope.

    It fails closed. If one stored response does not decode or parse, the
    whole reparse rolls back, so no run gets a partial parse.
    """
    self_domains = load_self_domains(self_domains_path)
    n_events = 0
    n_citations = 0
    with connect(db_path) as conn:
        if run_id is not None:
            if conn.execute("SELECT 1 FROM runs WHERE id = ?", (run_id,)).fetchone() is None:
                raise ValueError(f"run_id {run_id} not found")
            events = conn.execute(
                "SELECT id, raw_response_json FROM events WHERE run_id = ? AND fetch_status = 'ok'",
                (run_id,),
            ).fetchall()
        else:
            events = conn.execute(
                "SELECT id, raw_response_json FROM events WHERE fetch_status = 'ok'"
            ).fetchall()
        parse_id = insert_parse(
            conn,
            run_id=run_id,
            parser_version=PARSER_VERSION,
            self_domains=self_domains,
        )
        for ev in events:
            try:
                raw = json.loads(ev["raw_response_json"] or "")
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"event {ev['id']}: stored raw response is not valid JSON"
                ) from exc
            citations = parse_citations(raw, self_domains)
            n_citations += insert_citations(conn, ev["id"], parse_id, citations)
            n_events += 1
    return {
        "parse_id": parse_id,
        "events_reparsed": n_events,
        "citations_appended": n_citations,
        "parser_version": PARSER_VERSION,
        "self_domains": sorted(self_domains),
    }
