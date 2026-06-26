"""The human-style deductive solver and difficulty grader."""

from __future__ import annotations

import random

import pytest

from logicgrid.deduce import N, U, Y, Board, grade, is_logic_solvable, solve
from logicgrid.generate import generate_puzzle, generate_rated, random_solution
from logicgrid.model import Category, Theme
from logicgrid.webapi import build_cafe_theme


def _agrees(board, X) -> bool:
    """Every determined cell must match the true solution X (soundness)."""
    n, k = board.n, board.k
    ent = {(c, X[e][c]): e for e in range(n) for c in range(k)}
    for (i, j), m in board.cell.items():
        for a in range(n):
            for b in range(n):
                if m[a][b] == U:
                    continue
                want = Y if ent[(i, a)] == ent[(j, b)] else N
                if m[a][b] != want:
                    return False
    return True


def test_board_same_category_relation():
    theme = Theme("t", "", [Category("A", ["a", "b"]), Category("B", ["c", "d"])])
    bd = Board(theme)
    assert bd.get(0, 0, 0, 0) == Y  # an item is itself
    assert bd.get(0, 0, 0, 1) == N  # distinct items, same category -> different
    assert bd.get(0, 0, 1, 0) == U  # cross-category, unknown to start


def test_solver_is_always_sound(plain_theme):
    # Soundness is the invariant: every fact the solver derives must match the
    # true solution, whether or not it fully solves (some unique puzzles need
    # techniques beyond tier 4). Completeness is guaranteed only for the
    # generate-and-grade-filtered puzzles (see test_generate_rated_*).
    solved = 0
    for s in range(15):
        rng = random.Random(s)
        p = generate_puzzle(plain_theme, rng, difficulty="medium")
        r = solve(plain_theme, p.clues)
        assert _agrees(r["board"], p.solution), "deductions must match the solution"
        solved += r["solved"]
    assert solved >= 10  # the large majority solve by tiers 0-4


def test_is_logic_solvable_true_for_unique(plain_theme):
    p = generate_puzzle(plain_theme, random.Random(2))
    assert is_logic_solvable(plain_theme, p.clues)


def test_grade_reports_band_and_steps(plain_theme):
    p = generate_puzzle(plain_theme, random.Random(0), difficulty="medium")
    g = grade(plain_theme, p.clues)
    assert g["band"] in ("easy", "medium", "hard")
    assert g["solved"] and not g["needs_guessing"]
    assert g["ceiling"] == max(t for t, s in g["steps"].items() if s)


@pytest.mark.parametrize("target", ["easy", "medium", "hard"])
def test_generate_rated_matches_measured_band(target):
    theme, puzzle, report = generate_rated(
        lambda r: build_cafe_theme(r, 4), random.Random(5), target
    )
    assert report["band"] == target           # measured == requested
    assert report["solved"]                    # logic-solvable, no guessing
    assert _agrees(report["board"], puzzle.solution)


def test_difficulty_tier_ceilings():
    # easy = no clue tricks (<=2); medium = clue propagation (3);
    # hard = needs proof-by-contradiction (tier 4).
    e = generate_rated(lambda r: build_cafe_theme(r, 4), random.Random(1), "easy")[2]
    m = generate_rated(lambda r: build_cafe_theme(r, 4), random.Random(1), "medium")[2]
    h = generate_rated(lambda r: build_cafe_theme(r, 4), random.Random(1), "hard")[2]
    assert e["ceiling"] <= 2
    assert m["ceiling"] == 3
    assert h["ceiling"] == 4
    assert h["steps"][4] >= 1  # at least one hypothetical step


def test_solver_sound_across_cafe_sizes():
    for items in (3, 4):
        for d in ("easy", "medium", "hard"):
            theme, puzzle, report = generate_rated(
                lambda r, it=items: build_cafe_theme(r, it), random.Random(3), d
            )
            assert _agrees(report["board"], puzzle.solution)


@pytest.mark.parametrize("target", ["medium", "hard"])
def test_sequential_price_stays_sound_and_no_guessing(target):
    # The Price (ordered) category brings sequential clues; their propagators
    # must be sound and keep puzzles solvable by logic alone.
    from logicgrid.clues import Adjacent, Between, Diff, Greater

    theme, puzzle, report = generate_rated(
        lambda r: build_cafe_theme(r, 4, with_price=True), random.Random(7), target
    )
    assert report["band"] == target
    assert report["solved"]                       # no guessing
    assert _agrees(report["board"], puzzle.solution)
    # the ordered category exists and is value-sorted
    price = theme.categories[3]
    assert price.ordered and price.values == sorted(price.values)
