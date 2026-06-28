"""Puzzle generation: solution shape, clue pool, minimization, and the
end-to-end uniqueness guarantee."""

from __future__ import annotations

import random

import pytest

from logicgrid.clues import Conditional, Positive
from logicgrid.generate import (
    build_clue_pool,
    generate_puzzle,
    minimize,
    random_solution,
)
from logicgrid.solver import count_solutions, is_unique


def test_random_solution_is_anchored_and_permuted(plain_theme):
    rng = random.Random(0)
    X = random_solution(plain_theme, rng)
    n, k = plain_theme.n, plain_theme.k
    for i in range(n):
        assert X[i][0] == i  # anchor column
    for c in range(k):
        assert sorted(X[e][c] for e in range(n)) == list(range(n))  # permutation


def test_clue_pool_all_true_and_pins_solution(plain_theme):
    rng = random.Random(1)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng)
    assert pool, "pool should be non-empty"
    assert all(c.holds(X) for c in pool)
    # the full pool always pins exactly one solution
    assert count_solutions(plain_theme, pool, cap=2) == 1


def test_sequential_disabled_by_default_enabled_on_request(ordered_theme):
    from logicgrid.clues import Diff, Greater

    rng = random.Random(2)
    X = random_solution(ordered_theme, rng)
    off = build_clue_pool(ordered_theme, X, rng)
    assert not any(isinstance(c, (Greater, Diff)) for c in off)  # disabled by default
    on = build_clue_pool(ordered_theme, X, rng, include_sequential=True)
    assert any(isinstance(c, (Greater, Diff)) for c in on)


def test_conditional_clues_gated_off_by_default(plain_theme):
    rng = random.Random(3)
    X = random_solution(plain_theme, rng)
    off = build_clue_pool(plain_theme, X, rng)  # default: enable_conditional False
    assert not any(isinstance(c, Conditional) for c in off)
    on = build_clue_pool(plain_theme, X, rng, enable_conditional=True)
    conds = [c for c in on if isinstance(c, Conditional)]
    assert conds
    assert any(not c.biconditional for c in conds)  # if-then present
    assert any(c.biconditional for c in conds)       # if-and-only-if present
    assert all(c.holds(X) for c in on)               # every generated clue true under X


def test_group_clues_need_a_grouping_and_the_flag():
    from logicgrid.clues import DiffGroup, InGroup, SameGroup
    from logicgrid.model import Category, Theme

    grouped = Theme("G", "", [
        Category("Owner", ["Ann", "Bo", "Cy", "Di"]),
        Category("Pet", ["Cat", "Dog", "Eel", "Fox"], group_noun="kind",
                 groups=(("Furred", ("Cat", "Dog", "Fox")), ("Finned", ("Eel",)))),
        Category("Toy", ["Ball", "Cube", "Disc", "Rope"]),
    ], entity_noun="home")
    rng = random.Random(2)
    X = random_solution(grouped, rng)

    is_group = lambda c: isinstance(c, (InGroup, SameGroup, DiffGroup))
    off = build_clue_pool(grouped, X, rng)  # flag defaults off
    assert not any(is_group(c) for c in off)
    on = build_clue_pool(grouped, X, rng, enable_groups=True)
    assert any(is_group(c) for c in on)
    assert all(c.holds(X) for c in on)


def test_group_instances_appear_in_disjunctions_and_conditionals():
    # Groups can stand in as instances: a Compound disjunction mixing a named link
    # with a group existential, and a GroupLink embedded inside a Conditional. Both
    # are gated behind enable_group_instances and need a grouped category.
    from logicgrid.clues import Compound, GroupLink, Not
    from logicgrid.model import Category, Theme

    grouped = Theme("G", "", [
        Category("Owner", ["Ann", "Bo", "Cy", "Di"]),
        Category("Pet", ["Cat", "Dog", "Eel", "Fox"], group_noun="kind",
                 groups=(("Furred", ("Cat", "Dog", "Fox")), ("Finned", ("Eel",)))),
        Category("Toy", ["Ball", "Cube", "Disc", "Rope"]),
    ], entity_noun="home")
    rng = random.Random(5)
    X = random_solution(grouped, rng)

    off = build_clue_pool(grouped, X, rng, enable_groups=True)  # instances default off
    assert not any(isinstance(c, Compound) for c in off)

    on = build_clue_pool(
        grouped, X, rng, enable_groups=True, enable_conditional=True,
        enable_group_instances=True,
    )
    compounds = [c for c in on if isinstance(c, Compound)]
    assert compounds, "expected group-instance disjunction clues"

    def embeds_group_link(s):
        if isinstance(s, GroupLink):
            return True
        if isinstance(s, Not):
            return embeds_group_link(s.s)
        return any(embeds_group_link(p) for p in getattr(s, "parts", ())) or (
            embeds_group_link(s.p) or embeds_group_link(s.q) if hasattr(s, "p") else False
        )

    from logicgrid.clues import Conditional
    cond_with_group = [
        c for c in on
        if isinstance(c, Conditional) and (embeds_group_link(c.ante) or embeds_group_link(c.cons))
    ]
    assert cond_with_group, "expected a GroupLink embedded in a conditional"
    assert all(c.holds(X) for c in on)  # every generated clue is true under X


