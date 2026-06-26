"""The web payload layer: single café theme, difficulty, and grid size."""

from __future__ import annotations

import random

import pytest

from logicgrid.generate import DIFFICULTIES
from logicgrid.solver import count_solutions
from logicgrid.webapi import (
    CAFE_POOLS,
    DEFAULT_DIFFICULTY,
    DEFAULT_ITEMS,
    MAX_ITEMS,
    MIN_ITEMS,
    build_cafe_theme,
    build_payload,
    clamp_items,
)


def test_build_cafe_theme_shape_and_alphabetical():
    theme = build_cafe_theme(random.Random(1), DEFAULT_ITEMS)
    assert theme.k == 3  # Customer / Drink / Pastry
    assert [c.name for c in theme.categories] == list(CAFE_POOLS)
    for c in theme.categories:
        assert len(c.items) == DEFAULT_ITEMS
        assert c.items == sorted(c.items)  # rendered A->Z
    theme.validate()


def test_clamp_items_bounds():
    assert clamp_items(1) == MIN_ITEMS
    assert clamp_items(99) == MAX_ITEMS
    assert clamp_items(4) == 4


def test_build_payload_defaults():
    p = build_payload(seed=1)
    assert p["difficulty"] == DEFAULT_DIFFICULTY
    assert p["items"] == DEFAULT_ITEMS
    assert isinstance(p["seed"], int)
    assert len(p["categories"]) == 3
    assert p["clues"]
    for c in p["categories"]:
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
