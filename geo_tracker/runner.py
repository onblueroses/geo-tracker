"""Run all (prompt, engine) cells for a configuration.

Concurrency: one task per cell, capped by `max_concurrent` (default 5).
Failures are NOT retried automatically — each cell produces exactly one event
row (ok / error / timeout) and the runner moves on. Re-run to retry.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml

from geo_tracker.adapters import ALL_ADAPTERS, OpenRouterClient
from geo_tracker.parser import parse_citations
from geo_tracker.storage import init_db, insert_citations, insert_event, start_run

log = logging.getLogger("geo_tracker.runner")


def _load_yaml_list(path: Path) -> list:
    if not path.exists():
        raise FileNotFoundError(f"missing config file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("items") or data.get("prompts") or data.get("domains") or []
    if not isinstance(data, list):
        raise ValueError(f"{path} must be a YAML list (or a mapping with `items:`)")
    return data


async def _run_cell(
    db_path: Path,
    run_id: int,
    adapter,
    prompt: str,
    self_domains: set[str],
    sem: asyncio.Semaphore,
) -> tuple[str, str, int]:
    """Run one cell. Returns (engine, fetch_status, n_citations)."""
    async with sem:
        event = await adapter.query(prompt)
        event_id = insert_event(
            db_path,
            run_id=run_id,
            prompt=prompt,
            engine=adapter.name,
            model=adapter.model,
            fetch_status=event.fetch_status,
            fetch_error=event.fetch_error,
            response_text=event.response_text,
            raw_response=event.raw_response,
            latency_ms=event.latency_ms,
        )
        n_cites = 0
        if event.fetch_status == "ok":
            citations = parse_citations(event.raw_response, self_domains)
            n_cites = insert_citations(db_path, event_id, citations)
        return adapter.name, event.fetch_status, n_cites


async def run(
    db_path: Path,
    prompts_path: Path,
    self_domains_path: Path,
    label: str | None = None,
    engines: list[str] | None = None,
    max_concurrent: int = 5,
) -> dict:
    init_db(db_path)
    prompts = _load_yaml_list(prompts_path)
    self_domains_list = _load_yaml_list(self_domains_path)
    self_domains = {str(d).lower().lstrip("www.") for d in self_domains_list}

    client = OpenRouterClient()
    adapters = []
    for cls in ALL_ADAPTERS:
        if engines and cls.name not in engines:
            continue
        adapters.append(cls(client))

    if not adapters:
        raise ValueError(f"no adapters selected (engines filter: {engines!r})")

    run_id = start_run(
        db_path,
        label=label,
        config={
            "n_prompts": len(prompts),
            "n_engines": len(adapters),
            "self_domains": sorted(self_domains),
            "max_concurrent": max_concurrent,
        },
    )

    sem = asyncio.Semaphore(max_concurrent)
    tasks = [
        _run_cell(db_path, run_id, adapter, prompt, self_domains, sem)
        for prompt in prompts
        for adapter in adapters
    ]
    print(
        f"[run {run_id}] {len(tasks)} cells ({len(prompts)} prompts × {len(adapters)} engines)"
    )
    results = await asyncio.gather(*tasks)

    by_engine: dict[str, dict[str, int]] = {}
    total_cites = 0
    for engine, status, n_cites in results:
        d = by_engine.setdefault(
            engine, {"ok": 0, "error": 0, "timeout": 0, "citations": 0}
        )
        d[status] += 1
        d["citations"] += n_cites
        total_cites += n_cites

    return {
        "run_id": run_id,
        "total_cells": len(tasks),
        "total_citations": total_cites,
        "by_engine": by_engine,
    }
