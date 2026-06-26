"""Human-style deductive solver and difficulty grader.

Unlike `solver.count_solutions` (a brute-force backtracking counter that only
proves uniqueness), this solves a puzzle the way a person does: pure constraint
propagation, cheapest technique first, never guessing. It reports which
techniques were needed and how much work each did, which is the basis for an
*accurate* difficulty rating — and for the "solvable by logic alone" guarantee
(a puzzle this solver finishes has exactly one solution and needs no guessing).

Technique tiers (escalated only when cheaper ones are exhausted):
  0  givens          direct "is"/"is not"/neither/all-different facts
  1  line completion within a pairwise block, each item links exactly one other
  2  transitivity    combine blocks through a shared entity (the core move)
  3  clue propagation counting/matching clues: among / either-or / exactly-K /
                     group-match narrowing as the board fills in

The board state is the set of pairwise ✓/✗ facts a solver actually sees.
"""

from __future__ import annotations

from itertools import combinations

from .model import Theme

U, Y, N = 0, 1, 2  # unknown, linked (same entity), not linked


class Contradiction(Exception):
    """Raised if a deduction conflicts with a known fact (should never happen on
    a sound solver + valid puzzle)."""


class Board:
    """Pairwise relationship facts between every (category, item) pair."""

    def __init__(self, theme: Theme):
        self.n = theme.n
        self.k = theme.k
        # cell[(i, j)][a][b] for i < j: relation of item a (cat i) to item b (cat j)
        self.cell = {
            (i, j): [[U] * self.n for _ in range(self.n)]
            for i in range(self.k)
            for j in range(i + 1, self.k)
        }

    def get(self, ci, a, cj, b) -> int:
        if ci == cj:
            return Y if a == b else N  # same category: distinct items differ
        if ci < cj:
            return self.cell[(ci, cj)][a][b]
        return self.cell[(cj, ci)][b][a]

    def set(self, ci, a, cj, b, v) -> int:
        """Set a fact; return 1 if newly determined, 0 if already known."""
        cur = self.get(ci, a, cj, b)
        if cur == v:
            return 0
        if cur != U:
            raise Contradiction(f"({ci},{a})~({cj},{b}) is {cur}, cannot set {v}")
        if ci < cj:
            self.cell[(ci, cj)][a][b] = v
        else:
            self.cell[(cj, ci)][b][a] = v
        return 1

    def solved(self) -> bool:
        return all(U not in row for m in self.cell.values() for row in m)

    def copy(self) -> "Board":
        b = Board.__new__(Board)
        b.n, b.k = self.n, self.k
        b.cell = {key: [row[:] for row in m] for key, m in self.cell.items()}
        return b


def _g(board, p, q):
    return board.get(p[0], p[1], q[0], q[1])


def _s(board, p, q, v):
    return board.set(p[0], p[1], q[0], q[1], v)


# --- Tier 0: givens ---------------------------------------------------------
def _apply_givens(board, clues) -> int:
    changed = 0
    for clue in clues:
        name = type(clue).__name__
        if name == "Positive":
            changed += _s(board, clue.a, clue.b, Y)
        elif name == "Negative":
            changed += _s(board, clue.a, clue.b, N)
        elif name == "Neither":
            for o in clue.options:
                changed += _s(board, clue.anchor, o, N)
        elif name == "AllDifferent":
            for p, q in combinations(clue.terms, 2):
                if p[0] != q[0]:
                    changed += _s(board, p, q, N)
    return changed


# --- Tier 1: line completion within each pairwise block ---------------------
def _sweep_lines(board) -> int:
    changed = 0
    n = board.n
    for (i, j), m in board.cell.items():
        for a in range(n):
            for b in range(n):
                if m[a][b] == Y:  # a Y rules out the rest of its row + column
                    for b2 in range(n):
                        if b2 != b:
                            changed += board.set(i, a, j, b2, N)
                    for a2 in range(n):
                        if a2 != a:
                            changed += board.set(i, a2, j, b, N)
        for a in range(n):  # row with n-1 N's forces the remaining Y
            row = m[a]
            if row.count(N) == n - 1 and U in row:
                changed += board.set(i, a, j, row.index(U), Y)
        for b in range(n):  # same for columns
            col = [m[a][b] for a in range(n)]
            if col.count(N) == n - 1 and U in col:
                changed += board.set(i, col.index(U), j, b, Y)
    return changed


# --- Tier 2: transitivity through a pivot entity ----------------------------
def _sweep_transitivity(board) -> int:
    changed = 0
    n, k = board.n, board.k
    nodes = [(c, it) for c in range(k) for it in range(n)]
    for pivot in nodes:
        for q, r in combinations(nodes, 2):
            if q[0] == r[0]:
                continue  # same category — relation is structural
            pq = board.get(pivot[0], pivot[1], q[0], q[1])
            pr = board.get(pivot[0], pivot[1], r[0], r[1])
            if pq == Y and pr == Y:
                changed += _s(board, q, r, Y)
            elif (pq == Y and pr == N) or (pq == N and pr == Y):
                changed += _s(board, q, r, N)
    return changed


