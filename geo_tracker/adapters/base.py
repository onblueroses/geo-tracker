"""Shared OpenRouter client + EngineAdapter base.

All four engines (Perplexity, OpenAI, Anthropic, Gemini) share one HTTPS
client and differ only in the OpenRouter model string. The `:online` suffix
turns on web search for the OpenAI/Anthropic/Gemini routes; Perplexity's
sonar-pro is grounded natively.
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from typing import Any, Literal

import httpx
from openai import APIError, APITimeoutError, AsyncOpenAI
from pydantic import BaseModel, Field

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class EventPayload(BaseModel):
    """Canonical adapter return shape. One per (prompt, engine) call.

    `fetch_status` is orthogonal to `response_text`: a `timeout` or `error`
    still produces a row (with empty text and a captured error message), so
    the ledger never has gaps.
    """

    response_text: str
    raw_response: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = 0
    fetch_status: Literal["ok", "error", "timeout"]
    fetch_error: str | None = None


class OpenRouterClient:
    """Shared async client across all engine adapters."""

    def __init__(self, timeout: float = 60.0) -> None:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY missing in env")
        self._client = AsyncOpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=api_key,
            timeout=httpx.Timeout(timeout, connect=10.0),
        )

    async def chat_completion(self, model: str, prompt: str) -> EventPayload:
        started = time.monotonic()
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
        except APITimeoutError as exc:
            return EventPayload(
                response_text="",
                latency_ms=int((time.monotonic() - started) * 1000),
                fetch_status="timeout",
                fetch_error=str(exc),
            )
        except (APIError, httpx.HTTPError) as exc:
            return EventPayload(
                response_text="",
                latency_ms=int((time.monotonic() - started) * 1000),
                fetch_status="error",
                fetch_error=f"{type(exc).__name__}: {exc}",
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        choice = response.choices[0]
        text = choice.message.content or ""
        raw = response.model_dump()
        return EventPayload(
            response_text=text,
            raw_response=raw,
            latency_ms=latency_ms,
            fetch_status="ok",
        )


class EngineAdapter(ABC):
    """One adapter per LLM answer engine."""

    name: str
    model: str

    def __init__(self, client: OpenRouterClient) -> None:
        self.client = client

    @abstractmethod
    async def query(self, prompt: str) -> EventPayload: ...
