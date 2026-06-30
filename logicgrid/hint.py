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
    _sweep_comparative,
    _sweep_cross_elim,
    _sweep_hypothetical,
    _sweep_lines,
    _sweep_naked,
    _sweep_transitivity,
    _diff_components,
    _propagate_to_fixpoint,
    _PROPAGATORS,
)
from .model import Contradiction, Theme

# Friendly names for the deduction tiers, surfaced in the hint UI. The index is
# the tier number deduce.py uses (0 givens … 6 nested what-if).
TIER_NAMES = {
    0: "Given",
    1: "Elimination",
    2: "Cross-reference",
    3: "Clue logic",
    4: "Set logic",
    5: "What-if",
    6: "Nested what-if",
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
                f"must go with {_label(theme, (j, b))} — every other {_cat(theme, j)} "
                f"is already crossed out for it."
            )
        return (
            f"In {_cat(theme, i)} × {_cat(theme, j)}, {_label(theme, (j, b))} "
            f"must go with {_label(theme, (i, a))} — every other {_cat(theme, i)} "
            f"is already crossed out for it."
        )
    # v == N: there is an established link in the same row or column
    for b2 in range(before.n):
        if m[a][b2] == Y:
            return (
                f"{_label(theme, (i, a))} goes with {_label(theme, (j, b2))}, so it "
                f"can't also go with {_label(theme, (j, b))}."
            )
    for a2 in range(before.n):
        if m[a2][b] == Y:
            return (
                f"{_label(theme, (j, b))} goes with {_label(theme, (i, a2))}, so "
                f"{_label(theme, (i, a))} can't go with {_label(theme, (j, b))}."
            )
    return f"{_label(theme, (i, a))} can't go with {_label(theme, (j, b))}."


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
                f"{_label(theme, p)} goes with {_label(theme, r)}, and {_label(theme, q)} "
                f"goes with {_label(theme, r)}, so {_label(theme, p)} goes with {_label(theme, q)}."
            )
        if v == N and rp == Y and rq == N:
            return (
                f"{_label(theme, p)} goes with {_label(theme, r)}, but {_label(theme, q)} "
                f"doesn't, so {_label(theme, p)} doesn't go with {_label(theme, q)}."
            )
        if v == N and rp == N and rq == Y:
            return (
                f"{_label(theme, q)} goes with {_label(theme, r)}, but {_label(theme, p)} "
                f"doesn't, so {_label(theme, p)} doesn't go with {_label(theme, q)}."
            )
    link = "goes with" if v == Y else "doesn't go with"
    return f"Cross-referencing the established links, {_label(theme, p)} {link} {_label(theme, q)}."


def _reason_clue(theme, clue, i, a, j, b, v) -> str:
    rel = "must go with" if v == Y else "can't go with"
    # strip the clue's own trailing period so the embedded quote + em-dash reads cleanly
    text = clue.text(theme).rstrip(".")
    return f"From the clue “{text}” — {_label(theme, (i, a))} {rel} {_label(theme, (j, b))}."


def _reason_hyp(theme, i, a, j, b, v) -> str:
    if v == N:
        return (
            f"Suppose {_label(theme, (i, a))} went with {_label(theme, (j, b))} — "
            f"following the clues from there hits a contradiction, so it doesn't."
        )
    return (
        f"Suppose {_label(theme, (i, a))} didn't go with {_label(theme, (j, b))} — "
        f"that hits a contradiction, so it does."
    )


# --- What-if chain: a relevance-pruned proof of the contradiction ------------
# Replays the refuted branch one deduction at a time, recording each deduction's
# *antecedents* (the facts it followed from). When the branch clashes, it walks
# back from the contradiction through those antecedents and keeps ONLY the steps
# on a path to it — so the narration is the actual proof, not the full forward
# closure (which is mostly true-but-irrelevant side deductions).

def _cell(p, q):
    """A normalised cell key (lower category index first) for two nodes."""
    return (p[0], p[1], q[0], q[1]) if p[0] < q[0] else (q[0], q[1], p[0], p[1])


def _join(items, conj="and"):
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conj} {items[1]}"
    return ", ".join(items[:-1]) + f", {conj} {items[-1]}"


