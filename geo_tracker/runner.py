"""Run all (prompt, engine) cells for a configuration.

Concurrency: one task per cell, capped by `max_concurrent` (default 5).
geo-tracker does not retry a failed cell. Each cell produces exactly one
event row (ok, error, timeout or parse_error) and the runner moves on.
Re-run to retry.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from pathlib import Path
from typing import Any

import yaml

from geo_tracker.adapters import (
    DEFAULT_PROVIDER,
    Adapter,
    EventPayload,
    build_adapters,
    select_engines,
)
from geo_tracker.mentions import Brand, Mention, find_mentions, load_brands
from geo_tracker.parser import (
    PARSER_VERSION,
    Citation,
    normalize_self_domains,
    parse_citations,
)
from geo_tracker.storage import init_db, record_event, start_parse, start_run

log = logging.getLogger("geo_tracker.runner")

STATUSES = ("ok", "error", "timeout", "parse_error")
FAILED_STATUSES = frozenset(STATUSES) - {"ok"}


def load_yaml_list(path: Path) -> list[Any]:
    if not path.exists():
        raise FileNotFoundError(f"missing config file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("items") or data.get("prompts") or data.get("domains") or []
    if not isinstance(data, list):
        raise ValueError(f"{path} must be a YAML list (or a mapping with `items:`)")
    return data


def load_prompts(path: Path) -> list[str]:
    """Load prompts. Reject an empty list or an entry that is not text."""
    prompts: list[str] = []
    for i, item in enumerate(load_yaml_list(path)):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{path}: entry {i} is not a non-empty string: {item!r}")
        prompts.append(item.strip())
    if not prompts:
        raise ValueError(f"{path} has no prompts")
    return prompts


def load_self_domains(path: Path) -> set[str]:
    return normalize_self_domains(load_yaml_list(path))


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[:1000]}"


async def _run_cell(
    db_path: Path,
    run_id: int,
    parse_id: int,
    adapter: Adapter,
    prompt: str,
    self_domains: set[str],
    sem: asyncio.Semaphore,
    brands: list[Brand] | None = None,
) -> tuple[str, str, int]:
    """Run one cell. Returns (engine, fetch_status, n_citations).

    The cell fails closed. An adapter exception becomes an `error` row. A
    parser or matcher exception becomes a `parse_error` row that keeps the
    raw response.
    A storage failure rolls back and leaves an `error` row in its place.
    """
    async with sem:
        try:
            event = await adapter.query(prompt)
        except Exception as exc:
            event = EventPayload(
                response_text="", fetch_status="error", fetch_error=_describe(exc)
            )

        status: str = event.fetch_status
        error = event.fetch_error
        citations: list[Citation] = []
        mentions: list[Mention] = []
        if status == "ok":
            try:
                citations = parse_citations(event.raw_response, self_domains)
                if brands is not None:
                    mentions = find_mentions(event.response_text, brands)
            except Exception as exc:
                status, error = "parse_error", _describe(exc)
                citations, mentions = [], []

        try:
            record_event(
                db_path,
                run_id=run_id,
                parse_id=parse_id,
                prompt=prompt,
                engine=adapter.name,
                model=adapter.model,
                fetch_status=status,
                fetch_error=error,
                response_text=event.response_text,
                raw_response=event.raw_response,
                latency_ms=event.latency_ms,
                citations=citations,
                mentions=mentions,
            )
        except Exception as exc:
            try:
                record_event(
                    db_path,
                    run_id=run_id,
                    parse_id=parse_id,
                    prompt=prompt,
                    engine=adapter.name,
                    model=adapter.model,
                    fetch_status="error",
                    fetch_error=f"storage failed: {_describe(exc)}",
                    response_text="",
                    raw_response={},
                    latency_ms=event.latency_ms,
                )
            except Exception:
                log.exception("failed to record error event for %s", adapter.name)
            return adapter.name, "error", 0
        return adapter.name, status, len(citations)


async def run(
    db_path: Path,
    prompts_path: Path,
    self_domains_path: Path,
    label: str | None = None,
    engines: list[str] | None = None,
    max_concurrent: int = 5,
    brands_path: Path | None = None,
    provider: str = DEFAULT_PROVIDER,
) -> dict[str, Any]:
    """Run every cell. With `brands_path=None` the run does not measure mentions."""
    prompts = load_prompts(prompts_path)
    self_domains = load_self_domains(self_domains_path)
    brands = load_brands(brands_path) if brands_path is not None else None
    selected = select_engines(engines, provider)

    init_db(db_path)
    adapters: list[Adapter] = list(build_adapters(selected))

    run_id = start_run(
        db_path,
        label=label,
        config={
            "n_prompts": len(prompts),
            "provider": provider,
            "engines": {a.name: a.model for a in adapters},
            "self_domains": sorted(self_domains),
            "brands": [b.name for b in brands] if brands is not None else None,
            "max_concurrent": max_concurrent,
        },
    )
    parse_id = start_parse(
        db_path,
        run_id=run_id,
        parser_version=PARSER_VERSION,
        self_domains=self_domains,
        brands=brands,
    )

    sem = asyncio.Semaphore(max_concurrent)
    tasks = [
        _run_cell(db_path, run_id, parse_id, adapter, prompt, self_domains, sem, brands)
        for prompt in prompts
        for adapter in adapters
    ]
    print(
        f"[run {run_id}] {len(tasks)} cells ({len(prompts)} prompts × {len(adapters)} engines)"
    )
    results = await asyncio.gather(*tasks)

    by_engine: dict[str, dict[str, int]] = {}
    total_cites = 0
    failed = 0
    for engine, status, n_cites in results:
        d = by_engine.setdefault(engine, {s: 0 for s in STATUSES} | {"citations": 0})
        d[status] += 1
        d["citations"] += n_cites
        total_cites += n_cites
        failed += status in FAILED_STATUSES

    return {
        "run_id": run_id,
        "total_cells": len(tasks),
        "failed_cells": failed,
        "total_citations": total_cites,
        "by_engine": by_engine,
    }
