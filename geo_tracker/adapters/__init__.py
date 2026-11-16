"""LLM answer-engine adapters, through OpenRouter (default) or AWS Bedrock."""

from geo_tracker.adapters.base import (
    Adapter,
    EventPayload,
    OpenRouterClient,
    classify_response,
)
from geo_tracker.adapters.bedrock import BedrockClient, classify_converse
from geo_tracker.adapters.engines import (
    DEFAULT_PROVIDER,
    ENGINE_NAMES,
    ENGINES,
    PROVIDERS,
    Engine,
    EngineAdapter,
    build_adapters,
    select_engines,
)

__all__ = [
    "Adapter",
    "BedrockClient",
    "DEFAULT_PROVIDER",
    "ENGINE_NAMES",
    "ENGINES",
    "Engine",
    "EngineAdapter",
    "EventPayload",
    "OpenRouterClient",
    "PROVIDERS",
    "build_adapters",
    "classify_converse",
    "classify_response",
    "select_engines",
]
