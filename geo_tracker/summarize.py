"""Read a run from the ledger and produce a citation summary."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from geo_tracker.storage import connect, init_db, latest_parse_id


def _citation_filter(conn: sqlite3.Connection, run_id: int) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
    """Return the SQL condition that picks one interpretation of a run.

    Runs since v0.2 use their latest parse. A v0.1 run without a parse row
    falls back to its highest parser_version.
    """
    pid = latest_parse_id(conn, run_id)
    if pid is not None:
        pv = conn.execute(
            "SELECT parser_version FROM parses WHERE id = ?", (pid,)
        ).fetchone()["parser_version"]
        return "c.parse_id = ?", (pid,), {"parse_id": pid, "parser_version": pv}
    pv = conn.execute(
        """SELECT MAX(c.parser_version) AS pv FROM citations c
           JOIN events e ON c.event_id = e.id WHERE e.run_id = ?""",
        (run_id,),
    ).fetchone()["pv"]
    return (
        "c.parse_id IS NULL AND c.parser_version = ?",
        (pv,),
        {"parse_id": None, "parser_version": pv},
    )


def summarize_run(db_path: Path, run_id: int | None = None) -> dict[str, Any]:
    """Return per-engine cell counts and citation counts for a run.

    If run_id is None, it picks the latest run. Failed cells are counted on
    their own and never as cells that cite nothing.
    """
    if not db_path.exists():
        return {"error": f"database not found: {db_path}"}
    init_db(db_path)  # adds the v0.2 tables to a v0.1 ledger; never rewrites rows
    with connect(db_path) as conn:
        if run_id is None:
            row = conn.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return {"error": "no runs yet"}
            run_id = int(row["id"])
        assert run_id is not None

        meta = conn.execute(
            "SELECT id, started_at, label FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if meta is None:
            return {"error": f"run_id {run_id} not found"}

        cond, params, parse_info = _citation_filter(conn, run_id)

        cells = conn.execute(
            """SELECT engine, fetch_status, COUNT(*) AS n FROM events
               WHERE run_id = ? GROUP BY engine, fetch_status
               ORDER BY engine, fetch_status""",
            (run_id,),
        ).fetchall()

        engines: dict[str, dict[str, int]] = {}
        for r in cells:
            d = engines.setdefault(
                r["engine"],
                {"ok": 0, "failed": 0, "cells_citing_self": 0, "self_citations": 0},
            )
            d["ok" if r["fetch_status"] == "ok" else "failed"] += r["n"]

        self_rows = conn.execute(
            f"""SELECT e.engine, COUNT(DISTINCT e.id) AS cells, COUNT(*) AS n
                FROM citations c JOIN events e ON c.event_id = e.id
                WHERE e.run_id = ? AND e.fetch_status = 'ok' AND c.is_self = 1
                  AND {cond}
                GROUP BY e.engine""",
            (run_id, *params),
        ).fetchall()
        for r in self_rows:
            d = engines[r["engine"]]
            d["cells_citing_self"] = r["cells"]
            d["self_citations"] = r["n"]

        domain_counts = conn.execute(
            f"""SELECT c.cited_domain, MAX(c.is_self) AS is_self, COUNT(*) AS n
                FROM citations c JOIN events e ON c.event_id = e.id
                WHERE e.run_id = ? AND {cond}
                GROUP BY c.cited_domain
                ORDER BY n DESC, c.cited_domain
                LIMIT 30""",
            (run_id, *params),
        ).fetchall()

    return {
        "run_id": run_id,
        "started_at": meta["started_at"],
        "label": meta["label"],
        **parse_info,
        "cells_by_status": [dict(r) for r in cells],
        "engines": engines,
        "top_domains": [dict(r) for r in domain_counts],
    }


def print_summary(summary: dict[str, Any]) -> None:
    print(f"\n=== Run {summary['run_id']} ({summary['label'] or 'no label'}) ===")
    print(f"started_at: {summary['started_at']}")
    print(
        f"parse: {summary['parse_id'] if summary['parse_id'] is not None else 'legacy'}"
        f" (parser_version {summary['parser_version']})\n"
    )

    print("Cells per engine:")
    for r in summary["cells_by_status"]:
        print(f"  {r['engine']:14s}  {r['fetch_status']:11s}  {r['n']:4d}")

    print("\nSelf-citations per engine (cells citing you / ok cells, citations):")
    for engine, d in summary["engines"].items():
        failed = f"  ({d['failed']} failed, not counted)" if d["failed"] else ""
        print(
            f"  {engine:14s}  {d['cells_citing_self']:4d} / {d['ok']:<4d}"
            f"  {d['self_citations']:4d}{failed}"
        )

    print(f"\nTop {len(summary['top_domains'])} cited domains:")
    for r in summary["top_domains"]:
        marker = " *" if r["is_self"] else ""
        print(f"  {r['cited_domain']:40s}  {r['n']:4d}{marker}")
