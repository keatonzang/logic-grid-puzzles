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


def test_set_count_clues_generate_unions_and_subsets():
    # SetCount: cardinality over a union of set instances. Every generated one is
    # true under X, includes >= 1 group subject, and has a strictly-interior K.
    from logicgrid.clues import SetCount
    from logicgrid.model import Category, Theme

    two = Theme("KG", "", [
        Category("Owner", ["A", "B", "C", "D"]),
        Category("Guild", ["g0", "g1", "g2", "g3"], group_noun="guild",
                 groups=(("Joiner", ("g0", "g1")), ("Smith", ("g2", "g3")))),
        Category("Ward", ["w0", "w1", "w2", "w3"], group_noun="ward",
                 groups=(("Hill", ("w0", "w1")), ("Vale", ("w2", "w3")))),
    ], entity_noun="home")

    seen = 0
    saw_union = False
    for seed in range(40):
        rng = random.Random(seed)
        X = random_solution(two, rng)
        pool = build_clue_pool(two, X, rng, enable_groups=True, enable_set_count=True)
        for c in pool:
            if not isinstance(c, SetCount):
                continue
            seen += 1
            assert c.holds(X)
            assert any(s[0] == "group" for s in c.subjects)  # always >= 1 group
            size = len(c.subject_entities(X))
            assert 1 <= c.k <= size - 1                       # strictly interior
            # a named subject is never drawn from the grouped or target category —
            # its membership/target-hit would be decidable a priori (dead weight)
            tcat = c.target_cells[0][0]
            gcats = {s[1] for s in c.subjects if s[0] == "group"}
            for s in c.subjects:
                if s[0] == "entity":
                    assert s[1][0] not in gcats | {tcat}
            if len(c.subjects) > 1:
                saw_union = True
    assert seen, "expected SetCount clues to be generated"
    assert saw_union, "expected at least one mixed-union SetCount"


def test_conditional_atoms_never_share_a_line(plain_theme):
    # Two atoms about one term in one category decide each other under the
    # bijection — allowing them makes vacuous or disguised-negative conditionals
    # ("if Latte goes with the Bagel, then Latte does not go with the Scone").
    from logicgrid.clues import And, Conditional, GroupLink, Link, Not, Or, Xor

    def atoms(s):
        if isinstance(s, Not):
            return atoms(s.s)
        if isinstance(s, (And, Or)):
            return [a for p in s.parts for a in atoms(p)]
        if isinstance(s, Xor):
            return atoms(s.p) + atoms(s.q)
        return [s]

    for seed in range(8):
        rng = random.Random(seed)
        X = random_solution(plain_theme, rng)
        pool = build_clue_pool(plain_theme, X, rng, enable_conditional=True,
                               conditional_compound_prob=0.5)
        for c in pool:
            if not isinstance(c, Conditional):
                continue
            lines = []
            for a in atoms(c.ante) + atoms(c.cons):
                if isinstance(a, Link):
                    lines += [(a.a, a.b[0]), (a.b, a.a[0])]
                elif isinstance(a, GroupLink):
                    lines.append((a.anchor, a.cat))
            assert len(lines) == len(set(lines)), c.text(plain_theme)


def test_set_count_needs_the_flag_and_a_grouping(plain_theme):
    from logicgrid.clues import SetCount

    rng = random.Random(2)
    X = random_solution(plain_theme, rng)
    off = build_clue_pool(plain_theme, X, rng)  # flag default off
    assert not any(isinstance(c, SetCount) for c in off)
    # flag on but no grouping in the theme -> still none
    on = build_clue_pool(plain_theme, X, rng, enable_set_count=True)
    assert not any(isinstance(c, SetCount) for c in on)


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


def test_compound_conditionals_are_extreme_tiers_only(plain_theme):
    # Compound sides (And/Or/Xor inside an if-then/iff) are the heaviest clue to
    # parse: mega stays atom=>atom, only giga/tera roll compounds.
    from logicgrid.clues import And, Conditional, Or, Xor
    from logicgrid.generate import _DIFFICULTY_POOL, build_clue_pool

    assert _DIFFICULTY_POOL["mega"]["conditional_compound_prob"] == 0.0
    for d in ("giga", "tera"):
        assert _DIFFICULTY_POOL[d]["conditional_compound_prob"] > 0.0

    is_compound = lambda c: isinstance(c.ante, (And, Or, Xor)) or isinstance(
        c.cons, (And, Or, Xor)
    )
    seen = {0.0: False, 0.28: False}
    for prob in seen:
        for s in range(12):
            rng = random.Random(s)
            X = random_solution(plain_theme, rng)
            pool = build_clue_pool(
                plain_theme, X, rng,
                enable_conditional=True, conditional_compound_prob=prob,
            )
            conds = [c for c in pool if isinstance(c, Conditional)]
            assert conds
            seen[prob] = seen[prob] or any(is_compound(c) for c in conds)
    assert not seen[0.0]  # prob 0 never builds a compound side
    assert seen[0.28]     # the extreme-tier prob does (over several seeds)


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
        # pairwise-distinct categories: same-category terms differ by definition,
        # so a repeat would pad the clue with a vacuous pair
        assert len({t[0] for t in c.terms}) == len(c.terms)
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


