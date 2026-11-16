"""Extract URL citations from a stored response and classify each domain.

Two response shapes carry citations:

- OpenRouter normalizes citations for all `:online` engines into
  `choices[0].message.annotations[].url_citation.{url,title,content}`.
  Perplexity Sonar uses the same shape.
- The Bedrock Converse API puts them in
  `output.message.content[].citationsContent.citations[].location.web.url`.

Bump PARSER_VERSION when the extraction logic changes. Old rows keep their
parser_version, so you can re-parse historical raw responses without losing
the original interpretation.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

PARSER_VERSION = 2  # 2: Bedrock Converse citations


@dataclass(frozen=True)
class Citation:
    parser_version: int
    cited_url: str
    cited_domain: str
    rank: int
    snippet: str | None
    is_self: bool


def extract_domain(url: str) -> str:
    """Lowercase host, leading 'www.' stripped, port and path discarded."""
    if not url or not isinstance(url, str):
        return ""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    return host.removeprefix("www.")


def normalize_self_domains(items: Iterable[object]) -> set[str]:
    """Normalize the entries of self_domains.yaml to bare hosts.

    Accepts bare hosts and full URLs. Strips 'www.' as a prefix, not as a
    character set: `lstrip("www.")` would turn "walmart.com" into "almart.com".
    """
    out: set[str] = set()
    for item in items:
        s = str(item).strip().lower()
        if s.startswith(("http://", "https://")):
            s = extract_domain(s)
        else:
            s = s.removeprefix("www.")
        if s:
            out.add(s)
    return out


def _openrouter_citations(raw: dict[str, Any]) -> Iterator[tuple[Any, Any]]:
    choices = raw.get("choices") or []
    if not choices:
        return
    msg = choices[0].get("message") or {}
    for ann in msg.get("annotations") or []:
        if not isinstance(ann, dict):
            continue
        if ann.get("type") not in (None, "url_citation"):
            continue
        cit = ann.get("url_citation") or {}
        yield cit.get("url"), cit.get("content") or cit.get("title")


def _bedrock_citations(raw: dict[str, Any]) -> Iterator[tuple[Any, Any]]:
    msg = (raw.get("output") or {}).get("message") or {}
    for block in msg.get("content") or []:
        if not isinstance(block, dict):
            continue
        for cit in (block.get("citationsContent") or {}).get("citations") or []:
            if not isinstance(cit, dict):
                continue
            web = (cit.get("location") or {}).get("web") or {}
            yield web.get("url"), cit.get("title")


def parse_citations(
    raw_response: dict[str, Any], self_domains: set[str]
) -> list[Citation]:
    """Walk the stored response and produce one Citation per cited URL."""
    out: list[Citation] = []
    rank = 0
    seen: set[str] = set()
    pairs = [*_openrouter_citations(raw_response), *_bedrock_citations(raw_response)]
    for url, snippet in pairs:
        if not url or url in seen:
            continue
        seen.add(url)
        domain = extract_domain(url)
        if not domain:
            continue
        rank += 1
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
