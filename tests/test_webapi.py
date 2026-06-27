"""The web payload layer: single café theme, difficulty, and grid size."""

from __future__ import annotations

import random

import pytest

from logicgrid.generate import DIFFICULTIES
from logicgrid.solver import count_solutions
from logicgrid.webapi import (
    ATTRIBUTE_POOLS,
    DEFAULT_DIFFICULTY,
    DEFAULT_ITEMS,
    MAX_CATEGORIES,
    MAX_ITEMS,
    MIN_CATEGORIES,
    MIN_ITEMS,
    SUBJECT,
    THEMES,
    build_cafe_theme,
    build_payload,
    build_theme,
    clamp_categories,
    clamp_items,
    list_themes,
)


def test_build_cafe_theme_shape_and_alphabetical():
    theme = build_cafe_theme(random.Random(1), DEFAULT_ITEMS, categories=3)
    assert theme.k == 3
    assert theme.categories[0].name == SUBJECT[0]  # Customer is always category 0
    assert all(c.name in ({SUBJECT[0]} | set(ATTRIBUTE_POOLS)) for c in theme.categories)
    for c in theme.categories:
        assert len(c.items) == DEFAULT_ITEMS
        assert c.items == sorted(c.items)  # rendered A->Z
    theme.validate()


@pytest.mark.parametrize("k", [3, 4, 5])
def test_build_cafe_theme_category_count(k):
    theme = build_cafe_theme(random.Random(2), 4, categories=k)
    assert theme.k == k


def test_build_cafe_theme_with_price():
    theme = build_cafe_theme(random.Random(1), 4, categories=4, use_price=True)
    assert theme.k == 4
    price = theme.categories[-1]
    assert price.name == "Price"
    assert price.ordered
    assert price.values == sorted(price.values)  # ascending = rank order
    assert price.items == [f"${v}" for v in price.values]


def test_clamp_bounds():
    assert clamp_items(1) == MIN_ITEMS
    assert clamp_items(99) == MAX_ITEMS
    assert clamp_categories(1) == MIN_CATEGORIES
    assert clamp_categories(99) == MAX_CATEGORIES


def test_build_payload_defaults():
    p = build_payload(seed=1)
    assert p["difficulty"] == DEFAULT_DIFFICULTY
    assert p["items"] == DEFAULT_ITEMS
    assert isinstance(p["seed"], int)
    assert len(p["categories"]) == 3
    assert p["clues"]
    for c in p["categories"]:
        if c["name"] != "Price":  # Price is value-sorted (= rank), not alphabetical
            assert c["items"] == sorted(c["items"])


def test_build_payload_solution_rows_align():
    p = build_payload(seed=3, items=5)
    assert all(len(c["items"]) == 5 for c in p["categories"])
    assert len(p["solution"]) == 5  # one row per entity
    for row in p["solution"]:
        assert len(row) == 3
        for c, cell in enumerate(row):
            assert cell in p["categories"][c]["items"]


def test_build_payload_reproducible():
    a = build_payload(seed=7, difficulty="hard", items=4)
    b = build_payload(seed=7, difficulty="hard", items=4)
    assert a == b


def test_build_payload_varies_members_across_seeds():
    a = build_payload(seed=1)
    b = build_payload(seed=222)
    # different seeds should (very likely) draw a different member set somewhere
    assert a["categories"] != b["categories"]


def test_build_payload_unknown_difficulty_raises():
    with pytest.raises(ValueError, match="unknown difficulty"):
        build_payload(seed=1, difficulty="impossible")


def test_build_payload_clamps_items():
    assert build_payload(seed=1, items=99)["items"] == MAX_ITEMS
    assert build_payload(seed=1, items=1)["items"] == MIN_ITEMS


@pytest.mark.parametrize("k", [3, 4, 5])
def test_build_payload_category_count(k):
    p = build_payload(seed=4, difficulty="medium", items=4, categories=k)
    assert p["n_categories"] == k
    assert len(p["categories"]) == k


def test_build_payload_easy_never_has_price():
    # Price is only rolled in for medium/hard (where its sequential clues exist).
    for s in range(8):
        assert build_payload(seed=s, difficulty="easy")["has_price"] is False


@pytest.mark.parametrize("difficulty", DIFFICULTIES)
@pytest.mark.parametrize("items", [MIN_ITEMS, DEFAULT_ITEMS, MAX_ITEMS])
def test_every_difficulty_and_size_is_unique(difficulty, items):
    # Rebuild the theme exactly as build_payload does, then confirm uniqueness.
    rng = random.Random(5)
    theme = build_cafe_theme(rng, items)
    from logicgrid.generate import generate_puzzle

    puzzle = generate_puzzle(theme, rng, difficulty=difficulty)
    assert count_solutions(theme, puzzle.clues, cap=2) == 1
    assert all(c.holds(puzzle.solution) for c in puzzle.clues)


