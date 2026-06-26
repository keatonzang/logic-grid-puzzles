"""Backtracking solution counter and the uniqueness predicate."""

from __future__ import annotations

from logicgrid.clues import Negative, Positive
from logicgrid.solver import count_solutions, is_unique


def test_no_clues_counts_all_permutations(plain_theme):
    # 3x3 with a fixed anchor column => 3! * 3! = 36 full assignments,
    # but the counter caps early; verify the cap is honoured.
    assert count_solutions(plain_theme, [], cap=2) == 2
    # with a high cap we get the true total (3! permutations per free column)
    assert count_solutions(plain_theme, [], cap=1000) == 36


def test_full_positive_chain_is_unique(plain_theme):
    # Pin both free columns to the identity solution.
    clues = [
        Positive((0, i), (1, i)) for i in range(3)
    ] + [Positive((0, i), (2, i)) for i in range(3)]
    assert count_solutions(plain_theme, clues, cap=2) == 1
    assert is_unique(plain_theme, clues)


def test_contradiction_has_zero_solutions(plain_theme):
    # Ann is and is not with Dog -> unsatisfiable.
    clues = [Positive((0, 0), (1, 0)), Negative((0, 0), (1, 0))]
    assert count_solutions(plain_theme, clues, cap=5) == 0
    assert not is_unique(plain_theme, clues)


def test_underconstrained_is_not_unique(plain_theme):
    # A single positive link leaves many completions.
    clues = [Positive((0, 0), (1, 0))]
    assert count_solutions(plain_theme, clues, cap=2) == 2
    assert not is_unique(plain_theme, clues)


def test_cap_stops_early(plain_theme):
    # Counter must never exceed the cap.
    assert count_solutions(plain_theme, [], cap=1) == 1
