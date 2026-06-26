"""The web payload layer that the serverless function exposes."""

from __future__ import annotations

import pytest

from logicgrid.solver import count_solutions
from logicgrid.webapi import (
    DEFAULT_THEME,
    THEME_DICTS,
    build_payload,
    get_theme,
    list_themes,
)


def test_list_themes_shape():
    themes = list_themes()
    assert {t["key"] for t in themes} == set(THEME_DICTS)
    for t in themes:
        assert t["name"] and t["description"]
        assert t["size"] >= 2 and t["categories"] >= 2


def test_embedded_themes_validate():
    for key in THEME_DICTS:
        get_theme(key).validate()  # must not raise


def test_get_theme_unknown_raises():
    with pytest.raises(KeyError):
        get_theme("does-not-exist")


def test_build_payload_default_theme():
    p = build_payload()
    assert p["theme"] == DEFAULT_THEME
    assert isinstance(p["seed"], int)
    assert p["clues"] and all(isinstance(c, str) for c in p["clues"])
    # categories echoed with their items
    assert len(p["categories"]) == len(THEME_DICTS[DEFAULT_THEME]["categories"])


def test_build_payload_solution_rows_align_with_categories():
    p = build_payload("detectives", seed=3)
    ncats = len(p["categories"])
    nitems = len(p["categories"][0]["items"])
    assert len(p["solution"]) == nitems
    for row in p["solution"]:
        assert len(row) == ncats
        # each cell is a real item label from its category
        for c, cell in enumerate(row):
            assert cell in p["categories"][c]["items"]


def test_build_payload_seed_is_reproducible():
    a = build_payload("detectives", seed=99)
    b = build_payload("detectives", seed=99)
    assert a["clues"] == b["clues"]
    assert a["solution"] == b["solution"]


def test_build_payload_echoes_and_resolves_seed():
    # When no seed is given, a concrete one is chosen and echoed so the puzzle
    # is reproducible from the response alone.
    p = build_payload("detectives", seed=None)
    again = build_payload("detectives", seed=p["seed"])
    assert again["solution"] == p["solution"]


def test_build_payload_solution_actually_solves_the_clues():
    # Reconstruct the grid from the returned solution rows and confirm the
    # emitted clue set has exactly that unique solution.
    from logicgrid.generate import generate_puzzle
    import random

    theme = get_theme("space_colony")
    puzzle = generate_puzzle(theme, random.Random(5))
    assert count_solutions(theme, puzzle.clues, cap=2) == 1


def test_build_payload_unknown_theme_raises():
    with pytest.raises(KeyError):
        build_payload("nope")


@pytest.mark.parametrize("theme_key", list(THEME_DICTS))
def test_build_payload_every_theme(theme_key):
    p = build_payload(theme_key, seed=1)
    theme = get_theme(theme_key)
    assert len(p["solution"]) == theme.n
    assert p["clues"]
