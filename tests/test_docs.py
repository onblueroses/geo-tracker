"""The docs name the same models as the code."""

from pathlib import Path

from geo_tracker.adapters import ENGINES

ROOT = Path(__file__).parent.parent


def test_readme_lists_the_engine_models():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for e in ENGINES:
        assert f"`{e.model}`" in readme, e.model
