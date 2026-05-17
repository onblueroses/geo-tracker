"""The four answer engines: Perplexity, OpenAI, Anthropic, Gemini.

All routed via OpenRouter. The `:online` suffix on the OpenAI/Anthropic/Gemini
model strings activates OpenRouter's web-search augmentation, returning
citations in `choices[0].message.annotations[].url_citation`.
"""

from __future__ import annotations

from geo_tracker.adapters.base import EngineAdapter, EventPayload


class PerplexityAdapter(EngineAdapter):
    """Perplexity sonar-pro — native web grounding."""

    name = "perplexity"
    model = "perplexity/sonar-pro"

    async def query(self, prompt: str) -> EventPayload:
        return await self.client.chat_completion(self.model, prompt)


class OpenAIAdapter(EngineAdapter):
    """OpenAI gpt-4o-mini with web search via OpenRouter."""

    name = "openai"
    model = "openai/gpt-4o-mini:online"

    async def query(self, prompt: str) -> EventPayload:
        return await self.client.chat_completion(self.model, prompt)


class AnthropicAdapter(EngineAdapter):
    """Anthropic Claude with web search via OpenRouter."""

    name = "anthropic"
    model = "anthropic/claude-3.5-haiku:online"

    async def query(self, prompt: str) -> EventPayload:
        return await self.client.chat_completion(self.model, prompt)


class GeminiAdapter(EngineAdapter):
    """Google Gemini with web search via OpenRouter."""

    name = "gemini"
    model = "google/gemini-2.5-flash:online"

    async def query(self, prompt: str) -> EventPayload:
        return await self.client.chat_completion(self.model, prompt)