# --- Set logic (tier 4): explaining cross-elimination & naked subsets ---------
# Both produce only "not linked" (N) facts. Each explainer returns a reason plus
# the determined cells it read, so the what-if chain can slice through them.
def _explain_cross_elim(theme, S, ci, a, cj, b):
    n = S.n
    for m in range(S.k):
        if m == ci or m == cj:
            continue
        ca = [t for t in range(n) if S.get(ci, a, m, t) != N]
        if not ca or any(S.get(cj, b, m, t) != N for t in ca):
            continue  # B can still share one of A's options here — no elimination
        cands = _join([_label(theme, (m, t)) for t in ca], "or")
        reason = (f"in {_cat(theme,m)}, {_label(theme,(ci,a))} must be {cands}, but "
                  f"{_label(theme,(cj,b))} can be none of those, so they can't be the same.")
        ante = [_cell((ci, a), (m, t)) for t in range(n) if S.get(ci, a, m, t) == N]
        ante += [_cell((cj, b), (m, t)) for t in ca]  # B's exclusions of A's options (all N)
        return reason, ante
    return None


def _naked_owners(S, ci, cj, a, b):
    """The naked subset that rules out (ci,a)~(cj,b): a set of lines whose options
    are confined to exactly themselves. Returns (orientation, owners, span)."""
    n = S.n
    rcand = {r: frozenset(t for t in range(n) if S.get(ci, r, cj, t) != N) for r in range(n)}
    for size in (2, 3):
        for combo in combinations([r for r in range(n) if r != a], size):
            span = frozenset().union(*(rcand[r] for r in combo))
            if len(span) == size and b in span:
                return ("row", combo, span)
    ccand = {t: frozenset(r for r in range(n) if S.get(ci, r, cj, t) != N) for t in range(n)}
    for size in (2, 3):
        for combo in combinations([t for t in range(n) if t != b], size):
            span = frozenset().union(*(ccand[t] for t in combo))
            if len(span) == size and a in span:
                return ("col", combo, span)
    return None


def _explain_naked(theme, S, ci, a, cj, b):
    res = _naked_owners(S, ci, cj, a, b)
    if res is None:
        return None
    orient, owners, span = res
    n = S.n
    if orient == "row":
        own = [_label(theme, (ci, r)) for r in owners]
        cols = [_label(theme, (cj, t)) for t in span]
        ante = [_cell((ci, r), (cj, t)) for r in owners for t in range(n)
                if t not in span and S.get(ci, r, cj, t) == N]
    else:
        own = [_label(theme, (cj, t)) for t in owners]
        cols = [_label(theme, (ci, r)) for r in span]
        ante = [_cell((ci, r), (cj, t)) for t in owners for r in range(n)
                if r not in span and S.get(ci, r, cj, t) == N]
    reason = (f"{_join(own)} must take {_join(cols, 'or')} between them, so "
              f"{_label(theme,(ci,a))} can't go with {_label(theme,(cj,b))}.")
    return reason, ante


def _explain_set(theme, S, cell, v):
    """Why set logic forces ``cell`` to N (only N is ever produced). Returns
    (reason, antecedent_cells) or None."""
    if v != N:
        return None
    ci, a, cj, b = cell
    return _explain_cross_elim(theme, S, ci, a, cj, b) or _explain_naked(theme, S, ci, a, cj, b)


def _explain_comparative(theme, clues, ci, a, cj, b, v):
    """Narrate an exact-difference comparison deduction: find the ordered category
    whose Diff graph links the two terms and a shared reference both are pinned
    to, then read off whether their value-offsets match (same entity) or differ."""
    ta, tb = (ci, a), (cj, b)
    for cat, off in _diff_components(clues):
        if ta not in off or tb not in off:
            continue
        catname = _cat(theme, cat).lower()
        refs = sorted((r for r in off if r not in (ta, tb)),
                      key=lambda r: abs(off[ta] - off[r]) + abs(off[tb] - off[r]))
        amt = theme.categories[cat].amount

        def gap(t, r):
            d = off[t] - off[r]
            return f"exactly {amt(abs(d))} {'more' if d > 0 else 'less'} than {_label(theme, r)}"

        if refs:
            r = refs[0]
            if v == Y:
                return (f"{_label(theme,ta)} and {_label(theme,tb)} are both {gap(ta,r)} "
                        f"in {catname}, so they're the same.")
            return (f"{_label(theme,ta)} is {gap(ta,r)} in {catname} but {_label(theme,tb)} "
                    f"is {gap(tb,r)}, so they can't be the same.")
        rel = "the same" if v == Y else "a different"
        return (f"the difference clues pin {_label(theme,ta)} and {_label(theme,tb)} to "
                f"{rel} {catname}.")
    return None