# --- Tier 3: counting / matching clue propagation ---------------------------
def _prop_among(board, clue) -> int:
    # at least `at_least` of the options share the anchor's entity
    not_n = [o for o in clue.options if _g(board, clue.anchor, o) != N]
    if len(not_n) == clue.at_least:  # only this many can be Y, and we need them
        return sum(_s(board, clue.anchor, o, Y) for o in not_n)
    return 0


def _prop_either(board, clue) -> int:
    states = [_g(board, clue.anchor, o) for o in clue.options]
    changed = 0
    if Y in states:  # exactly one — rule out the rest
        for o, s in zip(clue.options, states):
            if s != Y:
                changed += _s(board, clue.anchor, o, N)
    else:
        not_n = [o for o, s in zip(clue.options, states) if s != N]
        if len(not_n) == 1:
            changed += _s(board, clue.anchor, not_n[0], Y)
    return changed


def _prop_exactly(board, clue) -> int:
    states = [_g(board, p, q) for p, q in clue.links]
    unknown = [i for i, s in enumerate(states) if s == U]
    changed = 0
    if states.count(Y) == clue.k:  # quota met — rest are N
        for i in unknown:
            changed += _s(board, *clue.links[i], N)
    elif states.count(N) == len(clue.links) - clue.k:  # rest must be Y
        for i in unknown:
            changed += _s(board, *clue.links[i], Y)
    return changed


def _prop_group_match(board, clue) -> int:
    # left/right pair up by shared entity: a permutation over the match matrix
    left, right, changed = clue.left, clue.right, 0
    size = len(left)

    def line(get_cell, set_cell):
        nonlocal changed
        states = [get_cell(t) for t in range(size)]
        if Y in states:
            yj = states.index(Y)
            for t in range(size):
                if t != yj and states[t] == U:
                    changed += set_cell(t, N)
        elif states.count(N) == size - 1 and U in states:
            changed += set_cell(states.index(U), Y)

    for i in range(size):
        line(lambda j: _g(board, left[i], right[j]),
             lambda j, v: _s(board, left[i], right[j], v))
    for j in range(size):
        line(lambda i: _g(board, left[i], right[j]),
             lambda i, v: _s(board, left[i], right[j], v))
    return changed


# --- Sequential clues: bounds/arc-consistency on an ordered category's ranks --
# For ordered category p, a term's "rank" is the index of its price item (items
# are value-sorted ascending). poss(t) = ranks not yet ruled out for t.
def _poss(board, t, p):
    return [q for q in range(board.n) if board.get(t[0], t[1], p, q) != N]


def _rule_out(board, t, p, ranks):
    return sum(board.set(t[0], t[1], p, q, N) for q in ranks)


def _prop_greater(board, clue) -> int:  # rank(a) > rank(b)
    p = clue.cat
    pa, pb = _poss(board, clue.a, p), _poss(board, clue.b, p)
    if not pa or not pb:
        return 0
    changed = _rule_out(board, clue.a, p, [q for q in pa if q <= min(pb)])
    changed += _rule_out(board, clue.b, p, [q for q in pb if q >= max(pa)])
    return changed


def _prop_diff(board, clue) -> int:  # value(a) - value(b) == delta
    p, v, d = clue.cat, clue._values, clue.delta
    pa, pb = _poss(board, clue.a, p), _poss(board, clue.b, p)
    changed = _rule_out(board, clue.a, p, [qa for qa in pa if not any(v[qa] - v[qb] == d for qb in pb)])
    changed += _rule_out(board, clue.b, p, [qb for qb in pb if not any(v[qa] - v[qb] == d for qa in pa)])
    return changed


def _prop_between(board, clue) -> int:  # rank(c) strictly between rank(a), rank(b)
    p = clue.cat
    pa, pb, pc = _poss(board, clue.a, p), _poss(board, clue.b, p), _poss(board, clue.c, p)
    if not pa or not pb or not pc:
        return 0
    btw = lambda x, y, z: min(x, y) < z < max(x, y)
    changed = _rule_out(board, clue.c, p, [qc for qc in pc if not any(btw(qa, qb, qc) for qa in pa for qb in pb)])
    changed += _rule_out(board, clue.a, p, [qa for qa in pa if not any(btw(qa, qb, qc) for qb in pb for qc in pc)])
    changed += _rule_out(board, clue.b, p, [qb for qb in pb if not any(btw(qa, qb, qc) for qa in pa for qc in pc)])
    return changed


def _prop_adjacent(board, clue) -> int:  # rank(b) == rank(a) + 1
    p = clue.cat
    pa, pb = _poss(board, clue.a, p), _poss(board, clue.b, p)
    changed = _rule_out(board, clue.a, p, [qa for qa in pa if qa + 1 not in pb])
    changed += _rule_out(board, clue.b, p, [qb for qb in pb if qb - 1 not in pa])
    return changed


