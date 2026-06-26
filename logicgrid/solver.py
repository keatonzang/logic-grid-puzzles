"""Backtracking solution counter.

Given a theme and a set of clues, count how many full solutions satisfy every
clue, stopping early once `cap` is reached. A clue set defines a valid puzzle
iff the count is exactly 1.

We assign one full category column at a time (each column is a permutation of
entities). After a column is placed we evaluate every clue whose involved
columns are now all assigned, pruning dead branches immediately. Columns that
appear in the most clues are assigned first so pruning bites early.
"""

from __future__ import annotations

import itertools

from .model import Theme


def count_solutions(theme: Theme, clues: list, cap: int = 2) -> int:
    n, k = theme.n, theme.k
    cols = list(range(1, k))  # column 0 is the fixed anchor (entity i -> item i)

    involve_count = {c: 0 for c in cols}
    for cl in clues:
        for c in cl.involved:
            if c in involve_count:
                involve_count[c] += 1
    order = sorted(cols, key=lambda c: involve_count[c], reverse=True)

    # For each step, precompute the clues that become fully checkable when that
    # step's column is added (i.e. the column completes the clue's dependencies).
    assigned = {0}
    steps = []  # (column, [clues to check])
    for c in order:
        assigned_after = assigned | {c}
        step_clues = [
            cl for cl in clues if c in cl.involved and cl.involved <= assigned_after
        ]
        steps.append((c, step_clues))
        assigned = assigned_after

    X = [[0] * k for _ in range(n)]
    for i in range(n):
        X[i][0] = i
    perms = list(itertools.permutations(range(n)))

    count = 0

    def rec(step: int) -> None:
        nonlocal count
        if count >= cap:
            return
        if step == len(steps):
            count += 1
            return
        c, step_clues = steps[step]
        for p in perms:
            for i in range(n):
                X[i][c] = p[i]
            if all(cl.holds(X) for cl in step_clues):
                rec(step + 1)
                if count >= cap:
                    return

    rec(0)
    return count


def is_unique(theme: Theme, clues: list) -> bool:
    return count_solutions(theme, clues, cap=2) == 1