def test_exclusive_pairings_mix_independent_and_overlapping(plain_theme):
    # Exclusive pairings are mostly fully independent ("A-X or B-Y") with a
    # minority of overlapping draws (shared value / chain) kept for texture
    # (_PAIRING_OVERLAP_PROB) — both flavors must appear, independent in the
    # majority, and a repeated link never says anything so it never ships.
    from logicgrid.clues import ExactlyKLinks

    distinct = overlapping = 0
    for seed in range(10):
        rng = random.Random(seed)
        X = random_solution(plain_theme, rng)
        pool = build_clue_pool(plain_theme, X, rng)
        for c in pool:
            if not isinstance(c, ExactlyKLinks):
                continue
            assert len(set(c.links)) == len(c.links)
            terms = [t for link in c.links for t in link]
            if len(set(terms)) == 2 * len(c.links):
                distinct += 1
            else:
                overlapping += 1
    assert distinct and overlapping, (distinct, overlapping)
    assert distinct > overlapping, (distinct, overlapping)


def test_all_different_respects_size_bound():
    # N caps at min(items, categories): terms need N distinct entities AND N
    # pairwise-distinct categories. space_colony (4 categories, 5 items) admits
    # N == 4; morning_rush (3 categories) caps at N == 3 despite its 4 items.
    import random as _random

    from logicgrid import load_theme
    from logicgrid.clues import AllDifferent

    theme = load_theme("themes/space_colony.yaml")
    rng = _random.Random(2)
    X = random_solution(theme, rng)
    pool = build_clue_pool(theme, X, rng)
    sizes = {len(c.terms) for c in pool if isinstance(c, AllDifferent)}
    assert sizes <= {3, 4}
    assert 4 in sizes  # k == 4 and n == 5 allow the full N == 4 clue

    cafe = load_theme("themes/morning_rush.yaml")  # k == 3: size-4 impossible
    rng = _random.Random(2)
    X = random_solution(cafe, rng)
    sizes = {len(c.terms) for c in build_clue_pool(cafe, X, rng)
             if isinstance(c, AllDifferent)}
    assert sizes == {3}


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


def test_semantic_screen_rejects_tautologies(plain_theme):
    # "at most 2 of these 2 options" is vacuously true on every solution —
    # zero information, so the screen drops it with no per-family guard.
    from logicgrid.clues import AtMost
    from logicgrid.generate import _semantic_screen

    rng = random.Random(2)
    X = random_solution(plain_theme, rng)
    trivial = AtMost((0, 0), [(1, 0), (2, 1)], 2)
    assert _semantic_screen(plain_theme, X, rng, [trivial]) == []


def test_semantic_screen_rejects_intra_clue_redundancy(plain_theme):
    # The degenerate disjunction "A goes with X, or A goes with X": one branch
    # (trivially) implies the other, so the connective collapses to one side.
    from logicgrid.clues import Compound, Link, Or
    from logicgrid.generate import _semantic_screen

    rng = random.Random(3)
    X = random_solution(plain_theme, rng)
    dup = Compound(Or([Link((0, 0), (1, 0)), Link((0, 0), (1, 0))]))
    assert _semantic_screen(plain_theme, X, rng, [dup]) == []


def test_semantic_screen_dedupes_equivalent_content(plain_theme):
    # The same fact stated two ways keeps only the cheaper reading, whichever
    # order the pool presents them in.
    from logicgrid.clues import Compound, Link, Negative, Not
    from logicgrid.generate import _semantic_screen

    rng = random.Random(4)
    X = random_solution(plain_theme, rng)
    neg = Negative((0, 0), (1, 1))
    wordy = Compound(Not(Link((0, 0), (1, 1))))
    kept = _semantic_screen(plain_theme, X, random.Random(4), [neg, wordy])
    assert kept == [neg]
    kept = _semantic_screen(plain_theme, X, random.Random(4), [wordy, neg])
    assert kept == [neg]


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
