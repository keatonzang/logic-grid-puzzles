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
  3  clue propagation the everyday clue moves: among / either-or / exactly-K /
                     conditionals / group-membership narrowing / simple rank bounds
  4  advanced logic  the expert forward moves: grid set logic (cross-elimination,
                     naked subsets, difference chaining) plus the heavy counting
                     propagators (set counts, cross-group counts/comparisons,
                     group ordering, between / distance pinches) — see _EXPERT_CLUES
  5  what-if         proof by contradiction (assume, propagate, refute)
  6  nested what-if  a what-if whose inner reasoning itself needs a what-if

The board state is the set of pairwise ✓/✗ facts a solver actually sees.

What this module guarantees vs merely models: uniqueness and logic-solvability
are verified per shipped puzzle; the difficulty numbers are structural
measurements with known edges (policy-dependent what-if counts, refutation-only
reasoning, sound-but-partial propagation, budgeted tera recovery and
minimization, no human solve-time anchoring). The full list lives in README
under "What's verified — and what's only modeled".
"""

from __future__ import annotations

import math
import time
from itertools import combinations

from .model import Contradiction, Theme

U, Y, N = 0, 1, 2  # unknown, linked (same entity), not linked

__all__ = ["Contradiction"]  # re-exported: defined in model, caught/raised here


class SolveBudgetExceeded(Exception):
    """A solve hit its wall-clock budget before finishing — distinct from
    Contradiction (which means *refuted*). Used to bound the depth-2 Tera-recovery
    solve: a puzzle that needs depth-3 reasoning makes the exhaustive depth-2 scan
    churn for tens of seconds to prove no depth-2 refutation exists, so the
    recovery passes a deadline and treats this as 'too deep to verify -> skip'."""


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
            raise Contradiction(
                f"({ci},{a})~({cj},{b}) is {cur}, cannot set {v}",
                conflict=(ci, a, cj, b, cur, v),
            )
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
            cnt = row.count(N)
            if cnt == n:  # every option ruled out — a dead line is a refutation
                raise Contradiction(f"({i},{a}) has no possible {j}-item left")
            if cnt == n - 1 and U in row:
                changed += board.set(i, a, j, row.index(U), Y)
        for b in range(n):  # same for columns
            col = [m[a][b] for a in range(n)]
            cnt = col.count(N)
            if cnt == n:
                raise Contradiction(f"({j},{b}) has no possible {i}-item left")
            if cnt == n - 1 and U in col:
                changed += board.set(i, col.index(U), j, b, Y)
    return changed


# --- Tier 2: transitivity through a pivot entity ----------------------------
def _sweep_transitivity(board) -> int:
    changed = 0
    n, k = board.n, board.k
    nodes = [(c, it) for c in range(k) for it in range(n)]
    for pivot in nodes:
        pc, pi = pivot
        # bucket the other nodes by their relation to the pivot — only Y/N
        # buckets produce deductions, so skip the (large) unknown set entirely.
        ys, ns = [], []
        for q in nodes:
            if q == pivot:
                continue
            r = board.get(pc, pi, q[0], q[1])
            if r == Y:
                ys.append(q)
            elif r == N:
                ns.append(q)
        for a in range(len(ys)):  # same entity as pivot => same as each other
            qa = ys[a]
            for b in range(a + 1, len(ys)):
                if qa[0] != ys[b][0]:
                    changed += _s(board, qa, ys[b], Y)
        for qy in ys:  # pivot's entity vs a different entity => different
            for qn in ns:
                if qy[0] != qn[0]:
                    changed += _s(board, qy, qn, N)
    return changed


# --- Grid set logic (half of tier 4): cross-elimination & naked subsets ------
# Intermediate grid-only tactics — reached before resorting to trial-and-error,
# but which line completion and transitivity cannot express because there is no
# single established link to pivot through:
#   * cross-elimination: two items whose candidate item-sets in some bridge
#     category are DISJOINT cannot be the same entity — they could never agree on
#     that category, so mark them apart.
#   * naked subsets: k items in one category that confine their candidates in a
#     bridge category to the same k items use those items up between them, so
#     every OTHER item is excluded from all k.
# Both are sound entailments under the per-category bijection. Crucially they let
# the solver make deductions it would otherwise reach only by a what-if, so
# running them before tier 4 pulls many puzzles down out of the contradiction tier.
def _cands(board, c, it, m):
    """Items of category m that node (c, it) could still be linked to."""
    return frozenset(t for t in range(board.n) if board.get(c, it, m, t) != N)


def _sweep_cross_elim(board) -> int:
    changed = 0
    n, k = board.n, board.k
    nodes = [(c, it) for c in range(k) for it in range(n)]
    cand = {p: {m: _cands(board, p[0], p[1], m) for m in range(k) if m != p[0]} for p in nodes}
    for x in range(len(nodes)):
        i, a = nodes[x]
        for y in range(x + 1, len(nodes)):
            j, b = nodes[y]
            if i == j or board.get(i, a, j, b) != U:
                continue
            for m in range(k):  # a bridge category where their options can't overlap
                if m == i or m == j:
                    continue
                if cand[(i, a)][m].isdisjoint(cand[(j, b)][m]):
                    changed += board.set(i, a, j, b, N)
                    break
    return changed


def _naked_dir(board, i, m, cand, row) -> int:
    """One direction of naked-subset elimination in block (i, m). ``cand`` maps
    each line index to the cross indices it can still take. A set S of lines whose
    candidate UNION is exactly |S| indices owns them — clear those from every
    other line. ``row`` picks which axis the lines are (category i vs category m)."""
    n = board.n
    changed = 0
    lines = [L for L, s in cand.items() if 1 < len(s) < n]  # singles=tier1, full=no info
    for size in (2, 3):
        if size > n - 2:
            break
        for combo in combinations(lines, size):
            union = frozenset().union(*(cand[L] for L in combo))
            if len(union) != size:
                continue
            owners = set(combo)
            for other in range(n):
                if other in owners:
                    continue
                for t in union:
                    if row:
                        changed += board.set(i, other, m, t, N)
                    else:
                        changed += board.set(i, t, m, other, N)
    return changed


def _sweep_naked(board) -> int:
    changed = 0
    n, k = board.n, board.k
    for i in range(k):
        for m in range(k):
            if m == i:
                continue
            rcand = {a: _cands(board, i, a, m) for a in range(n)}
            changed += _naked_dir(board, i, m, rcand, row=True)
            ccand = {t: frozenset(a for a in range(n) if board.get(i, a, m, t) != N)
                     for t in range(n)}
            changed += _naked_dir(board, i, m, ccand, row=False)
    return changed


def _diff_components(clues):
    """Per ordered category, the exact-difference (Diff) clues form a graph whose
    edges pin value gaps between entity terms. Returns, for each component, a dict
    mapping each term to its value-offset within that component — so two terms with
    equal offset share a value (same entity) and unequal offsets differ. Yields
    (cat, offset_map) per connected component."""
    from collections import defaultdict
    by_cat = defaultdict(list)
    for c in clues:
        if type(c).__name__ == "Diff":
            by_cat[c.cat].append(c)
    for cat, diffs in by_cat.items():
        adj = defaultdict(list)
        for d in diffs:
            adj[d.a].append((d.b, d.delta))   # value(a) = value(b) + delta
            adj[d.b].append((d.a, -d.delta))
        seen = set()
        for start in list(adj):
            if start in seen:
                continue
            off = {start: 0}
            stack = [start]
            while stack:
                u = stack.pop()
                for v, w in adj[u]:
                    if v not in off:
                        off[v] = off[u] - w   # value(v) = value(u) - w
                        stack.append(v)
            seen |= set(off)
            yield cat, off


def _sweep_comparative(board, clues) -> int:
    """Combine exact-difference clues that share an entity: terms pinned to the
    same value-offset from a shared reference must be the same entity (each value
    is unique under the bijection), and terms at different offsets must differ.
    The order-based comparative case (items on opposite sides of a shared item)
    already falls out of cross-elimination once the comparison propagators narrow
    the value ranges, so this layer adds the exact-difference equalities those
    can't — the only tactic here that yields a positive ✓."""
    changed = 0
    for _cat, off in _diff_components(clues):
        terms = list(off)
        for x in range(len(terms)):
            for y in range(x + 1, len(terms)):
                ta, tb = terms[x], terms[y]
                if ta[0] == tb[0]:
                    continue  # same category: their relation is already fixed
                want = Y if off[ta] == off[tb] else N
                if board.get(ta[0], ta[1], tb[0], tb[1]) != want:
                    changed += board.set(ta[0], ta[1], tb[0], tb[1], want)
    return changed