# --- Theme registry ----------------------------------------------------------

def test_list_themes_catalogue():
    cat = list_themes()
    assert [t["key"] for t in cat] == list(THEMES)
    assert {"cafe", "kings_guild", "dnd", "mystery", "space", "engineer"}.issubset(set(THEMES))
    for t in cat:
        assert t["name"] and t["description"]


def test_theme_specs_pools_are_valid():
    # Each theme has globally-unique items and enough pools/members for any size.
    for spec in THEMES.values():
        items = list(spec.subject_items) + [it for _, its in spec.attributes for it in its]
        assert len(items) == len(set(items)), f"{spec.key} has duplicate items"
        assert len(spec.subject_items) >= MAX_ITEMS
        assert len(spec.attributes) >= 4  # subject + 4 attributes supports k=5
        for name, pool in spec.attributes:
            assert len(pool) >= MAX_ITEMS, (spec.key, name)


@pytest.mark.parametrize("key", list(THEMES))
def test_each_theme_builds_unique_puzzle(key):
    from logicgrid.generate import generate_puzzle

    rng = random.Random(5)
    theme = build_theme(THEMES[key], rng, items=4, categories=4)
    theme.validate()
    puzzle = generate_puzzle(theme, rng, difficulty="medium")
    assert count_solutions(theme, puzzle.clues, cap=2) == 1
    assert all(c.holds(puzzle.solution) for c in puzzle.clues)


def test_build_payload_theme_echoed_and_named():
    p = build_payload(seed=3, theme="dnd")
    assert p["theme"] == "dnd"
    assert p["name"] == THEMES["dnd"].name


def test_build_payload_unknown_theme_raises():
    with pytest.raises(ValueError, match="unknown theme"):
        build_payload(seed=1, theme="nope")


def test_numeric_suffix_unit_in_clue_text():
    # D&D gold uses a suffix unit (" gp"): items render "50 gp" and amounts too.
    rng = random.Random(3)
    theme = build_theme(THEMES["dnd"], rng, items=4, categories=4, n_numeric=1)
    gold = theme.categories[-1]
    assert gold.name == "Gold" and gold.unit_suffix == " gp"
    assert gold.items == [f"{v} gp" for v in gold.values]
    assert gold.amount(20) == "20 gp"


# --- Multiple ordered categories --------------------------------------------

def test_school_theme_offers_two_ordered_dials():
    specs = THEMES["school"].numerics
    assert [ns.name for ns in specs] == ["Grade", "Period"]  # primary first


def test_build_theme_with_two_numerics_is_unique():
    from logicgrid.generate import generate_puzzle

    rng = random.Random(5)
    theme = build_theme(THEMES["school"], rng, items=4, categories=5, n_numeric=2)
    ordered = [c for c in theme.categories if c.ordered]
    assert {c.name for c in ordered} == {"Grade", "Period"}
    theme.validate()
    puzzle = generate_puzzle(theme, rng, difficulty="hard")
    assert count_solutions(theme, puzzle.clues, cap=2) == 1
    assert all(c.holds(puzzle.solution) for c in puzzle.clues)


def test_build_theme_caps_numerics_to_available_slots():
    # k=3 leaves only 2 non-subject slots; asking for 2 numerics must not crash
    # or starve the attribute draw (n_attr stays >= 0).
    rng = random.Random(1)
    theme = build_theme(THEMES["school"], rng, items=3, categories=3, n_numeric=2)
    assert theme.k == 3
    assert sum(c.ordered for c in theme.categories) <= 2


def test_second_dial_is_hard_and_large_only():
    # The gated second ordered category never appears on medium, nor below K=4,
    # but does turn up on some hard, large puzzles. Test the roll directly (cheap)
    # rather than running full generation.
    from logicgrid.webapi import _roll_n_numeric

    school = THEMES["school"]

    def roll(seed, difficulty, k):
        return _roll_n_numeric(school, difficulty, k, random.Random(seed))

    assert all(roll(s, "easy", 5) == 0 for s in range(50))          # easy: no numerics
    assert all(roll(s, "medium", 5) <= 1 for s in range(50))        # medium: at most primary
    assert all(roll(s, "hard", 3) <= 1 for s in range(50))          # K=3: at most primary
    assert any(roll(s, "hard", 5) == 2 for s in range(50))          # hard+K=5: sometimes both
    # single-dial themes never reach two, even on hard/large
    assert all(_roll_n_numeric(THEMES["dnd"], "hard", 5, random.Random(s)) <= 1 for s in range(50))


def test_two_numerics_payload_reproducible():
    # Determinism must hold with the extra up-front roll (hint endpoint relies on it).
    a = build_payload(seed=7, difficulty="hard", items=4, categories=5, theme="school")
    b = build_payload(seed=7, difficulty="hard", items=4, categories=5, theme="school")
    assert a == b
