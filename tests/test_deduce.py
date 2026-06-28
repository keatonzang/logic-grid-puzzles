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


def test_next_to_propagator_narrows(ordered_theme):
    # ordered cat 2 (Year), n=3. Pin term (1,0)'s rank to 0 by crossing 1 and 2.
    from logicgrid.clues import NextTo
    from logicgrid.deduce import _prop_next_to

    bd = Board(ordered_theme)
    bd.set(1, 0, 2, 1, N)
    bd.set(1, 0, 2, 2, N)  # (1,0) can only be rank 0 now
    # (0,1) must be immediately next to rank 0 -> only rank 1 survives
    _prop_next_to(bd, NextTo(2, (0, 1), (1, 0)))
    assert bd.get(0, 1, 2, 0) == N  # rank 0 ruled out (would be 0 apart)
    assert bd.get(0, 1, 2, 1) != N  # rank 1 kept (exactly 1 apart)
    assert bd.get(0, 1, 2, 2) == N  # rank 2 ruled out (2 apart)


def test_abs_apart_at_most_propagator_narrows(ordered_theme):
    from logicgrid.clues import AbsApart
    from logicgrid.deduce import _prop_abs_apart

    v = [2001, 2002, 2003]
    bd = Board(ordered_theme)
    bd.set(1, 0, 2, 1, N)
    bd.set(1, 0, 2, 2, N)  # (1,0) pinned to rank 0
    # "(0,1) is at most 1 away from (1,0)" -> rank 2 (gap 2) is impossible
    _prop_abs_apart(bd, AbsApart(2, (0, 1), (1, 0), 1, False, v))
    assert bd.get(0, 1, 2, 2) == N
    assert bd.get(0, 1, 2, 0) != N and bd.get(0, 1, 2, 1) != N


def test_exactly_anchor_propagator():
    from logicgrid.clues import Exactly
    from logicgrid.deduce import _prop_exactly_anchor

    theme = Theme(
        name="t", description="d", entity_noun="x",
        categories=[Category("C" + str(i), ["a", "b", "c", "d"]) for i in range(4)],
    )
    clue = Exactly((0, 0), [(1, 0), (2, 0), (3, 0)], 2)  # exactly two of three match

    bd = Board(theme)  # two options Y -> quota met, third forced N
    bd.set(0, 0, 1, 0, Y)
    bd.set(0, 0, 2, 0, Y)
    _prop_exactly_anchor(bd, clue)
    assert bd.get(0, 0, 3, 0) == N

    bd = Board(theme)  # one option N -> only two left, both needed -> both Y
    bd.set(0, 0, 1, 0, N)
    _prop_exactly_anchor(bd, clue)
    assert bd.get(0, 0, 2, 0) == Y
    assert bd.get(0, 0, 3, 0) == Y


def _plain3():
    return Theme(
        name="t", description="d", entity_noun="x",
        categories=[Category("C" + str(i), ["a", "b", "c"]) for i in range(3)],
    )


def test_implies_propagator():
    from logicgrid.clues import Implies
    from logicgrid.deduce import _prop_implies

    theme = _plain3()
    clue = Implies(((0, 0), (1, 0)), ((0, 0), (2, 0)))  # if (0,0)-(1,0) then (0,0)-(2,0)

    bd = Board(theme); bd.set(0, 0, 1, 0, Y)             # modus ponens
    _prop_implies(bd, clue); assert bd.get(0, 0, 2, 0) == Y

    bd = Board(theme); bd.set(0, 0, 2, 0, N)             # modus tollens (contrapositive)
    _prop_implies(bd, clue); assert bd.get(0, 0, 1, 0) == N

    bd = Board(theme); bd.set(0, 0, 1, 0, N)             # antecedent false -> no move
    _prop_implies(bd, clue); assert bd.get(0, 0, 2, 0) == U


def test_iff_propagator():
    from logicgrid.clues import Iff
    from logicgrid.deduce import _prop_iff

    theme = _plain3()
    clue = Iff(((0, 0), (1, 0)), ((0, 0), (2, 0)))

    bd = Board(theme); bd.set(0, 0, 1, 0, Y)             # left true -> right true
    _prop_iff(bd, clue); assert bd.get(0, 0, 2, 0) == Y

    bd = Board(theme); bd.set(0, 0, 1, 0, N)             # left false -> right false
    _prop_iff(bd, clue); assert bd.get(0, 0, 2, 0) == N

    bd = Board(theme); bd.set(0, 0, 2, 0, Y)             # right true -> left true (both ways)
    _prop_iff(bd, clue); assert bd.get(0, 0, 1, 0) == Y


