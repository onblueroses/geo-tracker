"""The docs name the same models as the code."""

from pathlib import Path

from geo_tracker.adapters import ENGINES

ROOT = Path(__file__).parent.parent


def test_readme_lists_the_engine_models():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for e in ENGINES:
        assert f"`{e.model}`" in readme, e.model


def test_readme_says_memory_engines_do_not_search():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "not what a search finds" in readme


def test_example_brands_file_loads():
    from geo_tracker.mentions import load_brands
    names = [b.name for b in load_brands(ROOT / "examples" / "brands.yaml")]
    assert names == ["Acme", "Acme Labs"]
