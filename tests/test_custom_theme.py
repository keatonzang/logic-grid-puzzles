"""Custom (user-authored) theme documents: determinism, round-trip, validation.

The contract: a theme is one self-contained JSON document (the builder's
export, `logicgrid.themes` format); the same (document, difficulty, seed)
always rebuilds the identical puzzle, and /api/hint regenerates it from the
same document the client generated with.
"""

from __future__ import annotations

import json

import pytest

from logicgrid.themes import theme_from_dict, theme_to_dict, theme_to_json, theme_from_json
from logicgrid.webapi import build_custom_puzzle, build_hint, build_payload


def farm_doc(**overrides) -> dict:
    doc = {
        "name": "Test Farm",
        "description": "Who grows what.",
        "entity_noun": "plot",
        "categories": [
            {"name": "Farmer", "items": ["Ada", "Bram", "Cleo", "Dov"]},
            {"name": "Crop", "items": ["Kale", "Maize", "Oats", "Rye"]},
            {
                "name": "Acreage",
                "items": ["2 acres", "4 acres", "6 acres", "8 acres"],
                "ordered": True,
                "values": [2, 4, 6, 8],
            },
        ],
    }
    doc.update(overrides)
    return doc


def grouped_doc() -> dict:
    doc = farm_doc()
    doc["categories"][1]["group_noun"] = "field"
    doc["categories"][1]["groups"] = [
        {"label": "North Field", "items": ["Kale", "Maize"]},
        {"label": "South Field", "items": ["Oats", "Rye"]},
    ]
    return doc


def test_same_doc_settings_seed_is_byte_identical():
    for difficulty in ("normal", "hard", "mega"):
        a = build_payload(seed=7, difficulty=difficulty, theme_doc=farm_doc())
        b = build_payload(seed=7, difficulty=difficulty, theme_doc=farm_doc())
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        assert a["theme"] == "custom"
        assert a["seed"] == 7


def test_doc_roundtrip_through_file_preserves_puzzle():
    # download -> re-upload must be the SAME theme: the exported JSON round-trips
    # and regenerates the identical puzzle for the same seed.
    doc = grouped_doc()
    theme = theme_from_dict(doc)
    reexported = theme_to_dict(theme)
    reimported = theme_from_json(theme_to_json(theme))
    assert theme_to_dict(reimported) == reexported
    a = build_payload(seed=11, difficulty="hard", theme_doc=doc)
    b = build_payload(seed=11, difficulty="hard", theme_doc=reexported)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_hint_regenerates_custom_puzzle():
    payload = build_payload(seed=5, difficulty="hard", theme_doc=farm_doc())
    hint = build_hint(5, "hard", 0, 0, {}, theme_doc=farm_doc())
    assert hint.get("text")
    # the hint indexes real categories of the regenerated puzzle
    i, j = (int(x) for x in hint["key"].split("-"))
    assert 0 <= i < len(payload["categories"])
    assert 0 <= j < len(payload["categories"])


def test_grouped_custom_theme_generates():
    payload = build_payload(seed=2, difficulty="mega", theme_doc=grouped_doc())
    assert payload["difficulty"] in ("normal", "hard", "mega", "giga", "tera")
    assert any(c.get("groups") for c in payload["categories"])


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda d: d.pop("categories"), "malformed"),
        (lambda d: d["categories"][0]["items"].append("Ada"), "duplicate"),
        (lambda d: d["categories"][0]["items"].pop(), "items"),
        (lambda d: d.update(categories=d["categories"][:1]), "categories"),
    ],
)
def test_bad_docs_raise_value_error(mutate, message):
    doc = farm_doc()
    mutate(doc)
    with pytest.raises(ValueError) as exc:
        build_custom_puzzle(3, "normal", doc)
    assert message.lower() in str(exc.value).lower()


def test_non_dict_doc_rejected():
    with pytest.raises(ValueError):
        build_custom_puzzle(3, "normal", "not a dict")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        build_custom_puzzle(3, "bogus-difficulty", farm_doc())


def test_api_puzzle_post_and_hint_roundtrip():
    # Through the actual serverless handlers' response builders.
    import importlib
    import os
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "api"))
    puzzle_api = importlib.import_module("puzzle")
    hint_api = importlib.import_module("hint")

    status, payload = puzzle_api._build_custom_response(
        {"theme_doc": farm_doc(), "difficulty": "hard", "seed": 9}
    )
    assert status == 200 and payload["theme"] == "custom" and payload["seed"] == 9

    status2, hint = hint_api._build_response(
        {"seed": 9, "difficulty": "hard", "theme_doc": farm_doc(), "known": {}}
    )
    assert status2 == 200 and hint.get("text")

    status3, err = puzzle_api._build_custom_response({"theme_doc": "nope"})
    assert status3 == 400 and "theme_doc" in err["error"]

    status4, err4 = hint_api._build_response(
        {"seed": 1, "theme_doc": ["not", "a", "dict"], "known": {}}
    )
    assert status4 == 400 and "theme_doc" in err4["error"]


