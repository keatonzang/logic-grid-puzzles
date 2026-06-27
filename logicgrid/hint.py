"""Step-by-step hint engine: the next single deduction, explained.

Where ``deduce.solve`` grades a puzzle (which techniques, how many steps), the
hint engine *narrates* the solve. It replays the very same tiers in the very same
order — givens, line elimination, transitivity, clue logic, contradiction — but
for every single-cell deduction it reconstructs a plain-English reason. The
reconstruction reuses the proven sweeps in ``deduce`` (run a sweep, diff the
board, explain what changed), so the hint path never re-implements the logic that
grading depends on — it only adds prose.

``next_hint`` then returns the first step the solver makes that the player hasn't
already got right, so a hint always moves them forward from wherever they are.
"""

from __future__ import annotations

from itertools import combinations

from .deduce import (
    N,
    U,
    Y,
    Board,
    _sweep_clues,
    _sweep_hypothetical,
    _sweep_lines,
    _sweep_transitivity,
    _PROPAGATORS,
)
from .model import Theme

# Friendly names for the deduction tiers, surfaced in the hint UI. The index is
# the tier number deduce.py uses (0 givens … 4 contradiction).
TIER_NAMES = {
    0: "Given",
    1: "Elimination",
    2: "Cross-reference",
    3: "Clue logic",
    4: "What-if",
}


def _label(theme: Theme, node) -> str:
    return theme.categories[node[0]].items[node[1]]


def _cat(theme: Theme, c: int) -> str:
    return theme.categories[c].name


def _changes(before: Board, after: Board):
    """Cells newly determined between two boards, as (i, j, a, b, value)."""
    out = []
    for (i, j), m in after.cell.items():
        bm = before.cell[(i, j)]
        for a in range(after.n):
            for b in range(after.n):
                if bm[a][b] == U and m[a][b] != U:
                    out.append((i, j, a, b, m[a][b]))
    return out


def _step(theme: Theme, i, j, a, b, value, tier, text) -> dict:
    """A single hint: which cell, what it becomes, and why."""
    return {
        "key": f"{i}-{j}",
        "a": a,
        "b": b,
        # client mark states: 1 = "=" (link), 2 = "×" (no link)
        "value": 1 if value == Y else 2,
        "link": value == Y,
        "tier": tier,
        "tier_name": TIER_NAMES[tier],
        "text": text,
    }


# --- Reason reconstruction --------------------------------------------------
def _reason_line(theme, before: Board, i, a, j, b, v) -> str:
    m = before.cell[(i, j)]
    if v == Y:  # forced because everything else in a row/column is ruled out
        if m[a].count(N) == before.n - 1:
            return (
                f"In {_cat(theme, i)} × {_cat(theme, j)}, {_label(theme, (i, a))} "
                f"must be {_label(theme, (j, b))} — every other {_cat(theme, j)} "
                f"is already crossed out for it."
            )
        return (
            f"In {_cat(theme, i)} × {_cat(theme, j)}, {_label(theme, (j, b))} "
            f"must be {_label(theme, (i, a))} — every other {_cat(theme, i)} "
            f"is already crossed out for it."
        )
    # v == N: there is an established link in the same row or column
    for b2 in range(before.n):
        if m[a][b2] == Y:
            return (
                f"{_label(theme, (i, a))} is {_label(theme, (j, b2))}, so it "
                f"can't also be {_label(theme, (j, b))}."
            )
    for a2 in range(before.n):
        if m[a2][b] == Y:
            return (
                f"{_label(theme, (j, b))} is {_label(theme, (i, a2))}, so "
                f"{_label(theme, (i, a))} can't be {_label(theme, (j, b))}."
            )
    return f"{_label(theme, (i, a))} can't be {_label(theme, (j, b))}."


def _reason_trans(theme, before: Board, i, a, j, b, v) -> str:
    p, q = (i, a), (j, b)
    nodes = [(c, it) for c in range(before.k) for it in range(before.n)]
    for r in nodes:
        if r == p or r == q:
            continue
        rp = before.get(p[0], p[1], r[0], r[1])
        rq = before.get(q[0], q[1], r[0], r[1])
        if rp == U or rq == U:
            continue
        if v == Y and rp == Y and rq == Y:
            return (
                f"{_label(theme, p)} is {_label(theme, r)}, and {_label(theme, q)} "
                f"is {_label(theme, r)}, so {_label(theme, p)} is {_label(theme, q)}."
            )
        if v == N and rp == Y and rq == N:
            return (
                f"{_label(theme, p)} is {_label(theme, r)}, but {_label(theme, q)} "
                f"isn't, so {_label(theme, p)} isn't {_label(theme, q)}."
            )
        if v == N and rp == N and rq == Y:
            return (
                f"{_label(theme, q)} is {_label(theme, r)}, but {_label(theme, p)} "
                f"isn't, so {_label(theme, p)} isn't {_label(theme, q)}."
            )
    link = "is" if v == Y else "isn't"
    return f"Cross-referencing the established links, {_label(theme, p)} {link} {_label(theme, q)}."


