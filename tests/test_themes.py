"""Theme loading from dicts, JSON files, and the shipped YAML themes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from logicgrid.themes import (
    load_theme,
    theme_from_dict,
    theme_from_json,
    theme_to_dict,
    theme_to_json,
)

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


# --- single-file representation: a theme round-trips through JSON --------------

def _rich_theme():
    # exercises every serialisable field (ordered, values, unit, suffix, referent, plural)
    data = {
        "name": "Rich",
        "description": "every field",
        "entity_noun": "class",
        "categories": [
            {"name": "Teacher", "items": ["Ames", "Boyd"]},
            {"name": "Club", "items": ["Chess", "Debate"], "referent": "the person studying {}"},
            {"name": "Earnings", "items": ["80", "85"], "ordered": True,
             "values": [80, 85], "unit_suffix": " gp", "plural": True},
        ],
    }
    return theme_from_dict(data)


def test_theme_to_dict_omits_defaults_keeps_set_fields():
    d = theme_to_dict(_rich_theme())
    assert "ordered" not in d["categories"][0]      # plain category stays minimal
    assert "referent" not in d["categories"][0]
    assert d["categories"][1]["referent"] == "the person studying {}"
    assert "plural" not in d["categories"][0]       # default False stays omitted
    earn = d["categories"][2]
    assert earn["ordered"] is True and earn["values"] == [80, 85]
    assert earn["unit_suffix"] == " gp"
    assert earn["plural"] is True                    # explicit plural is preserved


def test_theme_json_round_trips_exactly():
    theme = _rich_theme()
    again = theme_from_json(theme_to_json(theme))
    # the canonical dict is stable across a full export/import cycle
    assert theme_to_dict(again) == theme_to_dict(theme)


def test_round_tripped_theme_generates_a_unique_puzzle():
    import random

    from logicgrid.generate import generate_puzzle
    from logicgrid.solver import count_solutions

    theme = theme_from_json(theme_to_json(_rich_theme()))
    puzzle = generate_puzzle(theme, random.Random(1), difficulty="normal")
    assert count_solutions(theme, puzzle.clues, cap=2) == 1


def test_theme_from_json_surfaces_validation_errors():
    bad = json.dumps({"categories": [
        {"name": "A", "items": ["x", "x"]},  # duplicate items
        {"name": "B", "items": ["y", "z"]},
    ]})
    with pytest.raises(ValueError):
        theme_from_json(bad)
