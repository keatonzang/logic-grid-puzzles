"""Big puzzles: unclamped shapes, theme compatibility, re-theming (values,
groups, nested hierarchies), and the static bundle format.

Generation at real big shapes takes minutes, so these tests exercise the
re-theming machinery on hand-built themes and clues (fast and precise), plus
one small end-to-end bundle at a cheap shape."""

from __future__ import annotations

import json
import random

import pytest

from logicgrid import bigpuzzles
from logicgrid.clues import (
    AbsApart,
    AtLeastApart,
    Diff,
    DiffGroup,
    GroupCount,
    InGroup,
    SameGroup,
    SetCount,
    _plural,
)
from logicgrid.webapi import NESTED_MIN_ITEMS, THEMES, build_theme


# --- Shapes and compatibility --------------------------------------------------

def test_unclamped_build_theme_supports_4x6():
    t = build_theme(THEMES["dnd"], random.Random(1), items=6, categories=4,
                    n_numeric=1, clamp=False)
    t.validate()
    assert t.n == 6 and t.k == 4
    assert any(c.ordered for c in t.categories)


def test_clamped_build_theme_still_caps():
    t = build_theme(THEMES["dnd"], random.Random(1), items=6, categories=4,
                    n_numeric=1)  # clamp defaults True: the live web path
    assert t.n == 4  # max_items_for(4) == 4


def test_compatibility_ordered_and_pools():
    # 4x6 with an ordered category: every theme but mystery (no numeric)
    keys = bigpuzzles.compatible_themes(4, 6, needs_ordered=True)
    assert "mystery" not in keys and len(keys) == 8
    # without ordered, mystery qualifies too
    assert "mystery" in bigpuzzles.compatible_themes(4, 6, needs_ordered=False)
    # nested hierarchies: only the themes with nested vocabularies
    assert set(bigpuzzles.compatible_themes(3, 8, True, n_nested=1)) == {
        "kings_guild", "fishing",
    }
    # chess's fixed (factual) camps are not imposable flavor
    grouped = bigpuzzles.compatible_themes(4, 6, True, n_grouped=1)
    assert "chess" not in grouped
    assert {"kings_guild", "fishing"} <= set(grouped)


# --- Nested hierarchy construction ----------------------------------------------

def test_nested_groups_build_and_validate():
    t = build_theme(THEMES["kings_guild"], random.Random(42), items=8,
                    categories=3, n_numeric=1, use_groups=True, clamp=False)
    t.validate()
    nested = [c for c in t.categories if c.has_supergroups]
    assert len(nested) == 1
    c = nested[0]
    assert len(c.groups) >= 3 and len(c.supergroups) == 2
    # every group nests wholly inside one supergroup (validate enforces too)
    for _label, members in c.groups:
        homes = {s for s, mem in c.supergroups if members[0] in mem}
        assert len(homes) == 1


def test_nested_needs_enough_items():
    t = build_theme(THEMES["kings_guild"], random.Random(42), items=5,
                    categories=3, n_numeric=1, use_groups=True, clamp=False)
    assert not any(c.has_supergroups for c in t.categories)


def test_plural_handles_head_noun_phrases():
    assert _plural("side of town") == "sides of town"
    assert _plural("ward") == "wards"
    assert _plural("entry") == "entries"


# --- Re-theming: hand-built fixtures ---------------------------------------------

def _donor_and_target(items=6, seed=7):
    donor = build_theme(THEMES["kings_guild"], random.Random(seed), items=items,
                        categories=3, n_numeric=1, use_groups=True, clamp=False)
    target = bigpuzzles.dress("fishing", seed, donor)
    return donor, target


def _solution(n, k, seed=3):
    rng = random.Random(seed)
    X = [[0] * k for _ in range(n)]
    for i in range(n):
        X[i][0] = i
    for c in range(1, k):
        perm = list(range(n))
        rng.shuffle(perm)
        for i in range(n):
            X[i][c] = perm[i]
    return X


def test_dress_mirrors_shape_and_partitions():
    donor, target = _donor_and_target()
    assert target.n == donor.n and target.k == donor.k
    for dc, tc in zip(donor.categories, target.categories):
        assert dc.ordered == tc.ordered
        assert dc.has_groups == tc.has_groups
        assert dc.has_supergroups == tc.has_supergroups
        if dc.has_groups:
            d_parts = {
                tuple(sorted(dc.items.index(m) for m in mem))
                for _l, mem in dc.groups
            }
            t_parts = {
                tuple(sorted(tc.items.index(m) for m in mem))
                for _l, mem in tc.groups
            }
            assert d_parts == t_parts  # same index structure, new labels


def test_value_clue_remap_preserves_logic():
    donor, target = _donor_and_target()
    ocat = next(i for i, c in enumerate(donor.categories) if c.ordered)
    dvals, tvals = donor.categories[ocat].values, target.categories[ocat].values
    dstep, tstep = dvals[1] - dvals[0], tvals[1] - tvals[0]
    n, k = donor.n, donor.k
    X = _solution(n, k)
    rank = {e: X[e][ocat] for e in range(n)}
    hi = max(range(n), key=lambda e: rank[e])
    lo = min(range(n), key=lambda e: rank[e])
    gap = rank[hi] - rank[lo]
    a, b = (0, X[hi][0]), (1, X[lo][1])

    clues = [
        Diff(ocat, a, b, gap * dstep, dvals),
        # a ragged in-between delta: remaps via its rank bound, not division
        AtLeastApart(ocat, a, b, (gap - 1) * dstep + 1, dvals),
        AbsApart(ocat, a, b, (gap - 1) * dstep + 1, True, dvals),
        AbsApart(ocat, a, b, gap * dstep + 1, False, dvals),
    ]
    assert all(c.holds(X) for c in clues)
    rethemed = bigpuzzles.retheme_clues(clues, target)
    assert all(c.holds(X) for c in rethemed)
    assert rethemed[0].delta == gap * tstep
    assert rethemed[1].delta == gap * tstep  # ceil to the same rank bound
    assert rethemed[1]._values is tvals
    # originals untouched (deep clones)
    assert clues[0].delta == gap * dstep


