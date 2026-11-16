"""Engine table and fail-closed response handling. No network calls."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import pytest
from openai.types.chat import ChatCompletion

from geo_tracker.adapters import (
    ENGINES,
    OpenRouterClient,
    classify_response,
    select_engines,
)
from conftest import make_raw


def test_classify_ok_response():
    status, error, text = classify_response(make_raw("https://a.com", text="hi"))
    assert (status, error, text) == ("ok", None, "hi")


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"choices": []},
        {"error": {"code": 502, "message": "upstream"}, "choices": []},
        {"choices": [{"finish_reason": "error", "message": {"content": "partial"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": "  \n"}}]},
        {"choices": [{"finish_reason": "stop", "message": {"content": None}}]},
    ],
)
def test_classify_fails_closed(raw: dict[str, Any]):
    status, error, text = classify_response(raw)
    assert status == "error"
    assert error
    assert text == ""


def _client_returning(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> OpenRouterClient:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client = OpenRouterClient()
    response = ChatCompletion.model_validate(
        {"id": "1", "object": "chat.completion", "created": 0, "model": "m", **payload}
    )

    async def fake_create(**_: Any) -> ChatCompletion:
        return response

    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
    return client


def test_client_records_empty_answer_as_error(monkeypatch: pytest.MonkeyPatch):
    """Regression: an empty answer was stored as `ok` and read as "not cited"."""
    client = _client_returning(
        monkeypatch,
        {"choices": [{"index": 0, "finish_reason": "stop",
                      "message": {"role": "assistant", "content": ""}}]},
    )
    event = asyncio.run(client.chat_completion("m", "p"))
    assert event.fetch_status == "error"
    assert "empty answer" in (event.fetch_error or "")


def test_client_keeps_openrouter_citation_fields(monkeypatch: pytest.MonkeyPatch):
    """The SDK model must keep OpenRouter's extra `content` field on citations."""
    citation = {"url": "https://example.com/a", "title": "A", "content": "snippet",
                "start_index": 0, "end_index": 1}
    client = _client_returning(
        monkeypatch,
        {"choices": [{"index": 0, "finish_reason": "stop", "message": {
            "role": "assistant", "content": "answer",
            "annotations": [{"type": "url_citation", "url_citation": citation}]}}]},
    )
    event = asyncio.run(client.chat_completion("m", "p"))
    assert event.fetch_status == "ok"
    ann = event.raw_response["choices"][0]["message"]["annotations"][0]
    assert ann["url_citation"]["content"] == "snippet"
    json.dumps(event.raw_response)  # storable


def test_client_records_transport_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    client = OpenRouterClient(timeout=2)
    client._client = client._client.with_options(
        base_url="http://127.0.0.1:9/v1", max_retries=0
    )
    event = asyncio.run(client.chat_completion("m", "p"))
    assert event.fetch_status in ("error", "timeout")
    assert event.fetch_error


def test_select_engines_rejects_unknown_names():
    with pytest.raises(ValueError, match="openia"):
        select_engines(["openai", "openia"])
    assert [e.name for e in select_engines(["gemini", "openai"])] == ["openai", "gemini"]


def test_default_provider_is_openrouter():
    assert select_engines(None) == [e for e in ENGINES if e.provider == "openrouter"]
    assert [e.name for e in select_engines(None)] == ["perplexity", "openai", "anthropic", "gemini"]


def test_select_engines_keeps_providers_apart():
    with pytest.raises(ValueError, match="bedrock-nova"):
        select_engines(["bedrock-nova"])  # a Bedrock engine under the default provider
    with pytest.raises(ValueError, match="unknown provider"):
        select_engines(None, "azure")
    assert {e.provider for e in select_engines(None, "bedrock")} == {"bedrock"}


def test_engine_table_shape():
    names = [e.name for e in ENGINES]
    assert len(names) == len(set(names))
    for e in ENGINES:
        if e.provider == "bedrock":
            continue
        assert re.fullmatch(r"[a-z0-9-]+/[a-z0-9.\-]+(:online)?", e.model), e.model
        if e.grounding == "native":
            assert not e.model.endswith(":online")
        else:
            assert e.model.endswith(":online")
