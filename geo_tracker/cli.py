"""CLI: geo-tracker {init,run,summary}."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from geo_tracker.config import load_env
from geo_tracker import runner, storage, summarize

DEFAULT_DB = Path("geo-tracker.db")
DEFAULT_PROMPTS = Path("prompts.yaml")
DEFAULT_SELF = Path("self_domains.yaml")

INIT_PROMPTS = """\
# One prompt per line. These are what you'd actually type into Perplexity/
# ChatGPT/Claude/Gemini search. Aim for queries your audience would ask.

- best open source vector database for production
- compare postgres and clickhouse for analytics
- how to self-host an LLM gateway
- which python async http library is fastest
- best practices for SQLite write performance
"""

INIT_SELF = """\
# Your domains. The tracker classifies citations as 'self' if the cited
# host (after stripping www.) appears in this list.

- example.com
- docs.example.com
"""

INIT_ENV = """\
# OpenRouter routes all four answer engines through one API key.
# Get a key: https://openrouter.ai/keys
OPENROUTER_API_KEY=
"""


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.dir or ".")
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in (
        ("prompts.yaml", INIT_PROMPTS),
        ("self_domains.yaml", INIT_SELF),
        (".env", INIT_ENV),
    ):
        path = target / name
        if path.exists() and not args.force:
            print(f"skip (exists): {path}")
            continue
        path.write_text(content, encoding="utf-8")
        written.append(str(path))
    storage.init_db(target / "geo-tracker.db")
    written.append(str(target / "geo-tracker.db"))
    print(f"Wrote: {', '.join(written)}")
    print("\nNext steps:")
    print("  1. Edit prompts.yaml with the queries your audience asks")
    print("  2. Edit self_domains.yaml with your domains")
    print("  3. Set OPENROUTER_API_KEY in .env (https://openrouter.ai/keys)")
    print("  4. geo-tracker run")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    load_env(Path(args.env) if args.env else None)
    summary = asyncio.run(
        runner.run(
            db_path=Path(args.db),
            prompts_path=Path(args.prompts),
            self_domains_path=Path(args.self_domains),
            label=args.label,
            engines=args.engines.split(",") if args.engines else None,
            max_concurrent=args.concurrent,
        )
    )
    print(json.dumps(summary, indent=2))
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    summary = summarize.summarize_run(Path(args.db), run_id=args.run_id)
    summarize.print_summary(summary)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="geo-tracker",
        description="Measure how often LLM answer engines cite your URLs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser(
        "init",
        help="Scaffold prompts.yaml, self_domains.yaml, .env, and an empty SQLite DB",
    )
    pi.add_argument("--dir", help="Target directory (default: current)")
    pi.add_argument("--force", action="store_true", help="Overwrite existing files")
    pi.set_defaults(func=cmd_init)

    pr = sub.add_parser(
        "run", help="Query all engines for all prompts; write to ledger"
    )
    pr.add_argument("--db", default=str(DEFAULT_DB))
    pr.add_argument("--prompts", default=str(DEFAULT_PROMPTS))
    pr.add_argument("--self-domains", default=str(DEFAULT_SELF))
    pr.add_argument("--label", help="Free-text label for this run (e.g., '2026-W21')")
    pr.add_argument("--engines", help="Comma-separated subset (default: all four)")
    pr.add_argument("--concurrent", type=int, default=5)
    pr.add_argument("--env", help="Path to .env file (default: ./.env)")
    pr.set_defaults(func=cmd_run)

    ps = sub.add_parser("summary", help="Print a per-engine citation rollup")
    ps.add_argument("--db", default=str(DEFAULT_DB))
    ps.add_argument("--run-id", type=int, help="Specific run (default: latest)")
    ps.set_defaults(func=cmd_summary)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