def _sweep_set_logic(board, clues) -> int:
    """Tier 4: the intermediate tactics beyond clue propagation — grid set logic
    (cross-elimination, naked subsets) plus exact-difference comparison chaining,
    cheapest-first within the tier."""
    return _sweep_cross_elim(board) or _sweep_naked(board) or _sweep_comparative(board, clues)


# --- Tier 3: counting / matching clue propagation ---------------------------
def _prop_among(board, clue) -> int:
    # at least `at_least` of the options share the anchor's entity
    not_n = [o for o in clue.options if _g(board, clue.anchor, o) != N]
    if len(not_n) < clue.at_least:  # fewer live options than the minimum
        raise Contradiction("among can't reach its minimum")
    if len(not_n) == clue.at_least:  # only this many can be Y, and we need them
        return sum(_s(board, clue.anchor, o, Y) for o in not_n)
    return 0


def _prop_either(board, clue) -> int:
    states = [_g(board, clue.anchor, o) for o in clue.options]
    changed = 0
    if states.count(Y) > 1:  # exactly one may hold
        raise Contradiction("either-or has two confirmed options")
    if Y in states:  # exactly one — rule out the rest
        for o, s in zip(clue.options, states):
            if s != Y:
                changed += _s(board, clue.anchor, o, N)
    else:
        not_n = [o for o, s in zip(clue.options, states) if s != N]
        if not not_n:  # every option ruled out, but exactly one must hold
            raise Contradiction("either-or has no live option left")
        if len(not_n) == 1:
            changed += _s(board, clue.anchor, not_n[0], Y)
    return changed


def _prop_exactly(board, clue) -> int:
    states = [_g(board, p, q) for p, q in clue.links]
    unknown = [i for i, s in enumerate(states) if s == U]
    changed = 0
    if states.count(Y) > clue.k:
        raise Contradiction("exactly-K links exceed the quota")
    if states.count(N) > len(clue.links) - clue.k:
        raise Contradiction("exactly-K links can't reach the quota")
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
        if states.count(N) == size:  # a term with no partner left — refuted
            raise Contradiction("group-match term has no partner left")
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