def test_group_clues_relabel_under_target_vocabulary():
    donor, target = _donor_and_target()
    gcat = next(i for i, c in enumerate(donor.categories) if c.has_groups)
    dc, tc = donor.categories[gcat], target.categories[gcat]
    parts = [
        tuple(sorted(dc.items.index(m) for m in mem)) for _l, mem in dc.groups
    ]
    labels = [l for l, _ in dc.groups]
    n, k = donor.n, donor.k
    X = _solution(n, k)

    # pick an entity actually in group 0 so InGroup holds
    e_in = next(e for e in range(n) if X[e][gcat] in parts[0])
    anchor = (0, X[e_in][0])
    others = [e for e in range(n) if e != e_in]
    same = next((e for e in others if X[e][gcat] in parts[0]), None)

    clues = [
        InGroup(anchor, gcat, labels[0], parts[0]),
        GroupCount([(0, X[e][0]) for e in range(3)], gcat, labels[0], parts[0],
                   sum(1 for e in range(3) if X[e][gcat] in parts[0]) or 1,
                   "atmost" if not sum(1 for e in range(3) if X[e][gcat] in parts[0]) else "exactly"),
        SetCount([("group", gcat, parts[0], labels[0])],
                 [(gcat + 1 if gcat + 1 < k else 0, 0)], "whatever", False, 0, "atleast"),
    ]
    if same is not None:
        clues.append(SameGroup(anchor, (1, X[same][1]), gcat, dc.group_noun, parts))

    rethemed = bigpuzzles.retheme_clues(clues, target)
    t_labels = {l for l, _ in tc.groups} | {l for l, _ in tc.supergroups}
    assert rethemed[0].label in t_labels and rethemed[0].label != labels[0]
    assert rethemed[1].label in t_labels
    assert rethemed[2].subjects[0][3] in t_labels
    assert "or" in rethemed[2].target_label or rethemed[2].target_label  # rebuilt from items
    if same is not None:
        assert rethemed[-1].group_noun in (tc.group_noun, tc.supergroup_noun)
    # every rethemed text mentions no donor vocabulary
    for c in rethemed:
        txt = c.text(target)
        assert "Guild" not in txt and "Ward" not in txt and "Side" not in txt


def test_double_sequential_compat_and_dress():
    # two dials: only school (Grade+Period) and chess (Rating+Placing) qualify
    assert set(bigpuzzles.compatible_themes(4, 5, 2)) == {"school", "chess"}
    donor = build_theme(THEMES["school"], random.Random(5), 5, 4,
                        n_numeric=2, clamp=False)
    assert sum(c.ordered for c in donor.categories) == 2
    target = bigpuzzles.dress("chess", 5, donor)
    assert [c.ordered for c in donor.categories] == [
        c.ordered for c in target.categories
    ]
    # dial 1 valued on both; dial 2 rank-only on both (Period vs Placing)
    d1, d2 = [c for c in target.categories if c.ordered]
    assert d1.values is not None and d2.values is None


def test_downgrade_hits_exact_band_and_keeps_solution():
    # seed 777 at 3x5 deterministically measures giga; the downgrade must land
    # exactly on the target band with the same solution, every clue true
    theme, puzzle, report = bigpuzzles.generate_big(777, "giga", 3, 5)
    assert report["band"] == "giga"
    got = bigpuzzles.downgrade(theme, puzzle, "hard")
    assert got is not None
    variant, rep = got
    assert rep["band"] == "hard"
    assert variant.solution == puzzle.solution
    assert all(c.holds(puzzle.solution) for c in variant.clues)
    # the parent is untouched
    assert grade_band(theme, puzzle) == "giga"


def grade_band(theme, puzzle):
    from logicgrid.deduce import grade
    return grade(theme, puzzle.clues)["band"]


def test_walk_byproducts_are_collected_and_bundlable():
    # every logic-solvable candidate a walk grades is collectable; a byproduct
    # bundles under its MEASURED band with the request recorded honestly
    cands = bigpuzzles.generate_big_all(12345, "hard", 3, 5)
    assert cands
    theme_obj, puzzle, report = cands[0]
    assert report["band"] != "ambiguous"
    b = bigpuzzles.bundle_candidate("t-byprod", 12345, "hard",
                                    theme_obj, puzzle, report)
    assert b["difficulty"] == report["band"]
    assert b["requested"] == "hard"
    assert b["themes"]


# --- End-to-end bundle (small shape, kept cheap) ---------------------------------

@pytest.fixture(scope="module")
def small_bundle():
    return bigpuzzles.build_big_bundle(
        "t-3x5", seed=12345, difficulty="hard", categories=3, items=5
    )


def test_bundle_shape_and_json(small_bundle):
    b = small_bundle
    assert b["categories"] == 3 and b["items"] == 5
    assert b["default_theme"] in b["themes"]
    assert len(b["themes"]) >= 2
    json.dumps(b)  # fully serialisable (no _ctx leaks)


def test_bundle_themes_agree_structurally(small_bundle):
    b = small_bundle
    counts = {key: (len(t["clues"]), len(t["hints"]), len(t["solution"]))
              for key, t in b["themes"].items()}
    assert len(set(counts.values())) == 1  # same logic everywhere
    for t in b["themes"].values():
        assert t["solution"] and t["clues"] and t["hints"]
        for step in t["hints"]:
            assert {"key", "a", "b", "value", "text"} <= set(step)
