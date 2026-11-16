"""CLI: geo-tracker {init,run,summary,reparse}.

Exit codes: 0 success, 1 a run with failed cells or a runtime error,
2 bad input (flags, config files, missing key).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from geo_tracker import reparse as reparse_mod
from geo_tracker import runner, storage, summarize
from geo_tracker.adapters import ENGINE_NAMES, select_engines
from geo_tracker.config import load_env

DEFAULT_DB = Path("geo-tracker.db")
DEFAULT_PROMPTS = Path("prompts.yaml")
DEFAULT_SELF = Path("self_domains.yaml")
DEFAULT_BRANDS = Path("brands.yaml")

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

INIT_BRANDS = """\
# Your brand names. An answer mentions you if its text contains one of these
# names as a whole word, in any letter case. "Acme" does not match "Acmeville".

- name: Acme
  aliases:
    - Acme Cloud
    - acme.example
"""

INIT_ENV = """\
# OpenRouter routes all four answer engines through one API key.
# Get a key: https://openrouter.ai/keys
OPENROUTER_API_KEY=
"""


def _fail(message: str, code: int) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return code


def _brands_path(arg: str | None) -> Path | None:
    """Return the brands file to use, or None to skip mention counts.

    A path given with --brands must exist. Without the flag, a missing
    ./brands.yaml means "do not measure mentions", so older setups still run.
    """
    if arg is not None:
        return Path(arg)
    if DEFAULT_BRANDS.exists():
        return DEFAULT_BRANDS
    print(f"note: {DEFAULT_BRANDS} not found, so brand mentions are not measured",
          file=sys.stderr)
    return None


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.dir or ".")
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, content in (
        ("prompts.yaml", INIT_PROMPTS),
        ("self_domains.yaml", INIT_SELF),
        ("brands.yaml", INIT_BRANDS),
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
    print("  3. Edit brands.yaml with your brand names")
    print("  4. Set OPENROUTER_API_KEY in .env (https://openrouter.ai/keys)")
    print("  5. geo-tracker run")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    if args.concurrent < 1:
        return _fail(f"--concurrent must be >= 1 (got {args.concurrent})", 2)
    engines = [e.strip() for e in args.engines.split(",") if e.strip()] if args.engines else None
    try:
        select_engines(engines)
    except ValueError as exc:
        return _fail(str(exc), 2)
    load_env(Path(args.env) if args.env else None)
    try:
        summary = asyncio.run(
            runner.run(
                db_path=Path(args.db),
                prompts_path=Path(args.prompts),
                self_domains_path=Path(args.self_domains),
                label=args.label,
                engines=engines,
                max_concurrent=args.concurrent,
                brands_path=_brands_path(args.brands),
            )
        )
    except (FileNotFoundError, ValueError) as exc:
        return _fail(str(exc), 2)
    print(json.dumps(summary, indent=2))
    if summary["failed_cells"]:
        return _fail(
            f"{summary['failed_cells']} of {summary['total_cells']} cells failed. "
            "They are in the ledger with their error.",
            1,
        )
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    summary = summarize.summarize_run(Path(args.db), run_id=args.run_id)
    if "error" in summary:
        return _fail(summary["error"], 1)
    summarize.print_summary(summary)
    return 0


def cmd_reparse(args: argparse.Namespace) -> int:
    db = Path(args.db)
    if not db.exists():
        return _fail(f"database not found: {db}", 1)
    try:
        storage.init_db(db)
        result = reparse_mod.reparse(
            db, Path(args.self_domains), run_id=args.run_id,
            brands_path=_brands_path(args.brands),
        )
    except (FileNotFoundError, ValueError) as exc:
        return _fail(f"{exc} (nothing was written)", 2)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="geo-tracker",
        description="Measure how often LLM answer engines cite your URLs.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser(
        "init",
        help="Scaffold prompts.yaml, self_domains.yaml, brands.yaml, .env and an empty DB",
    )
    pi.add_argument("--dir", help="Target directory (default: current)")
    pi.add_argument("--force", action="store_true", help="Overwrite existing files")
    pi.set_defaults(func=cmd_init)

    pr = sub.add_parser("run", help="Query all engines for all prompts; write to ledger")
    pr.add_argument("--db", default=str(DEFAULT_DB))
    pr.add_argument("--prompts", default=str(DEFAULT_PROMPTS))
    pr.add_argument("--self-domains", default=str(DEFAULT_SELF))
    pr.add_argument("--brands", help=f"Brand names to find in answers (default: ./{DEFAULT_BRANDS})")
    pr.add_argument("--label", help="Free-text label for this run (e.g., '2026-W47')")
    pr.add_argument(
        "--engines",
        help=f"Comma-separated subset of: {','.join(ENGINE_NAMES)} (default: all)",
    )
    pr.add_argument("--concurrent", type=int, default=5)
    pr.add_argument("--env", help="Path to .env file (default: ./.env)")
    pr.set_defaults(func=cmd_run)

    ps = sub.add_parser("summary", help="Print a per-engine citation rollup")
    ps.add_argument("--db", default=str(DEFAULT_DB))
    ps.add_argument("--run-id", type=int, help="Specific run (default: latest)")
    ps.set_defaults(func=cmd_summary)

    prep = sub.add_parser(
        "reparse",
        help="Re-extract citations and mentions from stored responses with the current config",
    )
    prep.add_argument("--db", default=str(DEFAULT_DB))
    prep.add_argument("--self-domains", default=str(DEFAULT_SELF))
    prep.add_argument("--brands", help=f"Brand names to find in answers (default: ./{DEFAULT_BRANDS})")
    prep.add_argument("--run-id", type=int, help="Limit to one run (default: all runs)")
    prep.set_defaults(func=cmd_reparse)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