def _grouped_theme():
    # Pet grouped: Furred = {Dog(0), Fox(2)}, Finned = {Eel(1)}
    return Theme(
        name="g", description="d", entity_noun="home",
        categories=[
            Category("Owner", ["Ann", "Bo", "Cy"]),
            Category("Pet", ["Dog", "Eel", "Fox"], group_noun="kind",
                     groups=(("Furred", ("Dog", "Fox")), ("Finned", ("Eel",)))),
        ],
    )


def test_in_group_propagator_crosses_off_complement():
    from logicgrid.clues import InGroup
    from logicgrid.deduce import _prop_in_group

    bd = Board(_grouped_theme())
    _prop_in_group(bd, InGroup((0, 0), 1, "Furred", (0, 2)))  # Ann is Furred -> not Eel(1)
    assert bd.get(0, 0, 1, 1) == N
    assert bd.get(0, 0, 1, 0) == U and bd.get(0, 0, 1, 2) == U


def test_same_group_propagator_narrows_to_shared_groups():
    from logicgrid.clues import SameGroup
    from logicgrid.deduce import _prop_same_group

    part = ((0, 2), (1,))
    bd = Board(_grouped_theme())
    # Pin Ann to Finned (only Eel possible): cross off Dog, Fox for Ann
    bd.set(0, 0, 1, 0, N)
    bd.set(0, 0, 1, 2, N)
    _prop_same_group(bd, SameGroup((0, 0), (0, 1), 1, "kind", part))
    # Bo must also be Finned -> Bo can't be Dog or Fox
    assert bd.get(0, 1, 1, 0) == N and bd.get(0, 1, 1, 2) == N
    assert bd.get(0, 1, 1, 1) != N


def test_diff_group_propagator_excludes_pinned_group():
    from logicgrid.clues import DiffGroup
    from logicgrid.deduce import _prop_diff_group

    part = ((0, 2), (1,))
    bd = Board(_grouped_theme())
    bd.set(0, 0, 1, 0, N)  # Ann pinned to Finned (Eel)
    bd.set(0, 0, 1, 2, N)
    _prop_diff_group(bd, DiffGroup((0, 0), (0, 1), 1, "kind", part))
    assert bd.get(0, 1, 1, 1) == N  # Bo can't be Finned (Eel)


def test_not_in_group_propagator_crosses_off_members():
    from logicgrid.clues import NotInGroup
    from logicgrid.deduce import _prop_not_in_group

    bd = Board(_grouped_theme())
    _prop_not_in_group(bd, NotInGroup((0, 0), 1, "Furred", (0, 2)))  # Ann not Furred
    assert bd.get(0, 0, 1, 0) == N and bd.get(0, 0, 1, 2) == N  # not Dog, not Fox
    assert bd.get(0, 0, 1, 1) == U  # Eel still open


def test_group_count_atleast_forces_undecided_in():
    from logicgrid.clues import GroupCount
    from logicgrid.deduce import _prop_group_count

    # "at least 2 of {Ann, Bo} are Furred" with both undecided -> both forced Furred
    bd = Board(_grouped_theme())
    _prop_group_count(bd, GroupCount([(0, 0), (0, 1)], 1, "Furred", (0, 2), 2, "atleast"))
    for e in (0, 1):  # each must be Furred -> not Eel(1)
        assert bd.get(0, e, 1, 1) == N


def test_group_count_atmost_forces_quota_out():
    from logicgrid.clues import GroupCount
    from logicgrid.deduce import _prop_group_count

    # "at most 1 Furred among {Ann, Bo}"; pin Ann Furred (Dog) -> Bo forced out (Finned)
    bd = Board(_grouped_theme())
    bd.set(0, 0, 1, 0, Y)  # Ann = Dog (Furred), definitely in
    _prop_group_count(bd, GroupCount([(0, 0), (0, 1)], 1, "Furred", (0, 2), 1, "atmost"))
    assert bd.get(0, 1, 1, 0) == N and bd.get(0, 1, 1, 2) == N  # Bo not Dog/Fox


def test_group_count_impossible_raises():
    from logicgrid.clues import GroupCount
    from logicgrid.deduce import _prop_group_count, Contradiction

    bd = Board(_grouped_theme())
    bd.set(0, 0, 1, 0, N)  # Ann can't be Dog
    bd.set(0, 0, 1, 2, N)  # ...or Fox -> Ann is definitely NOT Furred
    try:
        _prop_group_count(bd, GroupCount([(0, 0)], 1, "Furred", (0, 2), 1, "atleast"))
        assert False, "expected Contradiction"
    except Contradiction:
        pass


