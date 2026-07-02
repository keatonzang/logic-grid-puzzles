"""Diversity and calibration census over *shipped* puzzles.

The generator's correctness is self-verifying (uniqueness counting, logic-
solvability, measured bands), but clue DIVERSITY has no invariant of its own —
clue families can silently die in minimization (pairings and conditionals both
did, historically) without any test noticing. This module is the feedback
loop: it generates puzzles through the real shipping path (webapi.build_puzzle)
and reports what actually reaches players, per difficulty tier.

Run it any time generation, minimization, or pool composition changes:

    python -m logicgrid.census                    # kings_guild, all tiers
    python -m logicgrid.census --theme cafe --seeds 20 --calibration

`tests/test_census.py` pins regression floors on these numbers (diversity must
scale with tier; showcase clue types must actually ship at the extreme tiers).
"""

from __future__ import annotations

from collections import Counter

from .clues import Compound, Conditional, ExactlyKLinks, Or, Xor

_GROUP_CLUE_NAMES = {
    "InGroup", "SameGroup", "DiffGroup", "NotInGroup", "GroupCount",
    "GroupOrder", "GroupGroupCount", "GroupGroupCompare", "SetCount",
    "GroupMatch",
}


def structural_signature(clue) -> str:
    """A clue's *shape* — the class name refined by the structural flavors a
    player experiences as genuinely different clue kinds."""
    name = type(clue).__name__
    if isinstance(clue, ExactlyKLinks):
        terms = [t for link in clue.links for t in link]
        overlap = "shared" if len(set(terms)) < len(terms) else "distinct"
        return f"{name}[{clue.k}of{len(clue.links)},{overlap}]"
    if isinstance(clue, Conditional):
        kind = "iff" if clue.biconditional else "if-then"
        compound = any(
            type(s).__name__ in ("And", "Or", "Xor") for s in (clue.ante, clue.cons)
        )
        return f"{name}[{kind}{',compound' if compound else ''}]"
    if isinstance(clue, Compound):
        op = type(clue.stmt).__name__.lower()
        return f"{name}[{op}]"
    return name


def type_census(theme: str, difficulty: str, seeds: int) -> dict:
    """Distribution of shipped clue shapes for one (theme, difficulty).

    Returns counts (total clues per signature), presence (puzzles containing
    the signature), avg_clues, avg_distinct (mean distinct signatures per
    puzzle — the headline diversity number), and group_presence (fraction of
    puzzles carrying at least one hierarchy clue).
    """
    from .webapi import build_puzzle

    counts: Counter = Counter()
    presence: Counter = Counter()
    distinct_per_puzzle = []
    total_clues = 0
    group_puzzles = 0
    for seed in range(seeds):
        _, puzzle, _, _ = build_puzzle(seed=seed, difficulty=difficulty, theme=theme)
        sigs = [structural_signature(c) for c in puzzle.clues]
        counts.update(sigs)
        presence.update(set(sigs))
        distinct_per_puzzle.append(len(set(sigs)))
        total_clues += len(sigs)
        if any(type(c).__name__ in _GROUP_CLUE_NAMES for c in puzzle.clues):
            group_puzzles += 1
    return {
        "theme": theme,
        "difficulty": difficulty,
        "puzzles": seeds,
        "counts": dict(counts.most_common()),
        "presence": dict(presence),
        "avg_clues": total_clues / seeds,
        "avg_distinct": sum(distinct_per_puzzle) / seeds,
        "group_presence": group_puzzles / seeds,
    }


def calibration(theme: str, seeds: int, targets=("normal", "hard", "mega", "giga", "tera")) -> dict:
    """Exact-band hit rate per requested tier through the shipping path."""
    from .webapi import build_puzzle

    out = {}
    for target in targets:
        bands = [
            build_puzzle(seed=s, difficulty=target, theme=theme)[2]["band"]
            for s in range(seeds)
        ]
        out[target] = {
            "exact": sum(b == target for b in bands),
            "of": seeds,
            "bands": bands,
        }
    return out


def main(argv=None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--theme", default="kings_guild")
    ap.add_argument("--seeds", type=int, default=30)
    ap.add_argument("--tiers", nargs="*", default=["normal", "hard", "mega", "giga", "tera"])
    ap.add_argument("--calibration", action="store_true", help="also run the exact-band sweep")
    args = ap.parse_args(argv)

    for tier in args.tiers:
        c = type_census(args.theme, tier, args.seeds)
        print(
            f"\n=== {args.theme} / {tier} — {c['puzzles']} puzzles, "
            f"avg {c['avg_clues']:.1f} clues, avg {c['avg_distinct']:.1f} distinct shapes, "
            f"group clues in {c['group_presence']:.0%} ==="
        )
        for sig, n in c["counts"].items():
            print(f"  {n:4d} clues | in {c['presence'][sig]:2d}/{c['puzzles']} puzzles | {sig}")

    if args.calibration:
        print("\n=== calibration (exact-band hits) ===")
        for target, r in calibration(args.theme, args.seeds, tuple(args.tiers)).items():
            print(f"  {target:6s} {r['exact']}/{r['of']}  {r['bands']}")


if __name__ == "__main__":
    main()
