"""Find brand mentions in the answer text.

The rule: a brand is mentioned when one of its names appears in the answer
as a whole word, in any letter case. A "whole word" means the character
before and after the match is not a letter, a digit or an underscore, in
any script. Thus "Acme" matches "Acme's" and "(acme)", but not "Acmeville".

Text and names are normalized to Unicode NFC first, so a composed and a
decomposed "é" are the same. Overlapping names of one brand count once:
the longest name wins.

Bump MATCHER_VERSION when this rule changes.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

MATCHER_VERSION = 1


@dataclass(frozen=True)
class Brand:
    name: str
    aliases: tuple[str, ...]  # includes the name itself


@dataclass(frozen=True)
class Mention:
    brand: str
    count: int
    first_match: str  # the text as it appears in the answer


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def parse_brands(items: Iterable[object]) -> list[Brand]:
    """Validate brands.yaml entries.

    An entry is a name (`- Acme`) or a mapping with `name` and an optional
    `aliases` list. Fail closed on an entry that is not one of these.
    """
    brands: list[Brand] = []
    seen: set[str] = set()
    for i, item in enumerate(items):
        if isinstance(item, str):
            name, raw_aliases = item, []
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            name, raw_aliases = item["name"], item.get("aliases") or []
        else:
            raise ValueError(f"brands entry {i} must be a name or a mapping with `name`: {item!r}")
        name = _nfc(name.strip())
        if not name:
            raise ValueError(f"brands entry {i} has an empty name")
        if not isinstance(raw_aliases, list):
            raise ValueError(f"brands entry {i} ({name}): `aliases` must be a list")
        aliases = [name]
        for a in raw_aliases:
            if not isinstance(a, str) or not a.strip():
                raise ValueError(f"brands entry {i} ({name}): aliases must be non-empty strings")
            a = _nfc(a.strip())
            if a.casefold() not in {x.casefold() for x in aliases}:
                aliases.append(a)
        key = name.casefold()
        if key in seen:
            raise ValueError(f"brand {name!r} appears twice")
        seen.add(key)
        brands.append(Brand(name=name, aliases=tuple(aliases)))
    if not brands:
        raise ValueError("brands file has no brands")
    return brands


def load_brands(path: Path) -> list[Brand]:
    if not path.exists():
        raise FileNotFoundError(f"missing config file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("brands") or data.get("items") or []
    if not isinstance(data, list):
        raise ValueError(f"{path} must be a YAML list (or a mapping with `brands:`)")
    try:
        return parse_brands(data)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


@lru_cache(maxsize=256)
def _pattern(aliases: tuple[str, ...]) -> re.Pattern[str]:
    alts = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alts})(?!\w)", re.IGNORECASE)


def find_mentions(text: str, brands: Iterable[Brand]) -> list[Mention]:
    """Return one Mention per brand that the text names at least once."""
    text = _nfc(text or "")
    out: list[Mention] = []
    for b in brands:
        matches = _pattern(b.aliases).findall(text)
        if matches:
            out.append(Mention(brand=b.name, count=len(matches), first_match=matches[0]))
    return out


def brands_config(brands: Iterable[Brand]) -> list[dict[str, object]]:
    """The JSON form stored on each parse row."""
    return [{"name": b.name, "aliases": list(b.aliases)} for b in brands]