def _explain_trans_ante(S, ci, a, cj, b, v):
    """Antecedent pair for a transitivity deduction of (ci,a)~(cj,b)=v, or None.
    A pivot in a third category linked to both nodes forces their relation."""
    for c in range(S.k):
        if c == ci or c == cj:
            continue
        for it in range(S.n):
            rp = S.get(ci, a, c, it)
            rq = S.get(cj, b, c, it)
            if v == Y and rp == Y and rq == Y:
                return [_cell((ci, a), (c, it)), _cell((cj, b), (c, it))]
            if v == N and ((rp == Y and rq == N) or (rp == N and rq == Y)):
                return [_cell((ci, a), (c, it)), _cell((cj, b), (c, it))]
    return None


def _explain(theme, clues, S, cell, v):
    """Why is ``cell`` forced to ``v`` given board state ``S`` (in which the cell
    is still unknown)? Returns ``(reason_text, antecedent_cells)`` — the simplest
    justification found, trying line elimination, then transitivity, then clues —
    or ``None`` if no single rule accounts for it. Antecedent cells are
    normalised (lower category first)."""
    ci, a, cj, b = cell  # cell is normalised, so (ci, cj) is a real block
    n = S.n
    m = S.cell[(ci, cj)]
    if v == N:  # an established link in the same row or column rules this out
        for b2 in range(n):
            if b2 != b and m[a][b2] == Y:
                return _reason_line(theme, S, ci, a, cj, b, N), [(ci, a, cj, b2)]
        for a2 in range(n):
            if a2 != a and m[a2][b] == Y:
                return _reason_line(theme, S, ci, a, cj, b, N), [(ci, a2, cj, b)]
    else:  # v == Y: forced because every other cell in a row/column is ruled out
        if m[a].count(N) == n - 1 and m[a][b] == U:
            return (_reason_line(theme, S, ci, a, cj, b, Y),
                    [(ci, a, cj, bb) for bb in range(n) if bb != b])
        col = [m[aa][b] for aa in range(n)]
        if col.count(N) == n - 1 and m[a][b] == U:
            return (_reason_line(theme, S, ci, a, cj, b, Y),
                    [(ci, aa, cj, b) for aa in range(n) if aa != a])
    tr = _explain_trans_ante(S, ci, a, cj, b, v)
    if tr is not None:
        return _reason_trans(theme, S, ci, a, cj, b, v), tr
    for clue in clues:  # a clue whose propagation forces this cell to v
        name = type(clue).__name__
        if name not in _PROPAGATORS:
            continue
        cp = S.copy()
        try:
            _PROPAGATORS[name](cp, clue)
        except Contradiction:
            continue
        if cp.get(ci, a, cj, b) == v:
            return _reason_clue(theme, clue, ci, a, cj, b, v), _clue_ante(S, clue, cell, v)
    return _explain_set(theme, S, cell, v)  # grid set-logic, else None (caller falls back)


def _ablate_cells(board, clue):
    """Determined cells the clue could read — candidate antecedents to test."""
    inv = sorted(clue.involved)
    out = []
    for x in range(len(inv)):
        for y in range(x + 1, len(inv)):
            m = board.cell.get((inv[x], inv[y]))
            if m is None:
                continue
            out += [(inv[x], a, inv[y], b) for a in range(board.n)
                    for b in range(board.n) if m[a][b] != U]
    return out


def _clear(board, cell):
    cp = board.copy()
    ci, a, cj, b = cell
    cp.cell[(ci, cj)][a][b] = U
    return cp


def _clue_ante(board, clue, cell, v):
    """Which determined cells the clue *needed* to derive `cell` — found by
    ablation: drop a fact, see if the deduction survives."""
    prop = _PROPAGATORS[type(clue).__name__]
    ci, a, cj, b = cell
    ante = []
    for d in _ablate_cells(board, clue):
        if d == cell:
            continue
        cp = _clear(board, d)
        try:
            prop(cp, clue)
        except Contradiction:
            ante.append(d)
            continue
        if cp.get(ci, a, cj, b) != v:
            ante.append(d)
    return ante