def _prop_at_least_apart(board, clue) -> int:  # value(a) - value(b) >= delta
    p, v, d = clue.cat, clue._values, clue.delta
    pa, pb = _poss(board, clue.a, p), _poss(board, clue.b, p)
    if not pa or not pb:
        return 0
    min_b, max_a = min(v[q] for q in pb), max(v[q] for q in pa)
    changed = _rule_out(board, clue.a, p, [q for q in pa if v[q] < min_b + d])
    changed += _rule_out(board, clue.b, p, [q for q in pb if v[q] > max_a - d])
    return changed


def _prop_next_to(board, clue) -> int:  # |rank(a) - rank(b)| == 1
    p = clue.cat
    pa, pb = _poss(board, clue.a, p), _poss(board, clue.b, p)
    if not pa or not pb:
        return 0
    changed = _rule_out(board, clue.a, p, [qa for qa in pa if qa - 1 not in pb and qa + 1 not in pb])
    changed += _rule_out(board, clue.b, p, [qb for qb in pb if qb - 1 not in pa and qb + 1 not in pa])
    return changed


def _prop_abs_apart(board, clue) -> int:  # |value(a) - value(b)| >= / <= delta
    p, v, d = clue.cat, clue._values, clue.delta
    pa, pb = _poss(board, clue.a, p), _poss(board, clue.b, p)
    if not pa or not pb:
        return 0
    if clue.at_least:
        has_partner = lambda x, ys: any(abs(v[x] - v[y]) >= d for y in ys)
    else:
        has_partner = lambda x, ys: any(abs(v[x] - v[y]) <= d for y in ys)
    changed = _rule_out(board, clue.a, p, [qa for qa in pa if not has_partner(qa, pb)])
    changed += _rule_out(board, clue.b, p, [qb for qb in pb if not has_partner(qb, pa)])
    return changed


def _prop_multi_compare(board, clue) -> int:  # rank(c) >/< every other
    p, changed = clue.cat, 0
    for o in clue.others:
        pc, po = _poss(board, clue.c, p), _poss(board, o, p)
        if not pc or not po:
            continue
        if clue.greater:  # c > o
            changed += _rule_out(board, clue.c, p, [q for q in pc if q <= min(po)])
            changed += _rule_out(board, o, p, [q for q in po if q >= max(pc)])
        else:  # c < o
            changed += _rule_out(board, clue.c, p, [q for q in pc if q >= max(po)])
            changed += _rule_out(board, o, p, [q for q in po if q <= min(pc)])
    return changed


def _prop_at_most(board, clue) -> int:  # at most k options match the anchor
    states = [_g(board, clue.anchor, o) for o in clue.options]
    if states.count(Y) > clue.k:
        raise Contradiction("at-most quota exceeded")
    if states.count(Y) != clue.k:
        return 0
    changed = 0  # quota reached -> the rest can't match
    for o, s in zip(clue.options, states):
        if s == U:
            changed += _s(board, clue.anchor, o, N)
    return changed


def _prop_exactly_anchor(board, clue) -> int:  # exactly k options match the anchor
    states = [_g(board, clue.anchor, o) for o in clue.options]
    changed = 0
    if states.count(Y) > clue.k:
        raise Contradiction("exactly-K quota exceeded")
    if states.count(Y) == clue.k:  # quota met -> the rest can't match
        for o, s in zip(clue.options, states):
            if s == U:
                changed += _s(board, clue.anchor, o, N)
    not_n = [o for o, s in zip(clue.options, states) if s != N]
    if len(not_n) < clue.k:  # fewer live options than the quota needs
        raise Contradiction("exactly-K can't reach the quota")
    if len(not_n) == clue.k:  # only this many can match, and we need k -> all Y
        for o in not_n:
            changed += _s(board, clue.anchor, o, Y)
    return changed


def _prop_conditional(board, clue) -> int:  # general if-then / iff over Statements
    # The whole three-valued evaluation + constraint push lives on the embedded
    # Statement tree (clues.py), so this stays a thin, structure-agnostic shim and
    # arbitrarily nested antecedents/consequents propagate by the same rules.
    return clue.propagate(board)


# --- Hierarchy / group clues (resolve on the grouped category's column) ------
def _poss_groups(board, term, cat, partition):
    """Group indices still possible for `term` — a group where at least one of its
    items isn't yet ruled out for term's entity."""
    return {
        gi
        for gi, members in enumerate(partition)
        if any(_g(board, term, (cat, x)) != N for x in members)
    }


def _prop_in_group(board, clue) -> int:  # entity's grouped item must be in the group
    members = set(clue.members)
    return sum(
        _s(board, clue.anchor, (clue.cat, x), N)
        for x in range(board.n)
        if x not in members
    )


def _prop_same_group(board, clue) -> int:  # a and b fall in the same group
    cat, part = clue.cat, clue.partition
    shared = _poss_groups(board, clue.a, cat, part) & _poss_groups(board, clue.b, cat, part)
    changed = 0
    for gi, members in enumerate(part):  # neither may sit in a group the other can't
        if gi not in shared:
            for x in members:
                changed += _s(board, clue.a, (cat, x), N)
                changed += _s(board, clue.b, (cat, x), N)
    return changed


