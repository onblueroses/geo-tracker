"""Bedrock provider with a fake Converse client. No network calls, except
the live test at the end, which runs only when GEO_TRACKER_LIVE_BEDROCK=1."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from geo_tracker.adapters import (
    ENGINES,
    BedrockClient,
    EventPayload,
    classify_converse,
    select_engines,
)
from geo_tracker.adapters.engines import EngineAdapter
from geo_tracker.cli import main
from geo_tracker.parser import parse_citations

BEDROCK = {e.name: e for e in ENGINES if e.provider == "bedrock"}


def converse_response(*blocks: dict[str, Any], stop: str = "end_turn") -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": list(blocks)}},
        "stopReason": stop,
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        "ResponseMetadata": {"HTTPStatusCode": 200, "RetryAttempts": 0},
    }


def web_citation(url: str) -> dict[str, Any]:
    return {"citationsContent": {"citations": [
        {"location": {"web": {"url": url, "domain": url.split("/")[2]}}}]}}


# Trimmed from a real Nova 2 Lite answer with nova_grounding (2026-11-16).
NOVA_GROUNDED = converse_response(
    {"toolUse": {"toolUseId": "t1", "name": "nova_grounding",
                 "input": {"query": "q"}, "type": "server_tool_use"}},
    {"toolResult": {"toolUseId": "t1", "content": [{"text": "[HIDDEN]"}],
                    "status": "success", "type": "nova_grounding_result"}},
    {"text": "Acme 3.1 is current"},
    web_citation("https://www.example.com/news"),
    web_citation("https://en.wikipedia.org/wiki/Acme"),
    {"text": ". It fixes a bug"},
    web_citation("https://www.example.com/news"),
    {"text": "."},
)


class FakeConverse:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def ask(engine_name: str, fake: FakeConverse) -> EventPayload:
    adapter = EngineAdapter(BEDROCK[engine_name], BedrockClient(fake))
    return asyncio.run(adapter.query("which database?"))


def test_memory_engines_send_no_tools():
    fake = FakeConverse(converse_response({"text": "Use Acme."}))
    for name in ("bedrock-anthropic", "bedrock-openai"):
        event = ask(name, fake)
        assert (event.fetch_status, event.response_text) == ("ok", "Use Acme.")
    assert [c["modelId"] for c in fake.calls] == [
        BEDROCK["bedrock-anthropic"].model, BEDROCK["bedrock-openai"].model]
    assert all("toolConfig" not in c for c in fake.calls)
    assert fake.calls[0]["messages"] == [
        {"role": "user", "content": [{"text": "which database?"}]}]


def test_reasoning_block_is_not_answer_text():
    """GPT-6 Luna on Bedrock returns a reasoning block before the text."""
    fake = FakeConverse(converse_response(
        {"reasoningContent": {"redactedContent": "b3BhcXVl"}}, {"text": "Hi there!"}))
    event = ask("bedrock-openai", fake)
    assert (event.fetch_status, event.response_text) == ("ok", "Hi there!")


def test_nova_sends_grounding_tool_and_yields_citations():
    fake = FakeConverse(NOVA_GROUNDED)
    event = ask("bedrock-nova", fake)
    assert fake.calls[0]["toolConfig"] == {"tools": [{"systemTool": {"name": "nova_grounding"}}]}
    assert event.fetch_status == "ok"
    assert event.response_text == "Acme 3.1 is current. It fixes a bug."
    cits = parse_citations(event.raw_response, {"example.com"})
    assert [(c.rank, c.cited_domain, c.is_self) for c in cits] == [
        (1, "example.com", True), (2, "en.wikipedia.org", False)]


def test_memory_answer_has_no_citations():
    cits = parse_citations(converse_response({"text": "Acme, per example.com"}), {"example.com"})
    assert cits == []


@pytest.mark.parametrize(
    "raw",
    [
        {},
        converse_response(),
        converse_response({"text": "  \n"}),
        converse_response({"reasoningContent": {"redactedContent": "eA=="}}),
        converse_response({"text": "Sorry, I cannot."}, stop="guardrail_intervened"),
        converse_response({"text": "partial"}, stop="content_filtered"),
        converse_response({"toolUse": {"toolUseId": "t", "name": "x", "input": {}}},
                          stop="tool_use"),
        converse_response({"text": "{"}, stop="malformed_model_output"),
    ],
)
def test_classify_converse_fails_closed(raw: dict[str, Any]):
    status, error, text = classify_converse(raw)
    assert status == "error"
    assert error
    assert text == ""


def test_api_error_becomes_error_row():
    exc = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no access"}},
                      "Converse")
    event = ask("bedrock-anthropic", FakeConverse(exc))
    assert event.fetch_status == "error"
    assert "AccessDeniedException" in (event.fetch_error or "")
    assert event.response_text == ""


def test_read_timeout_becomes_timeout_row():
    event = ask("bedrock-nova", FakeConverse(ReadTimeoutError(endpoint_url="https://x")))
    assert event.fetch_status == "timeout"
    assert event.fetch_error


def test_raw_response_is_json_safe():
    import datetime
    raw = converse_response({"text": "ok"})
    raw["ResponseMetadata"]["when"] = datetime.datetime(2026, 1, 1)
    event = ask("bedrock-anthropic", FakeConverse(raw))
    assert event.fetch_status == "ok"
    assert event.raw_response["ResponseMetadata"]["when"].startswith("2026-01-01")


# --- CLI -------------------------------------------------------------------

def _aws_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, creds: bool) -> None:
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                "AWS_PROFILE", "AWS_DEFAULT_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-credentials"))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-config"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-2")  # boto3 itself ignores AWS_REGION
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    if creds:
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATESTONLY")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")


def _files(tmp_path: Path) -> list[str]:
    (tmp_path / "prompts.yaml").write_text("- q1\n", encoding="utf-8")
    (tmp_path / "self_domains.yaml").write_text("- example.com\n", encoding="utf-8")
    return ["--db", str(tmp_path / "t.db"), "--prompts", str(tmp_path / "prompts.yaml"),
            "--self-domains", str(tmp_path / "self_domains.yaml"),
            "--env", str(tmp_path / ".env")]


def test_cli_bedrock_run_needs_no_openrouter_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                 capsys: pytest.CaptureFixture[str]):
    _aws_env(monkeypatch, tmp_path, creds=True)
    ok = EventPayload(response_text="Acme", raw_response=NOVA_GROUNDED, fetch_status="ok")

    async def query(self: Any, prompt: str) -> EventPayload:
        assert isinstance(self.client, BedrockClient)
        return ok

    monkeypatch.setattr("geo_tracker.adapters.engines.EngineAdapter.query", query)
    assert main(["run", "--provider", "bedrock", *_files(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert '"total_cells": 3' in out
    assert all(name in out for name in BEDROCK)


def test_cli_bedrock_without_credentials_exits_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]):
    _aws_env(monkeypatch, tmp_path, creds=False)
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "--provider", "bedrock", *_files(tmp_path)])
    assert exit_info.value.code == 2
    assert "no AWS credentials" in capsys.readouterr().err
    assert not (tmp_path / "t.db").exists()


def test_cli_bedrock_without_region_exits_two(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                             capsys: pytest.CaptureFixture[str]):
    _aws_env(monkeypatch, tmp_path, creds=True)
    monkeypatch.delenv("AWS_REGION")
    with pytest.raises(SystemExit) as exit_info:
        main(["run", "--provider", "bedrock", *_files(tmp_path)])
    assert exit_info.value.code == 2
    assert "no AWS region" in capsys.readouterr().err


def test_cli_rejects_engine_of_other_provider(capsys: pytest.CaptureFixture[str]):
    assert main(["run", "--provider", "bedrock", "--engines", "perplexity"]) == 2
    assert "perplexity" in capsys.readouterr().err


# --- Live --------------------------------------------------------------------

LIVE = os.environ.get("GEO_TRACKER_LIVE_BEDROCK") == "1"


@pytest.mark.skipif(not LIVE, reason="live Bedrock test: set GEO_TRACKER_LIVE_BEDROCK=1 "
                    "and AWS credentials to run it (it costs a few cents)")
@pytest.mark.parametrize("name", sorted(BEDROCK))
def test_live_bedrock(name: str):
    [engine] = select_engines([name], "bedrock")
    adapter = EngineAdapter(engine, BedrockClient())
    event = asyncio.run(adapter.query(
        "What is the latest stable release of SQLite? Name a source."))
    assert event.fetch_status == "ok", event.fetch_error
    assert event.response_text.strip()
    cits = parse_citations(event.raw_response, set())
    if engine.system_tools:
        assert cits, "a grounded engine returned no citations"
    else:
        assert cits == []
