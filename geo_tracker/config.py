"""Env + config loading."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REQUIRED = ("OPENROUTER_API_KEY",)


def bedrock_setup_error() -> str | None:
    """Return why Bedrock calls cannot start, or None if they can.

    boto3 finds credentials and the region with its usual chain. This check
    asks the same chain, so a run does not write one error row per cell for a
    missing key.
    """
    try:
        import boto3
    except ImportError:
        return "Bedrock engines need boto3: pip install 'geo-tracker[bedrock]'"
    from geo_tracker.adapters.bedrock import session_region

    session = boto3.Session()
    if session.get_credentials() is None:
        return "no AWS credentials found (env, shared config files or instance role)"
    if not session_region(session):
        return "no AWS region set (AWS_REGION, AWS_DEFAULT_REGION or a profile region)"
    return None


def load_env(env_path: Path | None = None, provider: str = "openrouter") -> None:
    """Load .env from cwd or explicit path, then check the provider setup. Idempotent."""
    if env_path is None:
        env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    if provider == "bedrock":
        error = bedrock_setup_error()
        if error:
            print(f"ERROR: {error}", file=sys.stderr)
            sys.exit(2)
        return
    missing = [v for v in REQUIRED if not os.environ.get(v)]
    if missing:
        print(f"ERROR: required env vars missing: {missing}", file=sys.stderr)
        print(f"Looked in: {env_path}", file=sys.stderr)
        print("Get an OpenRouter key: https://openrouter.ai/keys", file=sys.stderr)
        sys.exit(2)