def _clue_fail_ante(board, clue):
    """Which determined cells the clue *needed* to become unsatisfiable."""
    prop = _PROPAGATORS[type(clue).__name__]
    ante = []
    for d in _ablate_cells(board, clue):
        cp = _clear(board, d)
        try:
            prop(cp, clue)
            ante.append(d)  # removing d clears the clash -> d was a cause
        except Contradiction:
            pass
    return ante or _ablate_cells(board, clue)  # fall back to the full read set


def _clue_clash(theme, clues, board):
    """A count-style clue that can no longer be satisfied at ``board`` (the kind
    that raises without a single clashing cell). Returns (text, antecedents)."""
    for clue in clues:
        name = type(clue).__name__
        if name not in _PROPAGATORS:
            continue
        cp = board.copy()
        try:
            _PROPAGATORS[name](cp, clue)
        except Contradiction:
            return (f"…but now the clue “{clue.text(theme).rstrip('.')}” can no longer "
                    f"hold — a contradiction.", _clue_fail_ante(board, clue))
    return ("…which forces a contradiction.", [])


def _whatif_chain(theme, clues, base: Board, i, a, j, b, forced) -> list:
    """The relevance-pruned proof that the refuted assumption is impossible.

    Assume the opposite of what the solver forced, then run the *real* tier-1-3
    propagation (the tested ``deduce`` sweeps) and journal every cell it forces,
    in order, until it hits the contradiction. Replaying that exact journal — the
    one path that actually reaches the clash — gives each step a plain-English
    reason and its antecedents; a backward slice from the clash then keeps only
    the steps on a path to it, so the narration is the proof, not the full
    forward closure of true-but-irrelevant side deductions."""
    trial = N if forced == Y else Y
    jb = base.copy()
    try:
        jb.set(i, a, j, b, trial)
    except Contradiction:
        return []

    # Journal every newly-forced cell, in the solver's own propagation order.
    journal: list = []
    base_set = jb.set

    def journaling_set(ci, ca, cj, cb, v):
        changed = base_set(ci, ca, cj, cb, v)  # raises (with .conflict) on a clash
        if changed:
            journal.append((_cell((ci, ca), (cj, cb)), v))
        return changed

    jb.set = journaling_set
    conflict = None
    try:
        _propagate_to_fixpoint(jb, clues, 0)
    except Contradiction as exc:
        conflict = exc.conflict
    # No depth-0 contradiction (shouldn't happen for a real what-if) -> generic.
    if conflict is None and not journal:
        return _whatif_frame(theme, i, a, j, b, trial, forced, [], "…which forces a contradiction.")

    # Replay the journal, explaining each forced cell against the state the solver
    # actually saw when it forced it.
    rb = base.copy()
    rb.set(i, a, j, b, trial)
    records: list = []
    writer: dict = {}
    for cell, v in journal:
        res = _explain(theme, clues, rb, cell, v)
        ci, ca, cj, cb = cell
        if res is None:  # no single rule pinned it (very rare) — name the fact plainly
            rel = "go with" if v == Y else "not go with"
            res = (f"the clues force {_label(theme,(ci,ca))} to {rel} "
                   f"{_label(theme,(cj,cb))}.", [])
        reason, ante = res
        rb.set(ci, ca, cj, cb, v)
        writer[cell] = len(records)
        records.append({"cell": cell, "v": v, "ante": ante, "reason": reason})

    # The clash: a propagation tried to set a cell against an existing fact.
    clash_text = clash_ante = None
    if conflict is not None:
        cci, ca, ccj, cb, cur, v = conflict
        cell = _cell((cci, ca), (ccj, cb))
        nci, na, ncj, nb = cell
        sb = rb.copy()                       # explain the *attempted* force...
        sb.cell[(nci, ncj)][na][nb] = U
        res = _explain(theme, clues, sb, cell, v)
        if res is not None:
            reason, ante = res
            had = "go with" if cur == Y else "not go with"
            clash_text = (f"{reason[:1].upper()}{reason[1:]} But {_label(theme,(nci,na))} was "
                          f"already shown to {had} {_label(theme,(ncj,nb))} — a contradiction.")
            clash_ante = list(ante) + [cell]  # ...and the fact it contradicts
    if clash_text is None:  # count-style clue, or a force no single rule names
        clash_text, clash_ante = _clue_clash(theme, clues, rb)

    # Backward slice: keep only deductions reachable from the contradiction.
    keep: set = set()
    queue = list(clash_ante)
    while queue:
        cell = queue.pop()
        idx = writer.get(cell)
        if idx is None or idx in keep:  # an already-known fact / the assumption -> leaf
            continue
        keep.add(idx)
        queue.extend(records[idx]["ante"])
    proof = [records[k]["reason"][:1].upper() + records[k]["reason"][1:] for k in sorted(keep)]
    return _whatif_frame(theme, i, a, j, b, trial, forced, proof, clash_text)


