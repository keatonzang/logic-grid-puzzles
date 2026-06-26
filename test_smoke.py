#!/usr/bin/env python3
"""Smoke test: every generated puzzle must have a unique solution, and that
unique solution must be the one we generated from. Run: python test_smoke.py
"""

from __future__ import annotations

import random

from logicgrid import generate_puzzle, load_theme
from logicgrid.solver import count_solutions

THEMES = [
    "themes/morning_rush.yaml",
    "themes/detectives.yaml",
    "themes/space_colony.yaml",
]
SEEDS = range(25)


def main() -> int:
    failures = 0
    for theme_path in THEMES:
        theme = load_theme(theme_path)
        for seed in SEEDS:
            rng = random.Random(seed)
            puzzle = generate_puzzle(theme, rng)
            n_solutions = count_solutions(theme, puzzle.clues, cap=2)
            if n_solutions != 1:
                print(f"FAIL {theme_path} seed={seed}: {n_solutions} solutions")
                failures += 1
                continue
            # the generating solution must satisfy every clue
            X = puzzle.solution
            if not all(c.holds(X) for c in puzzle.clues):
                print(f"FAIL {theme_path} seed={seed}: generating solution violates a clue")
                failures += 1
        # report clue-count range for a feel of difficulty
        counts = [
            len(generate_puzzle(theme, random.Random(s)).clues) for s in range(10)
        ]
        print(
            f"OK  {theme_path}: clue counts over 10 seeds "
            f"min={min(counts)} max={max(counts)} avg={sum(counts)/len(counts):.1f}"
        )

    if failures:
        print(f"\n{failures} FAILURES")
        return 1
    print("\nAll puzzles unique and consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
