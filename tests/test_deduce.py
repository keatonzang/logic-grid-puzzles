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


def test_cross_elimination_marks_disjoint_candidates_apart():
    # Two items whose options in a bridge category are disjoint can't be the same
    # entity. A=(cat0,item0) can only be cat1 {0,1}; B=(cat2,item0) excludes {0,1}.
    from logicgrid.deduce import _sweep_cross_elim

    th = Theme("t", "", [Category(f"C{c}", [f"{c}{i}" for i in range(4)]) for c in range(3)])
    b = Board(th)
    for t in (2, 3):
        b.set(0, 0, 1, t, N)   # A's cat-1 options = {0, 1}
    for t in (0, 1):
        b.set(2, 0, 1, t, N)   # B's cat-1 options = {2, 3}  (disjoint from A's)
    assert b.get(0, 0, 2, 0) == U
    assert _sweep_cross_elim(b)
    assert b.get(0, 0, 2, 0) == N


def test_naked_subset_excludes_outsiders():
    # Two items confined to the same two options use them up between them.
    from logicgrid.deduce import _sweep_naked

    th = Theme("t", "", [Category(f"C{c}", [f"{c}{i}" for i in range(4)]) for c in range(3)])
    b = Board(th)
    for row in (0, 1):         # rows 0,1 both confined to columns {0,1}
        b.set(0, row, 1, 2, N)
        b.set(0, row, 1, 3, N)
    assert b.get(0, 2, 1, 0) == U
    assert _sweep_naked(b)
    assert b.get(0, 2, 1, 0) == N and b.get(0, 2, 1, 1) == N  # row 2 barred from {0,1}


def test_set_logic_sweeps_are_sound():
    # Cross-elimination and naked subsets must never derive a fact that disagrees
    # with the true solution, across a range of generated puzzles.
    from logicgrid.deduce import (
        _apply_givens, _sweep_lines, _sweep_transitivity, _sweep_clues, _sweep_set_logic,
    )

    for d in ("normal", "hard", "mega"):
        for s in range(12):
            th = build_cafe_theme(random.Random(s), 4)
            p = generate_puzzle(th, random.Random(s), difficulty=d)
            b = Board(th)
            _apply_givens(b, p.clues)
            for _ in range(2000):
                if _sweep_lines(b) or _sweep_transitivity(b) or _sweep_set_logic(b) \
                        or _sweep_clues(b, p.clues):
                    continue
                break
            assert _agrees(b, p.solution), f"set-logic unsound on {d} seed {s}"


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
        p = generate_puzzle(plain_theme, rng, difficulty="hard")
        r = solve(plain_theme, p.clues)
        assert _agrees(r["board"], p.solution), "deductions must match the solution"
        solved += r["solved"]
    assert solved >= 10  # the large majority solve by tiers 0-4


def test_is_logic_solvable_true_for_unique(plain_theme):
    p = generate_puzzle(plain_theme, random.Random(2))
    assert is_logic_solvable(plain_theme, p.clues)


def test_grade_reports_band_and_steps(plain_theme):
    p = generate_puzzle(plain_theme, random.Random(0), difficulty="hard")
    g = grade(plain_theme, p.clues)
    assert g["band"] in ("normal", "hard", "mega", "giga", "tera")
    assert g["solved"] and not g["needs_guessing"]
    assert g["ceiling"] == max(t for t, s in g["steps"].items() if s)


@pytest.mark.parametrize("target", ["normal", "hard", "mega"])
def test_generate_rated_matches_measured_band(target):
    # the reliably-hittable tiers on a small grid; giga/tera need room to grow
    theme, puzzle, report = generate_rated(
        lambda r: build_cafe_theme(r, 4), random.Random(5), target
    )
    assert report["band"] == target           # measured == requested
    assert report["solved"]                    # logic-solvable, no guessing
    assert _agrees(report["board"], puzzle.solution)


def test_difficulty_tiers_increase_by_index():
    # Bands are quintiles of the composite difficulty index, so they are NOT
    # ceiling-locked (a clue-heavy ceiling-3 can outrank a sparse ceiling-4). The
    # robust contract: the index rises up the ladder, the easiest tier stays
    # genuinely shallow, and the harder ones demand real propagation.
    from logicgrid.deduce import difficulty_index

    e = generate_rated(lambda r: build_cafe_theme(r, 4), random.Random(1), "normal")[2]
    m = generate_rated(lambda r: build_cafe_theme(r, 4), random.Random(1), "hard")[2]
    h = generate_rated(lambda r: build_cafe_theme(r, 4), random.Random(1), "mega")[2]
    assert e["ceiling"] <= 2  # basic pool -> line elimination / transitivity only
    assert e["band"] == "normal"
    assert difficulty_index(e) <= difficulty_index(m) <= difficulty_index(h)
    assert h["ceiling"] >= 3  # mega demands clue-logic or proof-by-contradiction


