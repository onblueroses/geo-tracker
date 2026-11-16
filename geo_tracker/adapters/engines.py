"""The answer engines: Perplexity, OpenAI, Anthropic, Gemini.

All go through OpenRouter. The `:online` suffix turns on OpenRouter's web
plugin, which uses each provider's native search for these four providers.
Citations come back in `choices[0].message.annotations[].url_citation`.

Model IDs were checked against https://openrouter.ai/api/v1/models on
2026-11-16.
"""

from __future__ import annotations

from dataclasses import dataclass

from geo_tracker.adapters.base import EventPayload, OpenRouterClient


@dataclass(frozen=True)
class Engine:
    name: str
    model: str
    grounding: str


ENGINES: tuple[Engine, ...] = (
    Engine("perplexity", "perplexity/sonar-pro", "native"),
    Engine("openai", "openai/gpt-6-luna:online", "OpenRouter web plugin"),
    Engine("anthropic", "anthropic/claude-haiku-5.5:online", "OpenRouter web plugin"),
    Engine("gemini", "google/gemini-4-hydrogen:online", "OpenRouter web plugin"),
)

ENGINE_NAMES: tuple[str, ...] = tuple(e.name for e in ENGINES)


class EngineAdapter:
    """Send one prompt to one engine through the shared client."""

    def __init__(self, engine: Engine, client: OpenRouterClient) -> None:
        self.name = engine.name
        self.model = engine.model
        self.client = client

    async def query(self, prompt: str) -> EventPayload:
        return await self.client.chat_completion(self.model, prompt)


def select_engines(names: list[str] | None) -> list[Engine]:
    """Return the engines to run. Reject unknown names instead of skipping them."""
    if not names:
        return list(ENGINES)
    unknown = sorted(set(names) - set(ENGINE_NAMES))
    if unknown:
        raise ValueError(
            f"unknown engine(s): {', '.join(unknown)} (known: {', '.join(ENGINE_NAMES)})"
        )
    return [e for e in ENGINES if e.name in names]