def _prop_diff_group(board, clue) -> int:  # a and b fall in different groups
    cat, part = clue.cat, clue.partition
    changed = 0
    for t, other in ((clue.a, clue.b), (clue.b, clue.a)):
        poss = _poss_groups(board, t, cat, part)
        if len(poss) == 1:  # t's group is pinned -> other can't be in it
            (gi,) = tuple(poss)
            for x in part[gi]:
                changed += _s(board, other, (cat, x), N)
    return changed


def _prop_not_in_group(board, clue) -> int:  # entity's grouped item is NOT in the group
    return sum(_s(board, clue.anchor, (clue.cat, x), N) for x in clue.members)


def _anchor_group_status(board, anchor, cat, members):
    """Whether `anchor`'s entity is definitely in the group, definitely out, or
    still unknown — read off the grouped column. "In" if a member item is already
    linked (Y) or every non-member is ruled out; "out" symmetrically."""
    mset = set(members)
    items = range(board.n)
    member_y = any(_g(board, anchor, (cat, x)) == Y for x in items if x in mset)
    member_poss = any(_g(board, anchor, (cat, x)) != N for x in items if x in mset)
    non_y = any(_g(board, anchor, (cat, x)) == Y for x in items if x not in mset)
    non_poss = any(_g(board, anchor, (cat, x)) != N for x in items if x not in mset)
    if member_y or not non_poss:
        return "in"
    if non_y or not member_poss:
        return "out"
    return "unknown"


def _prop_group_count(board, clue) -> int:  # how many anchors fall in the group: >=/<=/== k
    cat, members = clue.cat, set(clue.members)
    nonmembers = [x for x in range(board.n) if x not in members]
    status = [_anchor_group_status(board, a, cat, members) for a in clue.anchors]
    lo = status.count("in")  # definitely in
    unknown = [i for i, s in enumerate(status) if s == "unknown"]
    hi = lo + len(unknown)  # most that could be in
    k, mode = clue.k, clue.mode
    if mode in ("atleast", "exactly") and hi < k:
        raise Contradiction("group-count can't reach the minimum")
    if mode in ("atmost", "exactly") and lo > k:
        raise Contradiction("group-count exceeds the maximum")
    changed = 0
    if mode in ("atleast", "exactly") and hi == k:  # every undecided anchor must be IN
        for i in unknown:
            for x in nonmembers:
                changed += _s(board, clue.anchors[i], (cat, x), N)
    if mode in ("atmost", "exactly") and lo == k:  # quota met -> undecided anchors are OUT
        for i in unknown:
            for x in members:
                changed += _s(board, clue.anchors[i], (cat, x), N)
    return changed


# --- General set-composition cardinality (SetCount) -------------------------
def _set_subject_cells(clue):
    """The (cat, item) cells whose link to an entity's subject row witnesses that
    the entity is in the subject union (flattened across selectors)."""
    cells = []
    for sub in clue.subjects:
        if sub[0] == "entity":
            cells.append(sub[1])
        else:  # ("group", cat, members, label)
            cells.extend((sub[1], m) for m in sub[2])
    return cells


def _row_or(board, e, cells):
    """Three-valued OR over `cells` read from subject row `e`: is entity `e` linked
    to at least one of them? Y if any link, N if all ruled out, else U."""
    vals = [board.get(0, e, c, i) for c, i in cells]
    if Y in vals:
        return Y
    return N if all(v == N for v in vals) else U


def _row_or_force_true(board, e, cells):  # the OR must hold: unit-propagate the last open disjunct
    vals = [board.get(0, e, c, i) for c, i in cells]
    if Y in vals:
        return 0
    open_ = [(c, i) for (c, i), v in zip(cells, vals) if v == U]
    if len(open_) == 1:
        c, i = open_[0]
        return _s(board, (0, e), (c, i), Y)
    return 0


def _row_or_force_false(board, e, cells):  # the OR must fail: every disjunct ruled out
    return sum(_s(board, (0, e), (c, i), N) for c, i in cells if board.get(0, e, c, i) != N)


def _prop_set_count(board, clue) -> int:
    """Cardinality over a union of set instances (see clues.SetCount). Sound but
    partial: bound-check the count of contributing entities, and once the count is
    forced to its limit, push the determinate side of each undecided entity's
    (in-subject AND hits-target) conjunction."""
    subj_cells = _set_subject_cells(clue)
    tgt_cells = list(clue.target_cells)
    k, mode = clue.k, clue.mode

    in_s = [_row_or(board, e, subj_cells) for e in range(board.n)]
    sat = [_row_or(board, e, tgt_cells) for e in range(board.n)]
    contrib = [
        N if (in_s[e] == N or sat[e] == N) else (Y if in_s[e] == Y and sat[e] == Y else U)
        for e in range(board.n)
    ]
    must = contrib.count(Y)
    can = must + contrib.count(U)
    if mode in ("atleast", "exactly") and can < k:
        raise Contradiction("set-count can't reach the minimum")
    if mode in ("atmost", "exactly") and must > k:
        raise Contradiction("set-count exceeds the maximum")

    force_true = mode in ("atleast", "exactly") and can == k   # every maybe must contribute
    force_false = mode in ("atmost", "exactly") and must == k   # quota met -> no more may
    if not (force_true or force_false):
        return 0
    changed = 0
    for e in range(board.n):
        if contrib[e] != U:
            continue
        if force_true:  # need in-subject AND hits-target -> drive both ORs true
            changed += _row_or_force_true(board, e, subj_cells)
            changed += _row_or_force_true(board, e, tgt_cells)
        else:  # force_false: kill the conjunction via whichever side the other pins
            if in_s[e] == Y:
                changed += _row_or_force_false(board, e, tgt_cells)
            elif sat[e] == Y:
                changed += _row_or_force_false(board, e, subj_cells)
    return changed


