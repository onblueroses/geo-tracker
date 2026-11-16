"""Shared test fixtures. No test makes a network call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from geo_tracker.storage import init_db


def make_raw(*urls: str, text: str = "answer") -> dict[str, Any]:
    """An OpenRouter chat completion with one url_citation per URL."""
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": text,
                    "annotations": [
                        {"type": "url_citation", "url_citation": {"url": u, "title": u}}
                        for u in urls
                    ],
                },
            }
        ]
    }


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "t.db"
    init_db(path)
    return path


@pytest.fixture
def self_domains_file(tmp_path: Path) -> Path:
    path = tmp_path / "self_domains.yaml"
    path.write_text("- example.com\n", encoding="utf-8")
    return path
