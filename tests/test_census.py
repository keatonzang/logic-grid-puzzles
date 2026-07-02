"""Regression floors for shipped-clue diversity (see logicgrid/census.py).

Correctness has per-puzzle verifiers; diversity historically had none, and clue
families silently died in minimization. These floors are deliberately loose
(small samples, seeded) — they exist to catch collapses, not to pin exact
distributions. Re-measure with `python -m logicgrid.census` before tightening.
"""

from __future__ import annotations

from logicgrid.census import type_census

SEEDS = 8


def test_diversity_scales_with_difficulty():
    normal = type_census("kings_guild", "normal", SEEDS)
    hard = type_census("kings_guild", "hard", SEEDS)
    tera = type_census("kings_guild", "tera", SEEDS)

    # normal is direct facts only; the bands above it must read richer.
    assert normal["avg_distinct"] <= 3.0, normal["avg_distinct"]
    assert hard["avg_distinct"] >= 3.5, hard["avg_distinct"]
    assert tera["avg_distinct"] >= 4.5, tera["avg_distinct"]
    assert tera["avg_distinct"] > normal["avg_distinct"]


def test_hard_keeps_hierarchy_clues():
    # The minimize skew exists so grouped themes actually show their groups
    # (guilds in roughly half of hard King's Guild puzzles, not ~5%).
    hard = type_census("kings_guild", "hard", 8)
    assert hard["group_presence"] >= 0.25, hard["group_presence"]


def test_extreme_tiers_ship_showcase_shapes():
    # Pairings and conditionals must actually reach players at the top tiers.
    tera = type_census("kings_guild", "tera", 8)
    pairing = sum(n for s, n in tera["presence"].items() if s.startswith("ExactlyKLinks"))
    conditional = sum(n for s, n in tera["presence"].items() if s.startswith("Conditional"))
    assert pairing >= 5, tera["presence"]
    assert conditional >= 4, tera["presence"]