def _prop_group_order(board, clue) -> int:  # every `higher`-guild entity outranks every `lower` one
    g, o = clue.gcat, clue.ocat
    hi, lo = clue.higher, clue.lower
    n = board.n
    changed = 0
    # Count bound: all |lo| lower-guild entities rank below all higher-guild ones,
    # so every higher trade sits at rank >= |lo|, and every lower trade at <= n-1-|hi|.
    floor, ceil = len(lo), n - 1 - len(hi)
    for t in hi:
        for r in range(floor):
            changed += _s(board, (g, t), (o, r), N)
    for t in lo:
        for r in range(ceil + 1, n):
            changed += _s(board, (g, t), (o, r), N)
    # Tighten off any pinned rank: a lower trade fixed at rank r pushes every
    # higher trade above r, and a higher trade fixed at r pushes every lower below r.
    for t2 in lo:
        for r in range(n):
            if _g(board, (g, t2), (o, r)) == Y:
                for t1 in hi:
                    for rr in range(r + 1):
                        changed += _s(board, (g, t1), (o, rr), N)
    for t1 in hi:
        for r in range(n):
            if _g(board, (g, t1), (o, r)) == Y:
                for t2 in lo:
                    for rr in range(r, n):
                        changed += _s(board, (g, t2), (o, rr), N)
    return changed


# --- Cross-group clues (two hierarchies) ------------------------------------
# Entities are addressed through the subject column (category 0); membership in a
# group is read with _anchor_group_status on the (0, e) anchor.
def _force_into(board, e, cat, members) -> int:
    return sum(_s(board, (0, e), (cat, x), N) for x in range(board.n) if x not in set(members))


def _prop_group_group_count(board, clue) -> int:  # |A∩B| across the two hierarchies vs k
    n = board.n
    c1, c2 = clue.cat1, clue.cat2
    A, B = clue.membersA, clue.membersB
    sa = [_anchor_group_status(board, (0, e), c1, A) for e in range(n)]
    sb = [_anchor_group_status(board, (0, e), c2, B) for e in range(n)]
    both_in = [e for e in range(n) if sa[e] == "in" and sb[e] == "in"]
    poss = [e for e in range(n) if sa[e] != "out" and sb[e] != "out"]  # could be in both
    lo, hi = len(both_in), len(poss)
    k, mode = clue.k, clue.mode
    if mode in ("atleast", "exactly") and hi < k:
        raise Contradiction("cross-group count can't reach the minimum")
    if mode in ("atmost", "exactly") and lo > k:
        raise Contradiction("cross-group count exceeds the maximum")
    changed = 0
    if mode in ("atleast", "exactly") and hi == k:  # every candidate must be in both
        for e in poss:
            changed += _force_into(board, e, c1, A) + _force_into(board, e, c2, B)
    if mode in ("atmost", "exactly") and lo == k:  # quota met -> the rest out of A∩B
        for e in range(n):
            if e in both_in:
                continue
            if sa[e] == "in":  # in A -> must be out of B
                changed += sum(_s(board, (0, e), (c2, x), N) for x in B)
            elif sb[e] == "in":  # in B -> must be out of A
                changed += sum(_s(board, (0, e), (c1, x), N) for x in A)
    return changed


def _prop_group_group_compare(board, clue) -> int:  # |A∩C| > |B∩C|
    n = board.n
    c1, c2 = clue.cat1, clue.cat2
    A, B, C = clue.membersA, clue.membersB, clue.membersC
    sc = [_anchor_group_status(board, (0, e), c2, C) for e in range(n)]
    sa = [_anchor_group_status(board, (0, e), c1, A) for e in range(n)]
    sb = [_anchor_group_status(board, (0, e), c1, B) for e in range(n)]
    a_lo = sum(1 for e in range(n) if sa[e] == "in" and sc[e] == "in")
    a_hi = sum(1 for e in range(n) if sa[e] != "out" and sc[e] != "out")
    b_lo = sum(1 for e in range(n) if sb[e] == "in" and sc[e] == "in")
    b_hi = sum(1 for e in range(n) if sb[e] != "out" and sc[e] != "out")
    if a_hi <= b_lo:  # the most A can be still can't beat the least B
        raise Contradiction("cross-group comparison impossible")
    changed = 0
    if a_hi == b_lo + 1:  # tight: A must hit its max and B its min
        for e in range(n):  # force every candidate into A∩C
            if sa[e] != "out" and sc[e] != "out" and not (sa[e] == "in" and sc[e] == "in"):
                changed += _force_into(board, e, c1, A) + _force_into(board, e, c2, C)
        for e in range(n):  # keep B∩C down to its definite members
            if sb[e] == "in" and sc[e] == "in":
                continue
            if sb[e] == "in" and sc[e] != "out":  # in B -> must be out of C
                changed += sum(_s(board, (0, e), (c2, x), N) for x in C)
            elif sc[e] == "in" and sb[e] != "out":  # in C -> must be out of B
                changed += sum(_s(board, (0, e), (c1, x), N) for x in B)
    return changed


