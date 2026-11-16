"""The answer engines, per provider.

OpenRouter (the default): Perplexity, OpenAI, Anthropic, Gemini. The
`:online` suffix turns on OpenRouter's web plugin, which uses each provider's
native search for these four providers. Citations come back in
`choices[0].message.annotations[].url_citation`. Model IDs were checked
against https://openrouter.ai/api/v1/models on 2026-11-16.

AWS Bedrock: Claude Haiku 5.5 and GPT-6 Luna without search, so they measure
what the model knows from training, not what a search finds. Nova 2 Lite
with its `nova_grounding` web search tool gives citations. The IDs are US
cross-region inference profiles, checked with `aws bedrock
list-inference-profiles` in us-east-2 on 2026-11-16.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from geo_tracker.adapters.base import EventPayload, OpenRouterClient
from geo_tracker.adapters.bedrock import BedrockClient

Provider = Literal["openrouter", "bedrock"]
PROVIDERS: tuple[Provider, ...] = ("openrouter", "bedrock")
DEFAULT_PROVIDER: Provider = "openrouter"

MEMORY_ONLY = "none (model memory)"


@dataclass(frozen=True)
class Engine:
    name: str
    model: str
    grounding: str
    provider: Provider = "openrouter"
    system_tools: tuple[str, ...] = ()


ENGINES: tuple[Engine, ...] = (
    Engine("perplexity", "perplexity/sonar-pro", "native"),
    Engine("openai", "openai/gpt-6-luna:online", "OpenRouter web plugin"),
    Engine("anthropic", "anthropic/claude-haiku-5.5:online", "OpenRouter web plugin"),
    Engine("gemini", "google/gemini-4-hydrogen:online", "OpenRouter web plugin"),
    Engine("bedrock-anthropic", "us.anthropic.claude-haiku-5-5", MEMORY_ONLY, "bedrock"),
    Engine("bedrock-openai", "us.openai.gpt-6-luna", MEMORY_ONLY, "bedrock"),
    Engine("bedrock-nova", "us.amazon.nova-2-lite-v1:0", "Nova web grounding", "bedrock",
           ("nova_grounding",)),
)

ENGINE_NAMES: tuple[str, ...] = tuple(e.name for e in ENGINES)


def make_client(provider: Provider) -> OpenRouterClient | BedrockClient:
    if provider == "bedrock":
        return BedrockClient()
    return OpenRouterClient()


class EngineAdapter:
    """Send one prompt to one engine through the shared client of its provider."""

    def __init__(self, engine: Engine, client: OpenRouterClient | BedrockClient) -> None:
        self.name = engine.name
        self.model = engine.model
        self.engine = engine
        self.client = client

    async def query(self, prompt: str) -> EventPayload:
        if isinstance(self.client, BedrockClient):
            return await self.client.converse(self.model, prompt, self.engine.system_tools)
        return await self.client.chat_completion(self.model, prompt)


def select_engines(names: list[str] | None, provider: str = DEFAULT_PROVIDER) -> list[Engine]:
    """Return the engines of one provider to run.

    Reject an unknown provider and an engine name that the provider does not
    have, instead of skipping them.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider} (known: {', '.join(PROVIDERS)})")
    pool = [e for e in ENGINES if e.provider == provider]
    if not names:
        return pool
    known = [e.name for e in pool]
    unknown = sorted(set(names) - set(known))
    if unknown:
        raise ValueError(
            f"unknown engine(s) for provider {provider}: {', '.join(unknown)} "
            f"(known: {', '.join(known)})"
        )
    return [e for e in pool if e.name in names]


def build_adapters(engines: list[Engine]) -> list[EngineAdapter]:
    """One adapter per engine. One client per provider, made only when used."""
    clients: dict[str, OpenRouterClient | BedrockClient] = {}
    adapters: list[EngineAdapter] = []
    for e in engines:
        if e.provider not in clients:
            clients[e.provider] = make_client(e.provider)
        adapters.append(EngineAdapter(e, clients[e.provider]))
    return adapters
