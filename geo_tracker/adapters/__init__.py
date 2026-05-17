"""LLM answer-engine adapters. All routed through OpenRouter."""

from geo_tracker.adapters.base import EngineAdapter, EventPayload, OpenRouterClient
from geo_tracker.adapters.engines import (
    AnthropicAdapter,
    GeminiAdapter,
    OpenAIAdapter,
    PerplexityAdapter,
)

__all__ = [
    "EngineAdapter",
    "EventPayload",
    "OpenRouterClient",
    "AnthropicAdapter",
    "GeminiAdapter",
    "OpenAIAdapter",
    "PerplexityAdapter",
    "ALL_ADAPTERS",
]

ALL_ADAPTERS = (
    PerplexityAdapter,
    OpenAIAdapter,
    AnthropicAdapter,
    GeminiAdapter,
)