_PROPAGATORS = {
    "Among": _prop_among,
    "EitherOr": _prop_either,
    "Exactly": _prop_exactly_anchor,
    "ExactlyKLinks": _prop_exactly,
    "Conditional": _prop_conditional,
    "Compound": _prop_conditional,  # both just delegate to the statement tree
    "InGroup": _prop_in_group,
    "SameGroup": _prop_same_group,
    "DiffGroup": _prop_diff_group,
    "NotInGroup": _prop_not_in_group,
    "GroupCount": _prop_group_count,
    "SetCount": _prop_set_count,
    "GroupOrder": _prop_group_order,
    "GroupGroupCount": _prop_group_group_count,
    "GroupGroupCompare": _prop_group_group_compare,
    "GroupMatch": _prop_group_match,
    "Greater": _prop_greater,
    "Diff": _prop_diff,
    "Between": _prop_between,
    "Adjacent": _prop_adjacent,
    "NextTo": _prop_next_to,
    "AtLeastApart": _prop_at_least_apart,
    "AbsApart": _prop_abs_apart,
    "MultiCompare": _prop_multi_compare,
    "AtMost": _prop_at_most,
}


# Clue propagators whose reasoning is an *expert* forward move for a human —
# multi-entity counting/pigeonhole (set counts, group counts, cross-group counts
# and comparisons, group ordering) and the witness-scan pinches (between,
# absolute distance). They fire at tier 4 alongside the grid set logic, only
# when every cheaper technique has stalled, and are priced accordingly. The
# remaining propagators (direct disjunctions, conditionals, simple rank bounds,
# group membership narrowing) are the everyday tier-3 moves.
_EXPERT_CLUES = frozenset({
    "SetCount", "GroupCount", "GroupOrder", "GroupGroupCount",
    "GroupGroupCompare", "Between", "AbsApart",
})


def _sweep_clues(board, clues, expert: bool = False) -> int:
    return sum(
        _PROPAGATORS[type(c).__name__](board, c)
        for c in clues
        if type(c).__name__ in _PROPAGATORS
        and (type(c).__name__ in _EXPERT_CLUES) == expert
    )


def _sweep_advanced(board, clues) -> int:
    """Tier 4 combined: expert clue propagation, then grid set logic."""
    return _sweep_clues(board, clues, expert=True) or _sweep_set_logic(board, clues)


def _propagate_to_fixpoint(board, clues, hyp_depth: int = 0, first: bool = False, deadline=None) -> None:
    """Tiers 1-4 to a fixpoint; with hyp_depth > 0, also apply hypotheticals
    nested up to that depth. Raises Contradiction on conflict.

    ``first`` forwards the early-exit mode into the nested hypotheticals (see
    _sweep_hypothetical): take the first refuting assumption instead of the minimum
    one. Cheaper, but the chosen what-if is no longer the minimal-proof one, so it
    is used only for solvability/grading at depth 2 — never on the canonical
    depth-1 grade or the hint narrator's minimal proofs.

    Tier 4 (expert clue propagation + grid set logic) IS part of the inner
    closure: a what-if's refutation may use the full forward technique set, so
    the solver never escalates to more (or deeper) what-ifs than the reasoning
    genuinely needs. It runs last within the loop, so the cheap tiers still do
    almost all the work and the per-trial cost stays modest."""
    while True:
        if _sweep_lines(board):
            continue
        if _sweep_transitivity(board):
            continue
        if _sweep_clues(board, clues):
            continue
        if _sweep_advanced(board, clues):
            continue
        if hyp_depth and _hypothetical_at(board, clues, hyp_depth, first=first, deadline=deadline):
            continue
        return


# --- Tiers 5+: hypotheticals (proof by contradiction, nested lookahead) -------
# A `depth`-d hypothetical assumes a cell value and propagates with tiers up to
# (d-1) hypotheticals inside. depth 1 == tier 5 (single what-if); depth 2 ==
# tier 6 (a what-if whose inner reasoning may itself need a what-if).
def _ndet(board) -> int:
    """How many cells are determined — the size of a propagation's closure."""
    return sum(v != U for m in board.cell.values() for row in m for v in row)


