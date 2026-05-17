"""Extract URL citations from an OpenRouter event and classify each domain.

OpenRouter normalizes citations across all four `:online` engines into a
single shape: `choices[0].message.annotations[].url_citation.{url,title,content}`.
Perplexity sonar uses the same shape.

Bump PARSER_VERSION when the extraction logic changes — old rows keep their
parser_version so you can re-parse historical raw responses without losing
the original interpretation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

PARSER_VERSION = 1


@dataclass(frozen=True)
class Citation:
    parser_version: int
    cited_url: str
    cited_domain: str
    rank: int
    snippet: str | None
    is_self: bool


def extract_domain(url: str) -> str:
    """Lowercase host, leading 'www.' stripped, port + path discarded."""
    if not url or not isinstance(url, str):
        return ""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def parse_citations(
    raw_response: dict[str, Any], self_domains: set[str]
) -> list[Citation]:
    """Walk the OpenRouter response and produce one Citation per cited URL."""
    out: list[Citation] = []
    choices = raw_response.get("choices") or []
    if not choices:
        return out
    msg = choices[0].get("message") or {}
    annotations = msg.get("annotations") or []
    rank = 0
    seen: set[str] = set()
    for ann in annotations:
        if not isinstance(ann, dict):
            continue
        if ann.get("type") not in (None, "url_citation"):
            continue
        cit = ann.get("url_citation") or {}
        url = cit.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        domain = extract_domain(url)
        if not domain:
            continue
        rank += 1
        snippet = cit.get("content") or cit.get("title")
        out.append(
            Citation(
                parser_version=PARSER_VERSION,
                cited_url=url,
                cited_domain=domain,
                rank=rank,
                snippet=snippet[:500] if isinstance(snippet, str) else None,
                is_self=domain in self_domains,
            )
        )
    return out
