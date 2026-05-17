"""Re-parse historical raw responses into new citation rows.

Use when you change `self_domains.yaml` or bump `parser.PARSER_VERSION`. The
old citation rows stay around; new ones are inserted with the current
PARSER_VERSION tag. `summarize` always uses the latest parser_version per run.
"""

from __future__ import annotations

import json
from pathlib import Path

from geo_tracker.parser import PARSER_VERSION, extract_domain, parse_citations
from geo_tracker.runner import _load_yaml_list
from geo_tracker.storage import connect, insert_citations


def _normalize_self_domains(items: list) -> set[str]:
    out: set[str] = set()
    for d in items:
        s = str(d).strip().lower()
        if s.startswith(("http://", "https://")):
            s = extract_domain(s)
        elif s.startswith("www."):
            s = s[4:]
        if s:
            out.add(s)
    return out


def reparse(db_path: Path, self_domains_path: Path, run_id: int | None = None) -> dict:
    self_domains = _normalize_self_domains(_load_yaml_list(self_domains_path))
    n_events = 0
    n_citations = 0
    with connect(db_path) as conn:
        if run_id is not None:
            events = conn.execute(
                "SELECT id, raw_response_json FROM events WHERE run_id = ? AND fetch_status = 'ok'",
                (run_id,),
            ).fetchall()
        else:
            events = conn.execute(
                "SELECT id, raw_response_json FROM events WHERE fetch_status = 'ok'"
            ).fetchall()
        for ev in events:
            try:
                raw = json.loads(ev["raw_response_json"] or "{}")
            except json.JSONDecodeError:
                continue
            citations = parse_citations(raw, self_domains)
            if citations:
                insert_citations(db_path, ev["id"], citations)
                n_citations += len(citations)
            n_events += 1
    return {
        "events_reparsed": n_events,
        "citations_appended": n_citations,
        "parser_version": PARSER_VERSION,
        "self_domains": sorted(self_domains),
    }