# A what-if whose contradiction needs no more than this many forced cells is
# "easy enough" — take it without scanning further. Cheap stalls (the common case)
# stop almost immediately; only a stall with no quick refutation pays for the full
# scan. Tuned so the chosen what-if's proof is short without tripling grade cost.
def _sweep_hypothetical(board, clues, depth: int, first: bool = False, deadline=None,
                        sizes: list | None = None) -> int:
    """Apply the *easiest* what-if: of every assumption that propagates to a
    contradiction, take the one whose contradiction needs the fewest forced cells.
    A person picks the assumption that blows up quickly, not the first one in
    reading order — and the closure size is a faithful stand-in for the length of
    the proof a hint will show, so the hint that narrates this step is the shortest
    available rather than an arbitrary deep one. The full scan (every open cell,
    no early stop) makes the choice exact and deterministic; it costs more per
    solve, a deliberate trade for always surfacing the minimum refutation.

    ``first`` switches to early-exit: take the FIRST refuting assumption and return,
    skipping the minimisation scan. A depth-2 scan with an exhaustive depth-1
    refutation inside it costs ~100x a depth-1 scan (seconds → over a minute on a
    4x4); early-exit collapses that back to a fraction of a second. The trade is
    that the chosen what-if is no longer minimal, so this mode is reserved for
    *solvability/grading* of the deep (Tera catch-all) tier and for picking a
    nested-what-if hint cell — never the canonical depth-1 grade or a minimal proof.
    The inner propagation inherits ``first`` so the whole nested scan stays cheap.

    ``sizes``, when given, collects the applied what-if's refutation length (the
    cells its contradiction forced) — the direct "how easy was this proof by
    contradiction" signal band_of separates mega/giga on."""
    base = _ndet(board)
    best = None  # (closure_size, i, a, j, b, other)
    for (i, j), m in board.cell.items():
        if deadline is not None and time.monotonic() > deadline:
            raise SolveBudgetExceeded()  # bail before churning the rest of the scan
        for a in range(board.n):
            for b in range(board.n):
                if m[a][b] != U:
                    continue
                for trial, other in ((Y, N), (N, Y)):
                    test = board.copy()
                    test.set(i, a, j, b, trial)
                    try:
                        _propagate_to_fixpoint(test, clues, depth - 1, first=first, deadline=deadline)
                    except Contradiction:
                        size = _ndet(test) - base  # cells forced before the clash
                        if first:  # solvability only — take the first refutation found
                            board.set(i, a, j, b, other)
                            if sizes is not None:
                                sizes.append(size)
                            return 1
                        if best is None or size < best[0]:
                            best = (size, i, a, j, b, other)
                        break  # this cell is settled; don't test its other trial
    if best is None:
        return 0
    board.set(best[1], best[2], best[3], best[4], best[5])
    if sizes is not None:
        sizes.append(best[0])
    return 1


def _hypothetical_at(board, clues, max_depth: int, first: bool = False, deadline=None) -> int:
    """Try shallow hypotheticals first, deepening only when needed."""
    for depth in range(1, max_depth + 1):
        if _sweep_hypothetical(board, clues, depth, first=first, deadline=deadline):
            return depth
    return 0


def solve(theme: Theme, clues: list, max_hyp_depth: int = 1, first: bool = False, deadline=None) -> dict:
    """Solve by pure deduction, cheapest technique first. Returns a report:
      solved, needs_guessing, ceiling (highest tier used), steps (per tier),
      total_steps, board.

    Hypotheticals (tier 5 = depth 1, tier 6 = depth 2, …) kick in when forward
    propagation stalls, escalating depth only as needed — so unique puzzles solve
    with no guessing. max_hyp_depth caps the deepest nesting (0 = forward only).

    ``first`` switches the what-if scans to early-exit (see _sweep_hypothetical):
    far cheaper at depth 2, but the per-tier step counts become path-dependent, so
    it is for *solvability* checks (the Tera catch-all), not the canonical grade.
    ``deadline`` (a time.monotonic() value) bounds the what-if scans: if exceeded,
    SolveBudgetExceeded propagates out (the Tera recovery catches it and skips)."""
    board = Board(theme)
    steps = {t: 0 for t in range(7)}
    whatif_sizes: list = []  # refutation length of each applied what-if
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
        c = _sweep_advanced(board, clues)
        if c:
            steps[4] += c
            continue
        progressed = False
        for depth in range(1, max_hyp_depth + 1):
            c = _sweep_hypothetical(board, clues, depth, first=first, deadline=deadline,
                                    sizes=whatif_sizes)
            if c:
                steps[4 + depth] += c  # depth 1 -> tier 5, depth 2 -> tier 6
                progressed = True
                break
        if progressed:
            continue
        break  # stuck even at max depth -> needs deeper nesting (tier 6+)
    solved = board.solved()
    used = [t for t, s in steps.items() if s]
    return {
        "solved": solved,
        "needs_guessing": not solved,
        "ceiling": max(used) if used else 0,
        "steps": steps,
        "total_steps": sum(steps.values()),
        "whatif_sizes": whatif_sizes,
        "board": board,
    }


# Difficulty bands, separated primarily by solution METHODOLOGY — which
# techniques a solve forces — with the volume/ease of the contradiction work as
# the secondary separator inside the what-if bracket:
#   normal  ceiling <= 2  line elimination + transitivity only, no clue tricks
#   hard    ceiling 3-4   forward clue logic and/or the advanced tier-4 moves
#                         (set logic, expert counting) — never a contradiction
#   mega    ceiling == 5  contradictions INTRODUCED gently: at most
#                         _MEGA_MAX_WHATIFS what-ifs, each refuted within
#                         _MEGA_MAX_PROOF forced cells (a "very easy" what-if)
#   giga    ceiling == 5  sustained contradiction work (more, or longer, what-ifs)
#   tera    ceiling == 5 with heavy volume (>= _TERA_MIN_WHATIFS), or any nested
#                         what-if (ceiling >= 6) — the catch-all top tier
# The ladder is monotone in reasoning depth: no forward-only puzzle ever outranks
# a contradiction puzzle. Depth/breadth signals (step counts, clue reading load)
# remain *supplemental* — reported via difficulty_index on the payload, never the
# band. See band_of.
DIFFICULTY_ORDER = ("normal", "hard", "mega", "giga", "tera")