def _whatif_frame(theme, i, a, j, b, trial, forced, proof, clash_text) -> list:
    """Wrap a proof body in the assumption opener and the conclusion closer."""
    verb = "goes with" if trial == Y else "does not go with"
    concl = "does not go with" if forced == N else "goes with"
    return (
        [f"Start by assuming {_label(theme,(i,a))} {verb} {_label(theme,(j,b))}."]
        + proof + [clash_text]
        + [f"So {_label(theme,(i,a))} {concl} {_label(theme,(j,b))}."]
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


def _round_setlogic(board, clues, theme, steps) -> bool:
    # cross-elimination, then naked subsets, then exact-difference comparison
    # (matches _sweep_set_logic order), so each deduction names the tactic that
    # drove it.
    for sweep in (_sweep_cross_elim, _sweep_naked):
        before = board.copy()
        if not sweep(board):
            continue
        for (i, j, a, b, v) in _changes(before, board):
            res = _explain_set(theme, before, (i, a, j, b), v)
            reason = res[0] if res else f"{_label(theme,(i,a))} can't go with {_label(theme,(j,b))}."
            steps.append(_step(theme, i, j, a, b, v, 4, reason))
        return True
    before = board.copy()
    if _sweep_comparative(board, clues):
        for (i, j, a, b, v) in _changes(before, board):
            rel = "goes with" if v == Y else "can't go with"
            reason = _explain_comparative(theme, clues, i, a, j, b, v) or (
                f"comparing the difference clues, {_label(theme,(i,a))} {rel} {_label(theme,(j,b))}.")
            steps.append(_step(theme, i, j, a, b, v, 4, reason))
        return True
    return False


def _round_hyp(board, clues, theme, steps) -> bool:
    # Mirror deduce.solve's escalation: a single what-if (depth 1, tier 5) first,
    # then a nested one (depth 2, tier 6) only when the shallow pass can't progress
    # — so the narrator can carry a puzzle whose stall needs a what-if *inside* a
    # what-if (the Tera catch-all) instead of stopping short and reporting "done".
    for depth in (1, 2):
        before = board.copy()
        # depth 1 stays exhaustive (minimal proof + step-by-step chain); the nested
        # depth-2 pass uses early-exit (first=True) so a hint on a Tera nested
        # what-if returns in a fraction of a second instead of ~a minute.
        if not _sweep_hypothetical(board, clues, depth, first=(depth == 2)):
            continue
        for (i, j, a, b, v) in _changes(before, board):
            step = _step(theme, i, j, a, b, v, 4 + depth, _reason_hyp(theme, i, a, j, b, v))
            # Defer the (expensive) chain reconstruction to the ONE step a hint
            # returns. Only the shallow what-if reconstructs a step-by-step proof —
            # its refutation is forward propagation (see _whatif_chain); a nested
            # what-if keeps the correct cell and the plain "suppose … contradiction".
            if depth == 1:
                step["_ctx"] = (before, i, a, j, b, v)
            steps.append(step)
        return True
    return False


def trace(theme: Theme, clues: list) -> list[dict]:
    """The full ordered list of explained deductions that solve the puzzle.

    Mirrors ``deduce.solve``'s cheapest-tier-first escalation, so the narration
    matches how the puzzle is graded. Stops if no tier makes progress (a puzzle
    needing deeper nesting than tier 5 — skipped at generation anyway).
    """
    board = Board(theme)
    steps: list[dict] = []
    _givens(board, clues, theme, steps)
    rounds = (_round_lines, _round_trans, _round_clues, _round_setlogic, _round_hyp)
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
        # Build the what-if chain only for the step we actually return.
        ctx = step.pop("_ctx", None)
        if ctx is not None:
            before, i, a, j, b, v = ctx
            step["chain"] = _whatif_chain(theme, clues, before, i, a, j, b, v)
        return step
    return {"done": True}