def test_group_universal_disjunctions_generate():
    # "Either {X belongs to guild B} or {all members of ward A belong to guild B}":
    # a whole group standing in as a universal instance. Needs TWO partitions.
    from logicgrid.clues import Compound, GroupSubset, Or, Xor
    from logicgrid.model import Category, Theme

    two = Theme("KG", "", [
        Category("Owner", ["A", "B", "C", "D"]),
        Category("Guild", ["g0", "g1", "g2", "g3"], group_noun="guild",
                 groups=(("Joiner", ("g0", "g1")), ("Smith", ("g2", "g3")))),
        Category("Ward", ["w0", "w1", "w2", "w3"], group_noun="ward",
                 groups=(("Hill", ("w0", "w1")), ("Vale", ("w2", "w3")))),
    ], entity_noun="home")
    rng = random.Random(4)
    X = random_solution(two, rng)
    pool = build_clue_pool(two, X, rng, enable_groups=True, enable_group_instances=True)

    def has_universal(c):
        if not isinstance(c, Compound):
            return False
        parts = c.stmt.parts if isinstance(c.stmt, Or) else (
            (c.stmt.p, c.stmt.q) if isinstance(c.stmt, Xor) else ())
        return any(isinstance(p, GroupSubset) for p in parts)

    universals = [c for c in pool if has_universal(c)]
    assert universals, "expected group-universal disjunction clues"
    assert all(c.holds(X) for c in pool)


def test_group_instances_need_a_grouping():
    # No grouping -> no group-instance clues even with the flag on.
    from logicgrid.clues import Compound

    from logicgrid.model import Category, Theme
    plain = Theme("P", "", [
        Category("Owner", ["Ann", "Bo", "Cy"]),
        Category("Pet", ["Cat", "Dog", "Eel"]),
        Category("Toy", ["Ball", "Cube", "Disc"]),
    ], entity_noun="home")
    rng = random.Random(3)
    X = random_solution(plain, rng)
    pool = build_clue_pool(plain, X, rng, enable_group_instances=True, enable_conditional=True)
    assert not any(isinstance(c, Compound) for c in pool)


def test_group_count_never_degenerate():
    # A GroupCount must carry genuine "which ones?" ambiguity: a bound that forces
    # every anchor IN (K == size) or OUT (K == 0) is just a conjunction of InGroup
    # facts dressed up as set-counting ("at least two of [two things]"). K must stay
    # strictly inside 1..size-1 for every mode.
    from logicgrid.clues import GroupCount
    from logicgrid.model import Category, Theme

    grouped = Theme("G", "", [
        Category("Owner", ["Ann", "Bo", "Cy", "Di"]),
        Category("Pet", ["Cat", "Dog", "Eel", "Fox"], group_noun="kind",
                 groups=(("Furred", ("Cat", "Dog", "Fox")), ("Finned", ("Eel",)))),
        Category("Toy", ["Ball", "Cube", "Disc", "Rope"]),
    ], entity_noun="home")

    seen = 0
    for seed in range(40):
        rng = random.Random(seed)
        X = random_solution(grouped, rng)
        pool = build_clue_pool(grouped, X, rng, enable_groups=True)
        for c in pool:
            if isinstance(c, GroupCount):
                seen += 1
                size = len(c.anchors)
                assert 1 <= c.k <= size - 1, (c.mode, c.k, size)
                assert not (c.mode in ("exactly", "atleast") and c.k == size)
                assert not (c.mode in ("exactly", "atmost") and c.k == 0)
                assert c.holds(X)
    assert seen, "expected some GroupCount clues to be generated"


def test_group_clues_absent_without_a_grouping(plain_theme):
    # A theme with no grouping never yields group clues even with the flag on.
    from logicgrid.clues import DiffGroup, InGroup, SameGroup

    rng = random.Random(2)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng, enable_groups=True)
    assert not any(isinstance(c, (InGroup, SameGroup, DiffGroup)) for c in pool)


def test_groups_enabled_above_normal_only():
    from logicgrid.generate import _DIFFICULTY_POOL

    assert _DIFFICULTY_POOL["normal"].get("enable_groups", False) is False
    for d in ("hard", "mega", "giga", "tera"):
        assert _DIFFICULTY_POOL[d]["enable_groups"] is True