_PROPAGATORS = {
    "Among": _prop_among,
    "EitherOr": _prop_either,
    "ExactlyKLinks": _prop_exactly,
    "GroupMatch": _prop_group_match,
    "Greater": _prop_greater,
    "Diff": _prop_diff,
    "Between": _prop_between,
    "Adjacent": _prop_adjacent,
}


def _sweep_clues(board, clues) -> int:
    return sum(
        _PROPAGATORS[type(c).__name__](board, c)
        for c in clues
        if type(c).__name__ in _PROPAGATORS
    )


def _run_propagation(board, clues) -> None:
    """Tiers 1-3 to a fixpoint (givens are already on the board). Raises
    Contradiction if a forced fact conflicts."""
    while True:
        if _sweep_lines(board):
            continue
        if _sweep_transitivity(board):
            continue
        if _sweep_clues(board, clues):
            continue
        return


# --- Tier 4: hypothetical (proof by contradiction, single-step lookahead) ----
def _sweep_hypothetical(board, clues) -> int:
    """Assume an unknown cell's value; if propagation hits a contradiction, the
    other value is forced. Still pure logic — for a unique puzzle some such cell
    always exists once forward propagation stalls."""
    for (i, j), m in board.cell.items():
        for a in range(board.n):
            for b in range(board.n):
                if m[a][b] != U:
                    continue
                for trial, other in ((Y, N), (N, Y)):
                    test = board.copy()
                    test.set(i, a, j, b, trial)
                    try:
                        _run_propagation(test, clues)
                    except Contradiction:
                        board.set(i, a, j, b, other)
                        return 1
    return 0


def solve(theme: Theme, clues: list, allow_hypothetical: bool = True) -> dict:
    """Solve by pure deduction, cheapest technique first. Returns a report:
      solved, needs_guessing, ceiling (highest tier used), steps (per tier),
      total_steps, board.

    With allow_hypothetical, tier 4 (contradiction reasoning) is used when
    forward propagation stalls — so every unique puzzle solves with no guessing.
    """
    board = Board(theme)
    steps = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0}
    steps[0] = _apply_givens(board, clues)
    while not board.solved():
        c = _sweep_lines(board)
        if c:
            steps[1] += c
            continue
        c = _sweep_transitivity(board)
        if c:
            steps[2] += c
            continue
        c = _sweep_clues(board, clues)
        if c:
            steps[3] += c
            continue
        if allow_hypothetical:
            c = _sweep_hypothetical(board, clues)
            if c:
                steps[4] += c
                continue
        break  # stuck even with hypotheticals -> genuinely ambiguous
    solved = board.solved()
    used = [t for t, s in steps.items() if s]
    return {
        "solved": solved,
        "needs_guessing": not solved,
        "ceiling": max(used) if used else 0,
        "steps": steps,
        "total_steps": sum(steps.values()),
        "board": board,
    }


# Difficulty band by the hardest technique the solve required.
#   <=2  easy   (givens / line completion / transitivity only)
#     3  medium (needs counting/matching clue propagation)
#     4  hard   (needs at least one proof-by-contradiction step)
_BANDS = {0: "easy", 1: "easy", 2: "easy", 3: "medium", 4: "hard"}


def _score(r: dict) -> int:
    s = r["steps"]
    return r["ceiling"] * 1000 + s[4] * 50 + s[3] * 5 + s[2]


def grade(theme: Theme, clues: list) -> dict:
    """Difficulty report: band + ordinal score (ceiling dominates; ties broken by
    work at the top tiers).

    Fast path: forward propagation (tiers 0-3, no hypotheticals) classifies easy
    vs. medium cheaply. Only puzzles that stall there pay the tier-4 cost — and
    that confirms 'hard' (or 'ambiguous' if even tier 4 can't finish it).
    """
    cheap = solve(theme, clues, allow_hypothetical=False)
    if cheap["solved"]:
        cheap["band"] = _BANDS[cheap["ceiling"]]
        cheap["score"] = _score(cheap)
        return cheap
    full = solve(theme, clues, allow_hypothetical=True)
    full["band"] = "hard" if full["solved"] else "ambiguous"
    full["score"] = _score(full)
    return full


def is_logic_solvable(theme: Theme, clues: list) -> bool:
    """True iff the puzzle has a unique solution reachable by logic (no guessing)."""
    return solve(theme, clues)["solved"]


def board_solution(board: Board) -> list[list[int]]:
    """Read the anchored solution grid out of a fully solved board."""
    n, k = board.n, board.k
    X = [[0] * k for _ in range(n)]
    for e in range(n):
        X[e][0] = e
        for c in range(1, k):
            X[e][c] = next(b for b in range(n) if board.get(0, e, c, b) == Y)
    return X
