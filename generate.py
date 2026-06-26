#!/usr/bin/env python3
"""CLI: generate a logic-grid puzzle from a theme file.

Examples:
    python generate.py themes/detectives.yaml
    python generate.py themes/space_colony.yaml --seed 7 --show-solution
    python generate.py themes/detectives.yaml --no-grid
"""

from __future__ import annotations

import argparse
import random
import sys

from logicgrid import generate_puzzle, load_theme, render_puzzle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a logic-grid puzzle from a theme.")
    parser.add_argument("theme", help="path to a theme file (.yaml or .json)")
    parser.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible puzzles")
    parser.add_argument("--show-solution", action="store_true", help="print the answer key too")
    parser.add_argument("--no-grid", dest="grid", action="store_false", help="omit the pairwise grids")
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    theme = load_theme(args.theme)
    puzzle = generate_puzzle(theme, rng)
    print(render_puzzle(puzzle, show_solution=args.show_solution, grid=args.grid))
    return 0


if __name__ == "__main__":
    sys.exit(main())