def _reason_clue(theme, clue, i, a, j, b, v) -> str:
    rel = "must be" if v == Y else "can't be"
    return (
        f"From the clue “{clue.text(theme)}” — "
        f"{_label(theme, (i, a))} {rel} {_label(theme, (j, b))}."
    )


def _reason_hyp(theme, i, a, j, b, v) -> str:
    if v == N:
        return (
            f"Suppose {_label(theme, (i, a))} were {_label(theme, (j, b))} — "
            f"following the clues from there hits a contradiction, so it isn't."
        )
    return (
        f"Suppose {_label(theme, (i, a))} were not {_label(theme, (j, b))} — "
        f"that hits a contradiction, so it must be."
    )


# --- Tier 0 (givens) --------------------------------------------------------
def _givens(board: Board, clues, theme, steps) -> None:
    """Apply direct facts, one explained step per newly determined cell."""

    def place(p, q, v, clue):
        before = board.copy()
        if board.set(p[0], p[1], q[0], q[1], v):
            for (i, j, a, b, val) in _changes(before, board):
                steps.append(_step(theme, i, j, a, b, val, 0, _reason_clue(theme, clue, i, a, j, b, val)))

    for clue in clues:
        name = type(clue).__name__
        if name == "Positive":
            place(clue.a, clue.b, Y, clue)
        elif name == "Negative":
            place(clue.a, clue.b, N, clue)
        elif name == "Neither":
            for o in clue.options:
                place(clue.anchor, o, N, clue)
        elif name == "AllDifferent":
            for p, q in combinations(clue.terms, 2):
                if p[0] != q[0]:
                    place(p, q, N, clue)


# --- Tiers 1-4: run the proven sweep, diff, explain -------------------------
def _round_lines(board, clues, theme, steps) -> bool:
    before = board.copy()
    if not _sweep_lines(board):
        return False
    for (i, j, a, b, v) in _changes(before, board):
        steps.append(_step(theme, i, j, a, b, v, 1, _reason_line(theme, before, i, a, j, b, v)))
    return True


def _round_trans(board, clues, theme, steps) -> bool:
    before = board.copy()
    if not _sweep_transitivity(board):
        return False
    for (i, j, a, b, v) in _changes(before, board):
        steps.append(_step(theme, i, j, a, b, v, 2, _reason_trans(theme, before, i, a, j, b, v)))
    return True


def _round_clues(board, clues, theme, steps) -> bool:
    # Run clues one at a time so each deduction can name the clue that drove it.
    for clue in clues:
        if type(clue).__name__ not in _PROPAGATORS:
            continue
        before = board.copy()
        if _PROPAGATORS[type(clue).__name__](board, clue):
            for (i, j, a, b, v) in _changes(before, board):
                steps.append(_step(theme, i, j, a, b, v, 3, _reason_clue(theme, clue, i, a, j, b, v)))
            return True
    return False


def _round_hyp(board, clues, theme, steps) -> bool:
    before = board.copy()
    if not _sweep_hypothetical(board, clues, 1):
        return False
    for (i, j, a, b, v) in _changes(before, board):
        steps.append(_step(theme, i, j, a, b, v, 4, _reason_hyp(theme, i, a, j, b, v)))
    return True


def trace(theme: Theme, clues: list) -> list[dict]:
    """The full ordered list of explained deductions that solve the puzzle.

    Mirrors ``deduce.solve``'s cheapest-tier-first escalation, so the narration
    matches how the puzzle is graded. Stops if no tier makes progress (a puzzle
    needing deeper nesting than tier 4 — skipped at generation anyway).
    """
    board = Board(theme)
    steps: list[dict] = []
    _givens(board, clues, theme, steps)
    rounds = (_round_lines, _round_trans, _round_clues, _round_hyp)
    while not board.solved():
        if not any(r(board, clues, theme, steps) for r in rounds):
            break
    return steps


def next_hint(theme: Theme, clues: list, known: dict | None = None) -> dict:
    """The first deduction the player hasn't already made correctly.

    ``known`` is the player's current board: ``{"i-j": [[0/1/2, …], …]}`` using
    the same 0 blank / 1 link / 2 no-link encoding as a hint's ``value``. A step
    whose cell the player already has set to the right value is skipped. Returns
    ``{"done": True}`` once nothing new remains.
    """
    known = known or {}
    for step in trace(theme, clues):
        cur = known.get(step["key"])
        if cur is not None:
            try:
                if cur[step["a"]][step["b"]] == step["value"]:
                    continue
            except (IndexError, TypeError):
                pass
        return step
    return {"done": True}