def test_conditionals_are_rich_tiers_only(plain_theme):
    # normal/hard never surface conditionals; mega+ does (over several seeds).
    palette = {d: set() for d in ("normal", "hard", "mega")}
    for d in palette:
        for s in range(20):
            p = generate_puzzle(plain_theme, random.Random(s), difficulty=d)
            palette[d].update(type(c).__name__ for c in p.clues)
    assert "Conditional" not in palette["normal"]
    assert "Conditional" not in palette["hard"]
    assert "Conditional" in palette["mega"]  # mega/giga/tera share the rich pool


def test_difficulty_controls_clue_palette_and_size(plain_theme):
    from logicgrid.clues import ExactlyKLinks, GroupMatch
    from logicgrid.generate import DIFFICULTIES

    sizes = {}
    for d in DIFFICULTIES:
        seen = set()
        total = 0
        for s in range(12):
            p = generate_puzzle(plain_theme, random.Random(s), difficulty=d)
            seen.update(type(c).__name__ for c in p.clues)
            total += len(p.clues)
        sizes[d] = total
        if d == "normal":
            assert seen <= {"Positive", "Negative"}  # is / is-not only
        if d == "mega":
            assert "GroupMatch" in seen or "ExactlyKLinks" in seen  # trickiest unlocked
    # normal hands back more clues than the leanest rich tier (extra given vs minimal)
    assert sizes["normal"] > sizes["mega"]


def test_unknown_difficulty_raises(plain_theme):
    with pytest.raises(ValueError, match="unknown difficulty"):
        generate_puzzle(plain_theme, random.Random(0), difficulty="legendary")


def test_pool_contains_all_disjunction_types(plain_theme):
    from logicgrid.clues import Among, EitherOr, Neither

    rng = random.Random(4)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng)
    for cls in (Among, EitherOr, Neither):
        clues = [c for c in pool if isinstance(c, cls)]
        assert clues, f"no {cls.__name__} clues generated"
        assert {len(c.options) for c in clues} <= {2, 3}  # default N in {2, 3}


def test_disjunction_options_sometimes_span_categories(plain_theme):
    from logicgrid.clues import Among, EitherOr, Neither

    rng = random.Random(4)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng)
    disjunctions = [c for c in pool if isinstance(c, (Among, EitherOr, Neither))]
    # at least one clue draws options from more than one distinct category
    spans = [c for c in disjunctions if len({o[0] for o in c.options}) > 1]
    assert spans, "expected some cross-category option lists"


def test_all_pool_clues_true_under_solution(plain_theme):
    # Every pooled clue (disjunctions included) must hold under the generating X.
    rng = random.Random(11)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng)
    assert all(c.holds(X) for c in pool)


def test_all_different_generated_spanning_categories(plain_theme):
    from logicgrid.clues import AllDifferent

    rng = random.Random(11)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng)
    diffs = [c for c in pool if isinstance(c, AllDifferent)]
    assert diffs, "expected some AllDifferent clues"
    for c in diffs:
        assert len(c.terms) >= 3, "generated only for N >= 3"
        assert len({t[0] for t in c.terms}) >= 2, "must span >= 2 categories"
        assert c.holds(X)  # true under the solution


def test_pool_contains_pairing_and_match(plain_theme):
    from logicgrid.clues import ExactlyKLinks, GroupMatch

    rng = random.Random(11)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng)
    pairings = [c for c in pool if isinstance(c, ExactlyKLinks)]
    matches = [c for c in pool if isinstance(c, GroupMatch)]
    assert pairings and matches
    for c in pairings:
        assert c.k == 1 and 2 <= len(c.links) <= 3  # default K=1, N in {2,3}
        assert c.holds(X)
    for c in matches:
        assert 2 <= len(c.left) == len(c.right) <= 3
        assert c.holds(X)


def test_group_match_sides_are_category_disjoint(plain_theme):
    from logicgrid.clues import GroupMatch

    rng = random.Random(11)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng)
    matches = [c for c in pool if isinstance(c, GroupMatch)]
    assert matches
    for c in matches:
        lcats = {t[0] for t in c.left}
        rcats = {t[0] for t in c.right}
        assert lcats.isdisjoint(rcats)  # a category never spans both sides


def test_group_match_groups_can_span_categories(plain_theme):
    from logicgrid.clues import GroupMatch

    # Across a few seeds, at least one group should mix categories on a side.
    spans = False
    for s in range(6):
        rng = random.Random(s)
        X = random_solution(plain_theme, rng)
        for c in build_clue_pool(plain_theme, X, rng):
            if isinstance(c, GroupMatch) and (
                len({t[0] for t in c.left}) > 1 or len({t[0] for t in c.right}) > 1
            ):
                spans = True
    assert spans