def open_groups_doc() -> dict:
    doc = farm_doc()
    doc["categories"][1]["group_labels"] = ["North Field", "South Field"]
    doc["categories"][1]["group_noun"] = "field"
    return doc


def test_open_groups_are_deterministic_in_the_seed():
    # group_labels: membership is drawn per puzzle, but the SAME (doc, seed)
    # must roll the same membership — the hint endpoint depends on it.
    a = build_payload(seed=13, difficulty="hard", theme_doc=open_groups_doc())
    b = build_payload(seed=13, difficulty="hard", theme_doc=open_groups_doc())
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    crop = next(c for c in a["categories"] if c["name"] == "Crop")
    assert crop.get("groups"), "4 items should always form 2 groups of 2"
    assert {g["label"] for g in crop["groups"]} == {"North Field", "South Field"}
    # different seeds may deal different memberships (it's a per-puzzle roll)
    rosters = set()
    for s in range(8):
        p = build_payload(seed=s, difficulty="hard", theme_doc=open_groups_doc())
        crop = next(c for c in p["categories"] if c["name"] == "Crop")
        rosters.add(tuple(tuple(g["items"]) for g in crop.get("groups", [])))
    assert len(rosters) > 1, "membership should vary across seeds"


def test_open_groups_hint_roundtrip():
    hint = build_hint(13, "hard", 0, 0, {}, theme_doc=open_groups_doc())
    assert hint.get("text")


def test_open_groups_validation():
    bad = open_groups_doc()
    bad["categories"][1]["group_labels"] = ["Only One"]
    with pytest.raises(ValueError, match="at least 2"):
        build_custom_puzzle(3, "normal", bad)

    both = open_groups_doc()
    both["categories"][1]["groups"] = [{"label": "X", "items": ["Kale", "Maize"]}]
    with pytest.raises(ValueError, match="not both"):
        build_custom_puzzle(3, "normal", both)

    dupe = open_groups_doc()
    dupe["categories"][1]["group_labels"] = ["A", "A"]
    with pytest.raises(ValueError, match="unique"):
        build_custom_puzzle(3, "normal", dupe)

    # too few items to form 2x2 groups: no hierarchy, but still generates
    tiny = {
        "name": "T", "description": "", "entity_noun": "row",
        "categories": [
            {"name": "Pet", "items": ["Cat", "Dog", "Eel"]},
            {"name": "Toy", "items": ["Ball", "Rope", "Kite"], "group_labels": ["A", "B"]},
            {"name": "Bed", "items": ["Mat", "Nest", "Box"]},
        ],
    }
    pay = build_payload(seed=2, difficulty="normal", theme_doc=tiny)
    toy = next(c for c in pay["categories"] if c["name"] == "Toy")
    assert not toy.get("groups")


def recital_doc() -> dict:
    # UNEVENLY-spaced values + a grouped ORDERED category — both legal for
    # custom themes; registry themes never exercise either.
    return {
        "name": "Recital Day", "description": "", "entity_noun": "slot",
        "categories": [
            {"name": "Student", "items": ["Ana", "Ben", "Cleo", "Dmitri"]},
            {"name": "Piece", "items": ["Etude", "Nocturne", "Prelude", "Waltz"]},
            {"name": "Time", "items": ["9 am", "10 am", "1 pm", "2 pm"],
             "ordered": True, "values": [9, 10, 13, 14],
             "group_noun": "session",
             "groups": [{"label": "Morning", "items": ["9 am", "10 am"]},
                        {"label": "Afternoon", "items": ["1 pm", "2 pm"]}]},
        ],
    }


def test_uneven_values_and_grouped_ordered_category():
    # Regression: the at-least/at-most-apart samplers once derived deltas from
    # step * rank-gap (assuming even spacing) and emitted clues FALSE under X,
    # crashing generation ("clue pool failed to yield a unique solution").
    for seed in (3, 7, 11):
        p = build_payload(seed=seed, difficulty="hard", theme_doc=recital_doc())
        assert p["difficulty"] in ("normal", "hard", "mega", "giga", "tera")
        assert p["clues"]


def test_uneven_value_pool_is_all_true_and_keeps_apart_clues():
    from logicgrid.clues import AbsApart, AtLeastApart
    from logicgrid.generate import build_clue_pool, random_solution
    import random

    theme = theme_from_dict(recital_doc())
    seen_apart = 0
    for seed in range(6):
        rng = random.Random(seed)
        X = random_solution(theme, rng)
        pool = build_clue_pool(theme, X, rng, include_sequential=True, enable_groups=True)
        assert all(c.holds(X) for c in pool)
        seen_apart += sum(isinstance(c, (AbsApart, AtLeastApart)) for c in pool)
    assert seen_apart, "apart-style comparisons should survive with uneven values"