def test_solver_sound_across_cafe_sizes():
    for items in (3, 4):
        for d in ("normal", "hard", "mega"):
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


def test_conditional_implication_propagator():
    from logicgrid.clues import Conditional, Link
    from logicgrid.deduce import _prop_conditional

    theme = _plain3()
    clue = Conditional(Link((0, 0), (1, 0)), Link((0, 0), (2, 0)))  # if (0,0)-(1,0) then (0,0)-(2,0)

    bd = Board(theme); bd.set(0, 0, 1, 0, Y)             # modus ponens
    _prop_conditional(bd, clue); assert bd.get(0, 0, 2, 0) == Y

    bd = Board(theme); bd.set(0, 0, 2, 0, N)             # modus tollens (contrapositive)
    _prop_conditional(bd, clue); assert bd.get(0, 0, 1, 0) == N

    bd = Board(theme); bd.set(0, 0, 1, 0, N)             # antecedent false -> no move
    _prop_conditional(bd, clue); assert bd.get(0, 0, 2, 0) == U


def test_conditional_biconditional_propagator():
    from logicgrid.clues import Conditional, Link
    from logicgrid.deduce import _prop_conditional

    theme = _plain3()
    clue = Conditional(Link((0, 0), (1, 0)), Link((0, 0), (2, 0)), biconditional=True)

    bd = Board(theme); bd.set(0, 0, 1, 0, Y)             # left true -> right true
    _prop_conditional(bd, clue); assert bd.get(0, 0, 2, 0) == Y

    bd = Board(theme); bd.set(0, 0, 1, 0, N)             # left false -> right false
    _prop_conditional(bd, clue); assert bd.get(0, 0, 2, 0) == N

    bd = Board(theme); bd.set(0, 0, 2, 0, Y)             # right true -> left true (both ways)
    _prop_conditional(bd, clue); assert bd.get(0, 0, 1, 0) == Y


def test_conditional_compound_propagator():
    # if (0,0)-(1,0) then EITHER (0,0)-(2,0) or (0,1)-(2,0): modus ponens makes
    # the consequent disjunction fire, then unit-propagation forces the last open
    # disjunct once the other is ruled out.
    from logicgrid.clues import Conditional, Link, Or
    from logicgrid.deduce import _prop_conditional, _propagate_to_fixpoint, Contradiction

    theme = _plain3()
    cons = Or([Link((0, 0), (2, 0)), Link((0, 1), (2, 0))])
    clue = Conditional(Link((0, 0), (1, 0)), cons)

    bd = Board(theme)
    bd.set(0, 0, 1, 0, Y)          # antecedent holds
    bd.set(0, 0, 2, 0, N)          # first disjunct ruled out
    _prop_conditional(bd, clue)
    assert bd.get(0, 1, 2, 0) == Y  # so the other disjunct must hold

    # contrapositive: every consequent disjunct false -> antecedent broken
    bd = Board(theme)
    bd.set(0, 0, 2, 0, N); bd.set(0, 1, 2, 0, N)
    _prop_conditional(bd, clue)
    assert bd.get(0, 0, 1, 0) == N

    # a true antecedent with an impossible consequent is refuted
    bd = Board(theme)
    bd.set(0, 0, 1, 0, Y); bd.set(0, 0, 2, 0, N); bd.set(0, 1, 2, 0, N)
    try:
        _prop_conditional(bd, clue)
        assert False, "expected Contradiction"
    except Contradiction:
        pass


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


def _two_partition_theme():
    # Trade grouped (G={t0,t1}/H={t2,t3}); Quarter grouped (W={q0,q1}/E={q2,q3})
    return Theme(
        name="t", description="d", entity_noun="artisan",
        categories=[
            Category("Owner", ["A", "B", "C", "D"]),
            Category("Trade", ["t0", "t1", "t2", "t3"], group_noun="guild",
                     groups=(("G", ("t0", "t1")), ("H", ("t2", "t3")))),
            Category("Quarter", ["q0", "q1", "q2", "q3"], group_noun="ward",
                     groups=(("W", ("q0", "q1")), ("E", ("q2", "q3")))),
        ],
    )


