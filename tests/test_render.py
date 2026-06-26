"""Console rendering of clues, grids, and the solution table."""

from __future__ import annotations

import random

from logicgrid.generate import generate_puzzle
from logicgrid.render import (
    render_clues,
    render_grids,
    render_puzzle,
    render_solution,
)


def _puzzle(theme):
    return generate_puzzle(theme, random.Random(7))


def test_render_clues_numbers_every_clue(plain_theme):
    puzzle = _puzzle(plain_theme)
    out = render_clues(puzzle)
    assert out.startswith("CLUES")
    for i in range(1, len(puzzle.clues) + 1):
        assert f"{i:>2}." in out


def test_render_solution_lists_all_items(plain_theme):
    puzzle = _puzzle(plain_theme)
    out = render_solution(puzzle)
    assert "SOLUTION" in out
    for cat in plain_theme.categories:
        for item in cat.items:
            assert item in out


def test_render_grids_blank_vs_solved(plain_theme):
    puzzle = _puzzle(plain_theme)
    blank = render_grids(puzzle, solved=False)
    solved = render_grids(puzzle, solved=True)
    assert "blank" in blank and "_" in blank
    assert "X" in solved  # at least one link mark
    # one pairwise block per unordered pair of categories: C(3,2) = 3
    assert blank.count(" x ") == 3


def test_render_puzzle_includes_sections(ordered_theme):
    puzzle = _puzzle(ordered_theme)
    full = render_puzzle(puzzle, show_solution=True, grid=True)
    assert ordered_theme.name in full
    assert "CLUES" in full
    assert "GRID" in full
    assert "SOLUTION" in full


def test_render_puzzle_can_omit_grid_and_solution(plain_theme):
    puzzle = _puzzle(plain_theme)
    out = render_puzzle(puzzle, show_solution=False, grid=False)
    assert "CLUES" in out
    assert "GRID" not in out
    assert "SOLUTION" not in out