def _ordered_grouped_theme():
    # Pet grouped (Furred={Dog0,Fox2}, Finned={Eel1}); Score ordered (ranks 0..2)
    return Theme(
        name="g", description="d", entity_noun="home",
        categories=[
            Category("Owner", ["Ann", "Bo", "Cy"]),
            Category("Pet", ["Dog", "Eel", "Fox"], group_noun="kind",
                     groups=(("Furred", ("Dog", "Fox")), ("Finned", ("Eel",)))),
            Category("Score", ["Lo", "Mid", "Hi"], ordered=True, values=[1, 2, 3]),
        ],
    )


def test_group_order_propagator_bounds_ranks():
    from logicgrid.clues import GroupOrder
    from logicgrid.deduce import _prop_group_order

    bd = Board(_ordered_grouped_theme())
    # Furred {Dog0, Fox2} all outrank Finned {Eel1} on Score (cat 2).
    # floor = |lower| = 1 -> Furred trades can't be rank 0; ceil = n-1-|higher| = 0
    # -> Finned trade can't be rank 1 or 2.
    _prop_group_order(bd, GroupOrder(1, 2, (0, 2), (1,), "Furred", "Finned"))
    assert bd.get(1, 0, 2, 0) == N and bd.get(1, 2, 2, 0) == N  # Dog, Fox not lowest
    assert bd.get(1, 1, 2, 1) == N and bd.get(1, 1, 2, 2) == N  # Eel not Mid/Hi
    assert bd.get(1, 1, 2, 0) != N  # Eel still allowed at Lo


def test_group_clues_stay_sound_and_no_guessing():
    # King's Guild hard puzzles that keep a group clue must stay logic-solvable
    # and the solver must reach the true solution (catches an unsound propagator).
    from logicgrid.webapi import build_puzzle

    seen = 0
    for seed in range(40):
        th, puzzle, _rep, _ = build_puzzle(seed, "hard", items=4, categories=5, theme="kings_guild")
        names = {type(c).__name__ for c in puzzle.clues}
        if not (names & {"InGroup", "SameGroup", "DiffGroup", "NotInGroup", "GroupCount"}):
            continue
        seen += 1
        rep = solve(th, puzzle.clues)
        assert rep["solved"] and not rep["needs_guessing"], seed
        board = rep["board"]
        for e in range(th.n):
            for i in range(th.k):
                for j in range(i + 1, th.k):
                    assert board.get(i, puzzle.solution[e][i], j, puzzle.solution[e][j]) == Y
    assert seen, "no group clues kept across the sampled seeds"


def test_conditional_clues_stay_sound_and_no_guessing():
    # Hard puzzles that keep an Implies/Iff must remain logic-solvable with the
    # solver reaching the true solution (an unsound propagator would diverge).
    theme = Theme(
        name="t", description="d", entity_noun="order",
        categories=[
            Category("Customer", ["Ava", "Ben", "Cara", "Dane"]),
            Category("Drink", ["Chai", "Latte", "Mocha", "Tea"]),
            Category("Pastry", ["Bagel", "Donut", "Scone", "Tart"]),
            Category("Mug", ["Amber", "Cobalt", "Ivory", "Jade"]),
        ],
    )
    n, k = theme.n, theme.k
    seen = 0
    for seed in range(25):
        rng = random.Random(seed)
        _th, puzzle, _rep = generate_rated(lambda r: theme, rng, "hard")
        names = {type(c).__name__ for c in puzzle.clues}
        if not (names & {"Implies", "Iff"}):
            continue
        seen += 1
        rep = solve(theme, puzzle.clues)
        assert rep["solved"] and not rep["needs_guessing"], seed
        board = rep["board"]
        for e in range(n):  # solver's board agrees with the true solution
            for i in range(k):
                for j in range(i + 1, k):
                    assert board.get(i, puzzle.solution[e][i], j, puzzle.solution[e][j]) == Y
    assert seen, "no conditional clues kept across the sampled seeds"


@pytest.mark.parametrize("target", ["medium", "hard"])
def test_sequential_price_stays_sound_and_no_guessing(target):
    # The Price (ordered) category brings sequential clues; their propagators
    # must be sound and keep puzzles solvable by logic alone.
    from logicgrid.clues import Adjacent, Between, Diff, Greater

    theme, puzzle, report = generate_rated(
        lambda r: build_cafe_theme(r, 4, categories=4, use_price=True), random.Random(7), target
    )
    assert report["band"] == target
    assert report["solved"]                       # no guessing
    assert _agrees(report["board"], puzzle.solution)
    # the ordered category exists and is value-sorted
    price = theme.categories[-1]
    assert price.ordered and price.values == sorted(price.values)
