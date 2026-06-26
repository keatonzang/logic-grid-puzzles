"""Theme loading from dicts, JSON files, and the shipped YAML themes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from logicgrid.themes import load_theme, theme_from_dict

REPO_ROOT = Path(__file__).resolve().parent.parent
SHIPPED = [
    REPO_ROOT / "themes" / "morning_rush.yaml",
    REPO_ROOT / "themes" / "detectives.yaml",
    REPO_ROOT / "themes" / "space_colony.yaml",
]

PLAIN_DICT = {
    "name": "Dict theme",
    "description": "built from a dict",
    "entity_noun": "row",
    "categories": [
        {"name": "A", "items": ["a1", "a2"]},
        {"name": "B", "items": ["b1", "b2"]},
    ],
}


def test_theme_from_dict_basic():
    theme = theme_from_dict(PLAIN_DICT)
    assert theme.name == "Dict theme"
    assert theme.entity_noun == "row"
    assert theme.k == 2 and theme.n == 2
    assert theme.categories[0].ordered is False
    assert theme.categories[0].values is None


def test_theme_from_dict_ordered_values():
    data = {
        "name": "ord",
        "categories": [
            {"name": "A", "items": ["a1", "a2"]},
            {"name": "Y", "items": ["y1", "y2"], "ordered": True, "values": [10, 20]},
        ],
    }
    theme = theme_from_dict(data)
    assert theme.categories[1].ordered is True
    assert theme.categories[1].values == [10, 20]


def test_theme_from_dict_applies_defaults():
    theme = theme_from_dict(
        {"categories": [{"name": "A", "items": ["a", "b"]}, {"name": "B", "items": ["c", "d"]}]}
    )
    assert theme.name == "Untitled puzzle"
    assert theme.entity_noun == "entry"


def test_theme_from_dict_validates():
    bad = {"categories": [{"name": "A", "items": ["x"]}, {"name": "B", "items": ["y"]}]}
    with pytest.raises(ValueError):
        theme_from_dict(bad)


def test_load_theme_json_roundtrip(tmp_path: Path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(PLAIN_DICT), encoding="utf-8")
    theme = load_theme(p)
    assert theme.name == "Dict theme"


def test_load_theme_rejects_unknown_extension(tmp_path: Path):
    p = tmp_path / "t.txt"
    p.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported theme extension"):
        load_theme(p)


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_shipped_yaml_themes_load_and_validate(path: Path):
    theme = load_theme(path)
    theme.validate()  # should not raise
    assert theme.k >= 2
