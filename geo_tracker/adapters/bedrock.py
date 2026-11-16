"""AWS Bedrock client: the Converse API through boto3.

A Bedrock engine answers from the model alone, without web search, unless
the engine names a system tool. Amazon Nova 2 Lite has the `nova_grounding`
system tool, which searches the web. Its citations come back as
`citationsContent` blocks in `output.message.content`.

boto3 is an optional dependency: `pip install 'geo-tracker[bedrock]'`.
boto3 finds the credentials and the region with its usual chain (environment,
shared config files, instance role). Timeouts and retries are the botocore
defaults: https://docs.aws.amazon.com/botocore/latest/reference/config.html
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Protocol

from geo_tracker.adapters.base import EventPayload, FetchStatus

# Converse stop reasons that end a complete answer. `max_tokens` is kept as
# `ok`, as the OpenRouter path keeps `finish_reason="length"`. All other
# reasons (tool_use, guardrail_intervened, content_filtered,
# malformed_model_output, ...) mean that no full answer came back.
OK_STOP_REASONS = frozenset({"end_turn", "stop_sequence", "max_tokens"})

TIMEOUT_ERRORS = frozenset({"ReadTimeoutError", "ConnectTimeoutError"})


class ConverseClient(Protocol):
    """The part of a boto3 `bedrock-runtime` client that geo-tracker uses."""

    def converse(self, **kwargs: Any) -> dict[str, Any]: ...


def classify_converse(raw: dict[str, Any]) -> tuple[FetchStatus, str | None, str]:
    """Decide if a Converse response is a usable answer.

    Returns (fetch_status, fetch_error, response_text). It fails closed: a
    response without answer text is an error, never an answer that cites
    nothing. The answer text is the text blocks in order. Reasoning, tool and
    citation blocks are not answer text.
    """
    stop = raw.get("stopReason")
    if stop not in OK_STOP_REASONS:
        return "error", f"stopReason is {stop!r}, not a complete answer", ""
    message = (raw.get("output") or {}).get("message") or {}
    blocks = message.get("content") or []
    text = "".join(
        b["text"] for b in blocks if isinstance(b, dict) and isinstance(b.get("text"), str)
    )
    if not text.strip():
        return "error", f"empty answer text (stopReason={stop!r})", ""
    return "ok", None, text


def _json_safe(response: dict[str, Any]) -> dict[str, Any]:
    """boto3 can return datetimes and bytes. The ledger stores JSON."""
    return json.loads(json.dumps(response, default=str))


def session_region(session: Any) -> str | None:
    """The boto3 region, else AWS_REGION.

    boto3 reads AWS_DEFAULT_REGION and the profile, but not AWS_REGION, which
    the AWS CLI v2 and other SDKs read. Measured with boto3 1.44.3.
    """
    return session.region_name or os.environ.get("AWS_REGION") or None


def make_boto3_client() -> ConverseClient:
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "Bedrock engines need boto3: pip install 'geo-tracker[bedrock]'"
        ) from exc
    session = boto3.Session()
    return session.client("bedrock-runtime", region_name=session_region(session))


class BedrockClient:
    """Shared client across the Bedrock engine adapters.

    boto3 is synchronous, so each call runs in a worker thread. A boto3
    client is safe to share between threads.
    """

    def __init__(self, client: ConverseClient | None = None) -> None:
        self._client = client if client is not None else make_boto3_client()

    async def converse(
        self, model: str, prompt: str, system_tools: tuple[str, ...] = ()
    ) -> EventPayload:
        kwargs: dict[str, Any] = {
            "modelId": model,
            "messages": [{"role": "user", "content": [{"text": prompt}]}],
        }
        if system_tools:
            kwargs["toolConfig"] = {
                "tools": [{"systemTool": {"name": name}} for name in system_tools]
            }
        started = time.monotonic()

        def elapsed() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            response = await asyncio.to_thread(self._client.converse, **kwargs)
        except Exception as exc:
            status: FetchStatus = "timeout" if type(exc).__name__ in TIMEOUT_ERRORS else "error"
            return EventPayload(
                response_text="",
                latency_ms=elapsed(),
                fetch_status=status,
                fetch_error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = elapsed()
        raw = _json_safe(response)
        status, error, text = classify_converse(raw)
        return EventPayload(
            response_text=text,
            raw_response=raw,
            latency_ms=latency_ms,
            fetch_status=status,
            fetch_error=error,
        )