def test_pairing_k_and_sizes_configurable(plain_theme):
    from logicgrid.clues import ExactlyKLinks

    rng = random.Random(11)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng, pairing_sizes=(3,), pairing_k=2)
    pairings = [c for c in pool if isinstance(c, ExactlyKLinks)]
    assert pairings
    for c in pairings:
        assert c.k == 2 and len(c.links) == 3
        assert c.holds(X)


def test_all_different_respects_size_bound():
    # n == 4 here, so N == 4 ('all four different') should be reachable.
    import random as _random

    from logicgrid import load_theme
    from logicgrid.clues import AllDifferent

    theme = load_theme("themes/morning_rush.yaml")
    rng = _random.Random(2)
    X = random_solution(theme, rng)
    pool = build_clue_pool(theme, X, rng)
    sizes = {len(c.terms) for c in pool if isinstance(c, AllDifferent)}
    assert sizes <= {3, 4}
    assert 4 in sizes  # n == 4 allows the full N == 4 clue


def test_at_least_k_among_is_distinct_and_always_ambiguous(wide_theme):
    from logicgrid.clues import Among

    rng = random.Random(11)
    X = random_solution(wide_theme, rng)
    pool = build_clue_pool(wide_theme, X, rng)
    multi = [c for c in pool if isinstance(c, Among) and c.at_least >= 2]
    assert multi, "expected some 'at least K' Among clues"
    for c in multi:
        cats = [o[0] for o in c.options]
        assert len(cats) == len(set(cats)), "options must be in distinct categories"
        assert c.at_least < len(c.options), "K must stay below N (no strong K==N case)"
        assert c._matches(X) >= c.at_least  # genuinely true under the solution


def test_multi_match_can_be_disabled(wide_theme):
    from logicgrid.clues import Among

    rng = random.Random(11)
    X = random_solution(wide_theme, rng)
    pool = build_clue_pool(wide_theme, X, rng, multi_match=False)
    assert all(c.at_least == 1 for c in pool if isinstance(c, Among))


def test_disjunction_options_not_forced_same_category(wide_theme):
    # Option lists are sampled freely across categories — never *forced* into a
    # single category. With a wide theme, cross-category lists should dominate.
    from logicgrid.clues import Among, EitherOr, Neither

    rng = random.Random(3)
    X = random_solution(wide_theme, rng)
    pool = build_clue_pool(wide_theme, X, rng)
    threshold1 = [
        c
        for c in pool
        if isinstance(c, (Among, EitherOr, Neither)) and getattr(c, "at_least", 1) == 1
    ]
    assert threshold1
    spanning = [c for c in threshold1 if len({o[0] for o in c.options}) > 1]
    assert spanning, "free sampling should yield cross-category option lists"


def test_generated_either_or_has_exactly_one_true_option(plain_theme):
    from logicgrid.clues import EitherOr

    rng = random.Random(11)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng)
    for c in pool:
        if isinstance(c, EitherOr):
            assert c._matches(X) == 1


def test_among_sizes_configurable_for_larger_n(plain_theme):
    from logicgrid.clues import Among, EitherOr, Neither

    rng = random.Random(7)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng, among_sizes=(2,))
    disjunctions = [c for c in pool if isinstance(c, (Among, EitherOr, Neither))]
    assert disjunctions
    assert all(len(c.options) == 2 for c in disjunctions)


def test_minimize_preserves_uniqueness_and_is_minimal(plain_theme):
    rng = random.Random(3)
    X = random_solution(plain_theme, rng)
    pool = build_clue_pool(plain_theme, X, rng)
    minimal = minimize(plain_theme, pool, rng)
    assert is_unique(plain_theme, minimal)
    assert len(minimal) <= len(pool)
    # locally minimal: dropping any single clue breaks uniqueness
    for cl in minimal:
        trial = [c for c in minimal if c is not cl]
        assert not is_unique(plain_theme, trial)


@pytest.mark.parametrize("seed", range(6))
def test_generate_puzzle_unique_and_consistent(plain_theme, ordered_theme, seed):
    for theme in (plain_theme, ordered_theme):
        puzzle = generate_puzzle(theme, random.Random(seed))
        # exactly one solution
        assert count_solutions(theme, puzzle.clues, cap=2) == 1
        # the generating solution satisfies every emitted clue
        assert all(c.holds(puzzle.solution) for c in puzzle.clues)


def test_same_seed_is_reproducible(plain_theme):
    a = generate_puzzle(plain_theme, random.Random(42))
    b = generate_puzzle(plain_theme, random.Random(42))
    assert a.solution == b.solution
    assert [c.text(plain_theme) for c in a.clues] == [c.text(plain_theme) for c in b.clues]