# Contradiction-effort cuts inside the what-if bracket (ceiling 5), fitted on a
# 360-candidate rich-pool sample (3 themes x 3 grid shapes) so all three what-if
# bands stay reachable in a few generate-and-grade attempts — the ceiling-5
# population split ~18% mega / 51% giga / 31% tera:
#   mega — few and easy: <= _MEGA_MAX_WHATIFS what-ifs, every refutation forced
#          within _MEGA_MAX_PROOF cells;
#   tera — heavy volume: >= _TERA_MIN_WHATIFS what-ifs (nesting is tera outright);
#   giga — everything between.
_MEGA_MAX_WHATIFS = 2
_MEGA_MAX_PROOF = 10
_TERA_MIN_WHATIFS = 8

# The index is a *human-effort* score, built on the deductive solve (our model of
# a human solver) — NOT the backtracking search, which models work a person never
# does. Two signals:
#   * effort   — log1p of the deductive step count, each tier weighted by its human
#                cost (_TIER_EFFORT): transitivity cheap … nested what-if dear.
#   * cluecost — mean clue cognitive weight (reading / working-memory load).
# Each is centred/scaled (centre, robust-spread) so the two contribute comparably;
# the sum is the index. SUPPLEMENTAL ONLY: reported on the payload as a
# fine-grained "how much work" signal, but bands are decided by methodology
# (ceiling bracket + contradiction effort), never by this scalar — see band_of.
_TIER_EFFORT = {2: 1, 3: 4, 4: 12, 5: 40, 6: 120}  # human-cost weight per deductive tier
_INDEX_NORM = {"effort": (5.199, 1.137), "cluecost": (2.813, 1.189)}  # (centre, scale)


def difficulty_index(report: dict) -> float:
    """Human-effort difficulty score (see _INDEX_NORM): weighted deductive step
    effort plus clue cognitive load, each z-scored and summed. Informational —
    it orders puzzles within a band on the payload; band_of does not read it."""
    s = report["steps"]
    effort = math.log1p(sum(w * s[t] for t, w in _TIER_EFFORT.items()))
    cluecost = report.get("clue_cost", {}).get("mean", _INDEX_NORM["cluecost"][0])

    def z(name, x):
        c, sc = _INDEX_NORM[name]
        return (x - c) / sc

    return z("effort", effort) + z("cluecost", cluecost)


def band_of(report: dict) -> str:
    """Name the difficulty band for a solved report — methodology first.

    The reasoning ceiling picks the bracket (normal / hard / the what-if bands);
    within the what-if bracket the puzzle is separated by how easy its
    contradiction work is: what-if count and refutation length (whatif_sizes,
    the cells each applied what-if forced before clashing). A nested what-if
    (ceiling >= 6) is unconditionally the top tier."""
    ceiling = report["ceiling"]
    if ceiling >= 6:  # a proof inside a proof — the deepest reasoning we verify
        return "tera"
    if ceiling == 5:
        w = report["steps"][5]
        sizes = report.get("whatif_sizes") or []
        longest = max(sizes) if sizes else 0
        if w <= _MEGA_MAX_WHATIFS and longest <= _MEGA_MAX_PROOF:
            return "mega"  # contradiction reasoning, but introductory
        if w >= _TERA_MIN_WHATIFS:
            return "tera"  # what-if volume heavy enough to top the scale
        return "giga"
    if ceiling >= 3:  # clue logic / advanced forward moves, no contradiction
        return "hard"
    return "normal"  # elimination + cross-referencing only


def grade(theme: Theme, clues: list, max_hyp_depth: int = 1, first: bool = False, deadline=None) -> dict:
    """Difficulty report: measured band + the per-tier step counts behind it.

    A single escalating solve reports the *ceiling* (the hardest technique it
    actually used), the per-tier step counts, and each applied what-if's
    refutation length, which `band_of` turns into a band. Grading caps at one
    round of contradiction reasoning by default (`max_hyp_depth=1`): normal..giga
    are all reachable from there (they are distinguished by the volume/ease of
    single what-ifs, not nested ones). A puzzle that still won't solve at that
    depth is 'ambiguous'; Tera (the catch-all) re-grades it at `max_hyp_depth=2,
    first=True` to recover nested what-ifs cheaply (see generate.generate_rated),
    and anything still unsolved needs deeper nesting than we verify and is
    skipped, so we only ship puzzles proven solvable by logic. ``first`` forwards
    the early-exit what-if mode for that cheap deep check."""
    r = solve(theme, clues, max_hyp_depth=max_hyp_depth, first=first, deadline=deadline)
    r.update(_advanced_metrics(theme, clues))
    r["band"] = band_of(r) if r["solved"] else "ambiguous"
    return r


def _advanced_metrics(theme: Theme, clues: list) -> dict:
    """Signals attached to every grade: the clue set's cognitive load (mean/max/
    total reading weight — `clue_cost` feeds difficulty_index) and the backtracking
    search-tree size (`nodes`). NOTE: `nodes` no longer feeds the index — it modelled
    blind search a human never does and saturated the cap, dominating the old blend;
    the index is now human-effort based (see difficulty_index). It is kept only as an
    informational stat on the payload, and is cheap, so the search stays capped low."""
    from .clues import clueset_metrics
    from .solver import search_effort

    return {
        "nodes": search_effort(theme, clues, max_nodes=60_000),  # informational only
        "clue_cost": clueset_metrics(clues),
    }


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
