"""Brand matching rules. No network calls."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from geo_tracker.mentions import Brand, find_mentions, load_brands, parse_brands

ACME = Brand(name="Acme", aliases=("Acme",))


def _counts(text: str, brands: list[Brand]) -> dict[str, int]:
    return {m.brand: m.count for m in find_mentions(text, brands)}


@pytest.mark.parametrize(
    "text",
    [
        "Acme is fast.",
        "Try acme today.",
        "ACME!",
        "(Acme)",
        "Acme's docs",
        "Acme-based stack",
        "see acme.",
        "Acme",
    ],
)
def test_matches_on_word_boundaries_in_any_case(text: str):
    assert _counts(text, [ACME]) == {"Acme": 1}


@pytest.mark.parametrize(
    "text",
    ["Acmeville is a town.", "MyAcme", "acme_corp", "acme2", "2acme", "Ac me", ""],
)
def test_does_not_match_inside_a_word(text: str):
    assert _counts(text, [ACME]) == {}


def test_counts_every_occurrence():
    assert _counts("Acme, acme and ACME.", [ACME]) == {"Acme": 3}


def test_aliases_count_for_their_brand():
    brand = Brand(name="Acme", aliases=("Acme", "Acme Cloud", "acme.io"))
    found = find_mentions("Use Acme Cloud or visit acme.io.", [brand])
    assert len(found) == 1
    assert found[0].brand == "Acme"
    # The longer alias wins, so "Acme Cloud" is one mention, not two.
    assert found[0].count == 2
    assert found[0].first_match == "Acme Cloud"


def test_alias_with_dot_is_literal():
    brand = Brand(name="Acme", aliases=("acme.io",))
    assert _counts("acmexio", [brand]) == {}
    assert _counts("acme.io", [brand]) == {"Acme": 1}


def test_multi_word_alias_needs_the_exact_spacing():
    brand = Brand(name="Acme", aliases=("Acme Cloud",))
    assert _counts("acme cloud", [brand]) == {"Acme": 1}
    assert _counts("Acme  Cloud", [brand]) == {}
    assert _counts("Acme Cloudy", [brand]) == {}


def test_several_brands_are_counted_apart():
    brands = [ACME, Brand(name="Globex", aliases=("Globex",))]
    assert _counts("Acme beats Globex. Globex costs less.", brands) == {"Acme": 1, "Globex": 2}


def test_unicode_case_and_letters():
    brand = Brand(name="Café Zürich", aliases=("Café Zürich",))
    assert _counts("Visit CAFÉ ZÜRICH now.", [brand]) == {"Café Zürich": 1}
    # A letter with an accent is a word character, so it is a boundary only outside the name.
    assert _counts("Café Züriché", [brand]) == {}
    assert _counts("éCafé Zürich", [brand]) == {}


def test_unicode_composed_and_decomposed_forms_match():
    brand = parse_brands(["Café"])[0]
    decomposed = unicodedata.normalize("NFD", "Le café est bon.")
    assert decomposed != "Le café est bon."
    assert _counts(decomposed, [brand]) == {"Café": 1}


def test_non_latin_script():
    brand = Brand(name="Акме", aliases=("Акме",))
    assert _counts("Мы используем акме.", [brand]) == {"Акме": 1}
    assert _counts("Акмеград", [brand]) == {}


def test_parse_brands_accepts_names_and_mappings():
    brands = parse_brands(["Acme", {"name": "Globex", "aliases": ["Globex Corp", "globex.example"]}])
    assert brands == [
        Brand(name="Acme", aliases=("Acme",)),
        Brand(name="Globex", aliases=("Globex", "Globex Corp", "globex.example")),
    ]


@pytest.mark.parametrize(
    ("items", "match"),
    [
        ([], "no brands"),
        ([""], "entry 0"),
        ([42], "entry 0"),
        ([{"aliases": ["x"]}], "entry 0"),
        ([{"name": "Acme", "aliases": "Acme Corp"}], "aliases"),
        ([{"name": "Acme", "aliases": ["  "]}], "aliases"),
        (["Acme", "acme"], "twice"),
    ],
)
def test_parse_brands_rejects_bad_entries(items: list[object], match: str):
    with pytest.raises(ValueError, match=match):
        parse_brands(items)


def test_load_brands(tmp_path: Path):
    p = tmp_path / "brands.yaml"
    p.write_text("- Acme\n- name: Globex\n  aliases: [Globex Corp]\n", encoding="utf-8")
    assert [b.name for b in load_brands(p)] == ["Acme", "Globex"]
    p.write_text("brands:\n  - Acme\n", encoding="utf-8")
    assert [b.name for b in load_brands(p)] == ["Acme"]
    with pytest.raises(FileNotFoundError):
        load_brands(tmp_path / "missing.yaml")
