"""Shared OpenRouter client and the adapter protocol.

All engines share one HTTPS client and differ only in the OpenRouter model
string. The `:online` suffix turns on OpenRouter's web plugin. Perplexity
Sonar is grounded natively.
"""

from __future__ import annotations

import os
import time
from typing import Any, Literal, Protocol

from openai import APITimeoutError, AsyncOpenAI, OpenAIError, Timeout
from pydantic import BaseModel, Field

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

FetchStatus = Literal["ok", "error", "timeout"]


class EventPayload(BaseModel):
    """Canonical adapter return shape. One per (prompt, engine) call.

    A `timeout` or `error` still produces a row, with empty text and the
    error message, so the ledger never has gaps.
    """

    response_text: str
    raw_response: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = 0
    fetch_status: FetchStatus
    fetch_error: str | None = None


class Adapter(Protocol):
    """What the runner needs from an engine adapter."""

    name: str
    model: str

    async def query(self, prompt: str) -> EventPayload: ...


def classify_response(raw: dict[str, Any]) -> tuple[FetchStatus, str | None, str]:
    """Decide if a completed HTTP call produced a usable answer.

    Returns (fetch_status, fetch_error, response_text). It fails closed: a
    response without answer text is an error, never an answer that cites
    nothing.
    """
    if raw.get("error"):
        return "error", f"error in response body: {raw['error']}", ""
    choices = raw.get("choices") or []
    if not choices:
        return "error", "empty choices array in OpenRouter response", ""
    choice = choices[0] or {}
    finish_reason = choice.get("finish_reason")
    if finish_reason == "error":
        return "error", "finish_reason is 'error'", ""
    message = choice.get("message") or {}
    text = message.get("content") or ""
    if not text.strip():
        return "error", f"empty answer text (finish_reason={finish_reason!r})", ""
    return "ok", None, text


class OpenRouterClient:
    """Shared async client across all engine adapters.

    The OpenAI SDK retries connection errors, 429 and 5xx responses with its
    default policy. A cell that still fails after that is recorded as failed.
    """

    def __init__(self, timeout: float = 60.0) -> None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY missing in env")
        self._client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            timeout=Timeout(timeout, connect=10.0),
        )

    async def chat_completion(self, model: str, prompt: str) -> EventPayload:
        started = time.monotonic()

        def elapsed() -> int:
            return int((time.monotonic() - started) * 1000)

        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
        except APITimeoutError as exc:
            return EventPayload(
                response_text="",
                latency_ms=elapsed(),
                fetch_status="timeout",
                fetch_error=str(exc),
            )
        except OpenAIError as exc:
            return EventPayload(
                response_text="",
                latency_ms=elapsed(),
                fetch_status="error",
                fetch_error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = elapsed()
        raw = response.model_dump()
        status, error, text = classify_response(raw)
        return EventPayload(
            response_text=text,
            raw_response=raw,
            latency_ms=latency_ms,
            fetch_status=status,
            fetch_error=error,
        )