def test_group_group_count_forces_into_both():
    from logicgrid.clues import GroupGroupCount
    from logicgrid.deduce import _prop_group_group_count

    bd = Board(_two_partition_theme())
    # Pin entities 0,1 into G (Trade) and 2,3 into H, so G = {e0,e1} exactly.
    for e in (0, 1):
        bd.set(0, e, 1, 2, N); bd.set(0, e, 1, 3, N)
    for e in (2, 3):
        bd.set(0, e, 1, 0, N); bd.set(0, e, 1, 1, N)
    # "at least 2 members of G are in W"; |G|=2 -> both must be in W (Quarter ward W={0,1})
    _prop_group_group_count(bd, GroupGroupCount(1, (0, 1), "G", 2, (0, 1), "W", 2, "atleast"))
    for e in (0, 1):  # forced into W -> not q2, q3
        assert bd.get(0, e, 2, 2) == N and bd.get(0, e, 2, 3) == N


def test_group_group_count_impossible_raises():
    from logicgrid.clues import GroupGroupCount
    from logicgrid.deduce import _prop_group_group_count, Contradiction

    bd = Board(_two_partition_theme())
    for e in (0, 1):  # in G, and out of ward E (q2,q3)
        bd.set(0, e, 1, 2, N); bd.set(0, e, 1, 3, N)
        bd.set(0, e, 2, 2, N); bd.set(0, e, 2, 3, N)
    for e in (2, 3):  # in H -> G is exactly {e0,e1}, none can be in E
        bd.set(0, e, 1, 0, N); bd.set(0, e, 1, 1, N)
    try:
        _prop_group_group_count(bd, GroupGroupCount(1, (0, 1), "G", 2, (2, 3), "E", 1, "atleast"))
        assert False, "expected Contradiction"
    except Contradiction:
        pass


def test_group_group_compare_impossible_raises():
    from logicgrid.clues import GroupGroupCompare
    from logicgrid.deduce import _prop_group_group_compare, Contradiction

    bd = Board(_two_partition_theme())
    # Make G have nobody possible in W while H has someone: pin e0,e1 (only G candidates)
    # out of W, and 2,3 into H. Then |G∩W| max 0, |H∩W| min ... force impossibility of G>H.
    for e in (0, 1):
        bd.set(0, e, 1, 2, N); bd.set(0, e, 1, 3, N)  # in G
        bd.set(0, e, 2, 0, N); bd.set(0, e, 2, 1, N)  # out of W
    for e in (2, 3):
        bd.set(0, e, 1, 0, N); bd.set(0, e, 1, 1, N)  # in H
        bd.set(0, e, 2, 2, N); bd.set(0, e, 2, 3, N)  # in W
    try:
        _prop_group_group_compare(bd, GroupGroupCompare(1, (0, 1), "G", (2, 3), "H", 2, (0, 1), "W"))
        assert False, "expected Contradiction (G can't out-count H in W)"
    except Contradiction:
        pass


def test_group_clues_stay_sound_and_no_guessing():
    # King's Guild hard puzzles that keep a group clue must stay logic-solvable
    # and the solver must reach the true solution (catches an unsound propagator).
    from logicgrid.webapi import build_puzzle

    # A small sample — group clues survive in most King's Guild draws and the
    # propagators are unit-tested separately, so a handful of end-to-end solves is
    # enough to catch an unsound propagator (raise the range for a heavier sweep).
    seen = 0
    for seed in range(8):
        th, puzzle, _rep, _ = build_puzzle(seed, "hard", items=4, categories=5, theme="kings_guild")
        names = {type(c).__name__ for c in puzzle.clues}
        if not (names & {"InGroup", "SameGroup", "DiffGroup", "NotInGroup", "GroupCount",
                         "GroupOrder", "GroupGroupCount", "GroupGroupCompare"}):
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
    # Hard puzzles that keep a Conditional must remain logic-solvable with the
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
    for seed in range(20):  # conditionals are rarer now; sample enough to catch one
        rng = random.Random(seed)
        _th, puzzle, _rep = generate_rated(lambda r: theme, rng, "mega")
        names = {type(c).__name__ for c in puzzle.clues}
        if "Conditional" not in names:
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


@pytest.mark.parametrize("target", ["hard", "mega"])
def test_sequential_price_stays_sound_and_no_guessing(target):
    # The Price (ordered) category brings sequential clues; their propagators
    # must be sound and keep puzzles solvable by logic alone.
    from logicgrid.clues import Adjacent, Between, Diff, Greater

    theme, puzzle, report = generate_rated(
        lambda r: build_cafe_theme(r, 4, categories=4, use_price=True), random.Random(7), target
    )
    # soundness/solvability is the invariant here — the sequential clues can push
    # the measured band a notch above the request, which is fine (it never guesses).
    assert report["band"] in ("hard", "mega", "giga", "tera")
    assert report["solved"]                       # no guessing
    assert _agrees(report["board"], puzzle.solution)
    # the ordered category exists and is value-sorted
    price = theme.categories[-1]
    assert price.ordered and price.values == sorted(price.values)
