"""Read a run from the ledger and produce a citation summary."""

from __future__ import annotations

from pathlib import Path

from geo_tracker.storage import connect


def summarize_run(db_path: Path, run_id: int | None = None) -> dict:
    """Return citation counts per (engine, domain) for a run.

    If run_id is None, picks the latest run.
    """
    with connect(db_path) as conn:
        if run_id is None:
            row = conn.execute(
                "SELECT id, started_at, label FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return {"error": "no runs yet"}
            run_id = row["id"]

        meta = conn.execute(
            "SELECT id, started_at, label FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if meta is None:
            return {"error": f"run_id {run_id} not found"}

        # Per-engine cell counts (one cell = one (prompt, engine) call)
        engines = conn.execute(
            """SELECT engine, fetch_status, COUNT(*) AS n FROM events
               WHERE run_id = ? GROUP BY engine, fetch_status""",
            (run_id,),
        ).fetchall()

        # Pick the latest parser_version present for this run so a reparse
        # doesn't double-count alongside the original interpretation.
        latest_pv_row = conn.execute(
            """SELECT MAX(c.parser_version) AS pv FROM citations c
               JOIN events e ON c.event_id = e.id
               WHERE e.run_id = ?""",
            (run_id,),
        ).fetchone()
        latest_pv = latest_pv_row["pv"] if latest_pv_row else None

        # Citation counts per domain across all engines (latest parser_version only)
        domain_counts = conn.execute(
            """SELECT c.cited_domain, c.is_self, COUNT(*) AS n FROM citations c
               JOIN events e ON c.event_id = e.id
               WHERE e.run_id = ? AND c.parser_version = ?
               GROUP BY c.cited_domain
               ORDER BY n DESC""",
            (run_id, latest_pv),
        ).fetchall()

        # Self-citation count per engine (latest parser_version only)
        self_by_engine = conn.execute(
            """SELECT e.engine, COUNT(*) AS n FROM citations c
               JOIN events e ON c.event_id = e.id
               WHERE e.run_id = ? AND c.is_self = 1 AND c.parser_version = ?
               GROUP BY e.engine""",
            (run_id, latest_pv),
        ).fetchall()

    return {
        "run_id": run_id,
        "started_at": meta["started_at"],
        "label": meta["label"],
        "parser_version": latest_pv,
        "cells_by_engine": [dict(r) for r in engines],
        "top_domains": [dict(r) for r in domain_counts[:30]],
        "self_cites_by_engine": [dict(r) for r in self_by_engine],
    }


def print_summary(summary: dict) -> None:
    if "error" in summary:
        print(summary["error"])
        return
    print(f"\n=== Run {summary['run_id']} ({summary['label'] or 'no label'}) ===")
    print(f"started_at: {summary['started_at']}")
    print(f"parser_version: {summary.get('parser_version', 'n/a')}\n")

    print("Cells per engine:")
    for r in summary["cells_by_engine"]:
        print(f"  {r['engine']:14s}  {r['fetch_status']:8s}  {r['n']:4d}")

    print("\nSelf-citations per engine:")
    if not summary["self_cites_by_engine"]:
        print("  (none)")
    for r in summary["self_cites_by_engine"]:
        print(f"  {r['engine']:14s}  {r['n']:4d}")

    print(f"\nTop {len(summary['top_domains'])} cited domains:")
    for r in summary["top_domains"]:
        marker = " *" if r["is_self"] else ""
        print(f"  {r['cited_domain']:40s}  {r['n']:4d}{marker}")
