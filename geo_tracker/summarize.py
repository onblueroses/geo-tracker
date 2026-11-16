"""Read a run from the ledger and produce a citation and mention summary."""

from __future__ import annotations

import json
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

        # A parse with brands_json NULL (or a v0.1 run) did not measure mentions.
        pid = parse_info["parse_id"]
        brands_json = None
        if pid is not None:
            brands_json = conn.execute(
                "SELECT brands_json FROM parses WHERE id = ?", (pid,)
            ).fetchone()["brands_json"]
        brands = [b["name"] for b in json.loads(brands_json)] if brands_json else None

        engines: dict[str, dict[str, int | None]] = {}
        for r in cells:
            d = engines.setdefault(
                r["engine"],
                {"ok": 0, "failed": 0, "cells_citing_self": 0, "self_citations": 0,
                 "cells_mentioning": 0 if brands is not None else None},
            )
            key = "ok" if r["fetch_status"] == "ok" else "failed"
            d[key] = (d[key] or 0) + r["n"]

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

        if brands is not None:
            mention_rows = conn.execute(
                """SELECT e.engine, COUNT(DISTINCT e.id) AS cells
                   FROM mentions m JOIN events e ON m.event_id = e.id
                   WHERE e.run_id = ? AND e.fetch_status = 'ok' AND m.parse_id = ?
                   GROUP BY e.engine""",
                (run_id, pid),
            ).fetchall()
            for r in mention_rows:
                engines[r["engine"]]["cells_mentioning"] = r["cells"]

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
        "brands": brands,
        "cells_by_status": [dict(r) for r in cells],
        "engines": engines,
        "top_domains": [dict(r) for r in domain_counts],
    }


def print_summary(summary: dict[str, Any]) -> None:
    print(f"\n=== Run {summary['run_id']} ({summary['label'] or 'no label'}) ===")
    print(f"started_at: {summary['started_at']}")
    print(
        f"parse: {summary['parse_id'] if summary['parse_id'] is not None else 'legacy'}"
        f" (parser_version {summary['parser_version']})"
    )
    brands = summary["brands"]
    print(f"brands: {', '.join(brands) if brands is not None else 'not measured'}\n")

    print("Cells per engine:")
    for r in summary["cells_by_status"]:
        print(f"  {r['engine']:14s}  {r['fetch_status']:11s}  {r['n']:4d}")

    print("\nPer engine, ok cells only (cells citing you, citations, cells mentioning you):")
    print(f"  {'engine':14s}  {'cite you':>11s}  {'cites':>5s}  {'mention you':>11s}")
    for engine, d in summary["engines"].items():
        failed = f"  ({d['failed']} failed, not counted)" if d["failed"] else ""
        cm = d["cells_mentioning"]
        mention = f"{cm:4d} / {d['ok']:<4d}" if cm is not None else f"{'-':>4s}{'':7s}"
        line = (
            f"  {engine:14s}  {d['cells_citing_self']:4d} / {d['ok']:<4d}"
            f"  {d['self_citations']:5d}  {mention}{failed}"
        )
        print(line.rstrip())

    print(f"\nTop {len(summary['top_domains'])} cited domains:")
    for r in summary["top_domains"]:
        marker = " *" if r["is_self"] else ""
        print(f"  {r['cited_domain']:40s}  {r['n']:4d}{marker}")
