"""Env + config loading."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REQUIRED = ("OPENROUTER_API_KEY",)


def load_env(env_path: Path | None = None) -> None:
    """Load .env from cwd or explicit path. Idempotent."""
    if env_path is None:
        env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    missing = [v for v in REQUIRED if not os.environ.get(v)]
    if missing:
        print(f"ERROR: required env vars missing: {missing}", file=sys.stderr)
        print(f"Looked in: {env_path}", file=sys.stderr)
        print("Get an OpenRouter key: https://openrouter.ai/keys", file=sys.stderr)
        sys.exit(2)
