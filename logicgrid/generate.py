"""Puzzle generation: random solution -> clue pool -> minimal unique clue set."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .clues import (
    AbsApart,
    Adjacent,
    AllDifferent,
    Among,
    AtLeastApart,
    AtMost,
    Between,
    Diff,
    DiffGroup,
    EitherOr,
    Exactly,
    ExactlyKLinks,
    GroupCount,
    GroupGroupCompare,
    GroupGroupCount,
    GroupMatch,
    GroupOrder,
    Greater,
    And,
    Compound,
    Conditional,
    GroupLink,
    GroupSubset,
    InGroup,
    Link,
    Not,
    NotInGroup,
    Or,
    SameGroup,
    MultiCompare,
    Negative,
    Neither,
    NextTo,
    Positive,
    SetCount,
    Xor,
    clue_cost,
    entity_of,
)
from .model import Theme
from .solver import count_solutions, is_unique


@dataclass
class Puzzle:
    theme: Theme
    solution: list[list[int]]  # X[entity][category] = item index
    clues: list


def random_solution(theme: Theme, rng: random.Random) -> list[list[int]]:
    n, k = theme.n, theme.k
    X = [[0] * k for _ in range(n)]
    for i in range(n):
        X[i][0] = i
    for c in range(1, k):
        perm = list(range(n))
        rng.shuffle(perm)
        for i in range(n):
            X[i][c] = perm[i]
    return X


def _grouped_categories(theme: Theme):
    """For every category that carries a (>=2-block) partition, the data a clue
    needs to talk about its groups: ``(cat, labels, parts, group_of)`` where
    ``parts[gi]`` are the item indices of group ``gi`` and ``group_of[item]`` is its
    group index. Shared by the conditional and group-instance builders."""
    out = []
    for cat in range(theme.k):
        co = theme.categories[cat]
        if not co.has_groups:
            continue
        labels = [lab for lab, _ in co.groups]
        parts = [tuple(co.items.index(m) for m in mem) for _, mem in co.groups]
        if len(parts) < 2:
            continue
        group_of = {x: gi for gi, mem in enumerate(parts) for x in mem}
        out.append((cat, labels, parts, group_of))
    return out


# Chance an exclusive-pairing draw whose links overlap (share a value or chain
# through a term) is kept anyway — a minority texture next to the fully
# independent draws, which are always kept. See the pairing loop in
# build_clue_pool.
_PAIRING_OVERLAP_PROB = 0.25


# --- Semantic screen ---------------------------------------------------------
# One informativeness test instead of per-family triviality guards: every pool
# candidate is evaluated against a shared sample of random solutions, yielding
# a truth *signature* (bitmask over the sample). From the signatures we
#   * reject tautologies and near-tautologies (holds on the whole sample —
#     carries no information a solver could use),
#   * drop semantic duplicates ACROSS families, keeping the cheaper reading
#     (e.g. a shared-value pairing that restates an either/or),
#   * reject INTRA-clue redundancy inside boolean compounds: an operand that
#     semantically implies a sibling collapses the connective to one branch
#     ("either Edmund is in Oldwall, or someone in the River Ward is Edmund"
#     when Oldwall is in the River Ward) — the generalization of the old
#     hand-coded named-link-subsumed-by-existential guard.
# Duplicate atoms inside one clue ("A with X or A with X") are impossible by
# construction (sampling without replacement / `used` sets) and additionally
# rejected structurally where atoms are explicit (see clues.Count).
_SCREEN_SAMPLES = 128
_SCREEN_DEDUPE_MIN_BITS = 4  # sparse signatures are weak evidence of equivalence


def _stmt_parts(stmt):
    """Direct operands of a boolean connective node, else None."""
    if isinstance(stmt, (And, Or)):
        return list(stmt.parts)
    if isinstance(stmt, Xor):
        return [stmt.p, stmt.q]
    return None


def _has_subsumed_branch(clue, sols) -> bool:
    """True if a boolean node inside the clue has an operand that semantically
    implies a sibling on the sample — intra-clue redundancy."""
    if isinstance(clue, Compound):
        roots = [clue.stmt]
    elif isinstance(clue, Conditional):
        roots = [clue.ante, clue.cons]
    else:
        return False
    todo = list(roots)
    while todo:
        node = todo.pop()
        if isinstance(node, Not):
            todo.append(node.s)
            continue
        parts = _stmt_parts(node)
        if not parts:
            continue
        todo.extend(parts)
        sigs = [
            sum(1 << i for i, s in enumerate(sols) if p.value(s)) for p in parts
        ]
        for i in range(len(sigs)):
            for j in range(len(sigs)):
                if i != j and sigs[i] & ~sigs[j] == 0:  # operand i implies operand j
                    return True
    return False


def _semantic_screen(theme, X, rng, clues: list) -> list:
    """Filter an assembled pool by semantic signature (see section comment)."""
    sols = [random_solution(theme, rng) for _ in range(_SCREEN_SAMPLES)]
    full = (1 << _SCREEN_SAMPLES) - 1
    kept: list = []
    by_sig: dict = {}
    for c in clues:
        if isinstance(c, Positive):
            kept.append(c)  # positives pin the solution; uniqueness of the full pool needs them
            continue
        sig = 0
        for i, s in enumerate(sols):
            if c.holds(s):
                sig |= 1 << i
        if sig == full:
            continue  # true on the whole sample — (near-)tautology
        if _has_subsumed_branch(c, sols):
            continue
        if bin(sig).count("1") < _SCREEN_DEDUPE_MIN_BITS:
            kept.append(c)  # too selective to attest equivalence — keep unconditionally
            continue
        prev = by_sig.get(sig)
        if prev is None:
            by_sig[sig] = len(kept)
            kept.append(c)
        elif clue_cost(c) < clue_cost(kept[prev]):
            kept[prev] = c  # same semantic content: the simpler reading wins
    return kept


def build_clue_pool(
    theme: Theme,
    X: list[list[int]],
    rng: random.Random,
    max_negatives: int = 80,
    max_comparisons: int = 40,
    among_sizes: tuple[int, ...] = (2, 3),
    max_among: int = 40,
    max_either: int = 40,
    max_neither: int = 40,
    multi_match: bool = True,
    alldiff_sizes: tuple[int, ...] = (3, 4),
    max_alldiff: int = 30,
    pairing_sizes: tuple[int, ...] = (2, 3),
    pairing_k: int = 1,
    pairing_two_prob: float = 0.0,  # chance a 3-link draw rolls "exactly two"
    max_pairing: int = 25,
    match_sizes: tuple[int, ...] = (2, 3),
    max_match: int = 25,
    max_atmost: int = 20,
    max_exactly: int = 20,
    max_conditional: int = 14,
    conditional_compound_prob: float = 0.28,
    max_groups: int = 24,
    max_cross: int = 6,
    max_compounds: int = 16,
    max_set_count: int = 14,
    enable_negatives: bool = True,
    enable_among: bool = True,
    enable_either: bool = True,
    enable_neither: bool = True,
    enable_alldiff: bool = True,
    enable_pairing: bool = True,
    enable_match: bool = True,
    enable_atmost: bool = True,
    enable_exactly: bool = True,
    enable_conditional: bool = False,
    enable_groups: bool = False,
    enable_group_instances: bool = False,
    enable_set_count: bool = False,
    include_sequential: bool = False,
) -> list:
    """Every positive link plus sampled negatives, comparisons, and "one of N"
    disjunctions (Among / EitherOr / Neither), all true under X.

    The disjunction option lists are over *terms* that may span categories, so a
    clue can read "Ava goes with either Bagel or Latte" (a Pastry and a Drink).
    Each Among/EitherOr fixes exactly one true option plus decoys; Neither uses
    all-wrong options.

    `among_sizes` is the set of N to generate; the default (2, 3) covers
    either/or and one-of-three. Any N >= 2 is valid, so larger disjunctions can
    be unlocked later by widening this tuple.

    `multi_match` enables "at least K of N" Among clues (K in 2..N-1, distinct
    categories) — always ambiguous, never K == N.

    `alldiff_sizes` are the N for "all different" clues (N terms on distinct
    entities, spanning >= 2 categories); generated for N in 3..n.

    `pairing_sizes`/`pairing_k` drive exclusive-pairing clues ("exactly K of N
    links hold"; default K=1 over N in {2,3} is the classic "either/or, not
    both"). `match_sizes` are the group sizes N for group-match clues ("between
    A and B, one is C and the other is D"), for N in 2..n.
    """
    n, k = theme.n, theme.k
    positives: list = []
    negatives: list = []
    comparisons: list = []
    among: list = []
    either: list = []
    neither: list = []
    alldiff: list = []
    pairing: list = []
    match: list = []
    atmost: list = []
    exactly: list = []
    conditional: list = []
    groups: list = []
    cross: list = []  # cross-group clues (need two grouped categories)
    compounds: list = []  # bare statement clues mixing a named instance + a group
    set_counts: list = []  # cardinality over a union of set instances (SetCount)

    for c1 in range(k):
        for c2 in range(c1 + 1, k):
            for e in range(n):
                positives.append(Positive((c1, X[e][c1]), (c2, X[e][c2])))
            if enable_negatives:
                for e1 in range(n):
                    for e2 in range(n):
                        if e1 != e2:
                            negatives.append(Negative((c1, X[e1][c1]), (c2, X[e2][c2])))

    # Sequential clues on an ordered category (rank = item index, ascending):
    # higher/lower-than, exact-difference, between, immediately before/after and
    # next-to, at-least/at-most apart. Reference terms come from any non-ordered
    # category, drawn from *distinct* categories where possible so a comparison
    # naturally mixes categories ("the Ben order vs the Latte order"). Disabled
    # by default.
    for cn in range(k) if include_sequential else ():
        cat = theme.categories[cn]
        if not cat.ordered:
            continue
        refs = [c for c in range(k) if c != cn]

        def refs_for(entities):
            """One reference term per entity, from distinct non-ordered categories
            where possible (so the two sides of a comparison span categories)."""
            m = len(entities)
            cats = rng.sample(refs, m) if len(refs) >= m else [rng.choice(refs) for _ in entities]
            return [(c, X[e][c]) for c, e in zip(cats, entities)]

        rank = {e: X[e][cn] for e in range(n)}            # item index == rank
        by_rank = sorted(range(n), key=lambda e: rank[e])  # entities low -> high
        step = cat.values[1] - cat.values[0] if cat.values and n >= 2 else 1

        for e1 in range(n):  # higher-than for every ordered pair
            for e2 in range(n):
                if rank[e1] <= rank[e2]:
                    continue
                a, b = refs_for([e1, e2])
                comparisons.append(Greater(cn, a, b))
                # Exact-difference only for a *middle* gap (2..n-2 ranks): with
                # evenly-spaced values that gap repeats, so the clue narrows
                # rather than pinning exact values, and isn't just "adjacent".
                gap = rank[e1] - rank[e2]
                if cat.values is not None and 2 <= gap <= n - 2:
                    comparisons.append(
                        Diff(cn, a, b, cat.value(X[e1][cn]) - cat.value(X[e2][cn]), cat.values)
                    )

        for idx in range(n - 1):  # consecutive ranks: before/after + next-to
            a, b = refs_for([by_rank[idx], by_rank[idx + 1]])
            comparisons.append(Adjacent(cn, a, b))  # directional: a immediately below b
            comparisons.append(NextTo(cn, a, b))    # undirected: immediately next to

        for mid in range(n):  # between: a middle-ranked entity, one below + one above
            lows = [e for e in range(n) if rank[e] < rank[mid]]
            highs = [e for e in range(n) if rank[e] > rank[mid]]
            if lows and highs:
                a, b, c = refs_for([rng.choice(lows), rng.choice(highs), mid])
                comparisons.append(Between(cn, a, b, c))

        if cat.values is not None:
            for e1 in range(n):
                for e2 in range(n):
                    if e1 == e2:
                        continue
                    m = rank[e1] - rank[e2]
                    # at-least-apart / at-least-away: a loose multiple of the
                    # (even) step, >= 2 steps so it differs from "more than".
                    if m >= 2:
                        a, b = refs_for([e1, e2])
                        delta = step * rng.randint(2, m)
                        comparisons.append(AtLeastApart(cn, a, b, delta, cat.values))  # directional
                        comparisons.append(AbsApart(cn, a, b, delta, True, cat.values))  # symmetric
                    # at-most-away: |gap| <= delta, with delta >= the true gap but
                    # below the full range, so it bounds the two items *close*.
                    g = abs(m)
                    if e1 < e2 and 1 <= g <= n - 2:
                        a, b = refs_for([e1, e2])
                        delta = step * rng.randint(g, n - 2)
                        comparisons.append(AbsApart(cn, a, b, delta, False, cat.values))

        for c in range(n):  # less/more than both of two others
            highs = [e for e in range(n) if rank[e] > rank[c]]
            lows = [e for e in range(n) if rank[e] < rank[c]]
            if len(highs) >= 2:
                o1, o2 = rng.sample(highs, 2)
                tc, t1, t2 = refs_for([c, o1, o2])
                comparisons.append(MultiCompare(cn, tc, [t1, t2], False))
            if len(lows) >= 2:
                o1, o2 = rng.sample(lows, 2)
                tc, t1, t2 = refs_for([c, o1, o2])
                comparisons.append(MultiCompare(cn, tc, [t1, t2], True))

    # "One of N" disjunctions over option terms. For each anchor entity e a term
    # (co, io) with co != ca is *true* iff it is e's real item there.
    #
    # Options are sampled freely across the non-anchor categories — an option list
    # may still happen to repeat a category, but it is never forced to. (The
    # "at least K" path (K >= 2) below requires distinct categories.)
    for e in range(n):
        for ca in range(k):
            anchor = (ca, X[e][ca])
            non_anchor = [co for co in range(k) if co != ca]
            true_terms = [(co, X[e][co]) for co in non_anchor]
            false_terms = [
                (co, io) for co in non_anchor for io in range(n) if io != X[e][co]
            ]

            def make_options(size, include_true):
                """`size` option terms (one true if include_true, else all false),
                sampled freely across the non-anchor categories, or None if
                infeasible."""
                if include_true:
                    if not true_terms or len(false_terms) < size - 1:
                        return None
                    return [rng.choice(true_terms), *rng.sample(false_terms, size - 1)]
                if len(false_terms) < size:
                    return None
                return rng.sample(false_terms, size)

            for size in among_sizes:
                if size < 2:
                    continue
                if enable_among:
                    opts = make_options(size, True)
                    # "At least one of …" only says more than "either/or" when an
                    # entity could match several options at once — i.e. the options
                    # span >=2 categories. All-same-category options collapse to
                    # "exactly one of" (a disguised either/or), so skip those.
                    if opts is not None and len({o[0] for o in opts}) >= 2:
                        among.append(Among(anchor, opts))
                if enable_either:
                    opts = make_options(size, True)
                    if opts is not None:
                        either.append(EitherOr(anchor, opts))
                if enable_neither:
                    opts = make_options(size, False)
                    if opts is not None:
                        neither.append(Neither(anchor, opts))

            # Distinct-category option lists (exactly `n_true` of them match the
            # anchor) for the threshold disjunctions below.
            def distinct_opts(n_opts, n_true):
                cats = rng.sample(non_anchor, n_opts)
                true_cats = set(rng.sample(cats, n_true))
                return [
                    (co, X[e][co])
                    if co in true_cats
                    else (co, rng.choice([i for i in range(n) if i != X[e][co]]))
                    for co in cats
                ]

            # "At least K of N" Among (K < N, so always ambiguous; K == N would be N
            # direct links). Needs N >= 3 distinct categories.
            if multi_match:
                for n_opts in range(3, len(non_anchor) + 1):
                    for at_least in range(2, n_opts):
                        among.append(Among(anchor, distinct_opts(n_opts, at_least), at_least=at_least))

            # "At most K of N" (K < N). N >= 3 distinct categories — at N == 2 it
            # collapses toward either/or territory, so keep it to genuine "at most
            # one of three"-style clues (needs >= 4 total categories).
            if enable_atmost:
                for n_opts in range(3, len(non_anchor) + 1):
                    for k_max in range(1, n_opts):
                        atmost.append(AtMost(anchor, distinct_opts(n_opts, k_max), k_max))

            # "Exactly K of N" (2 <= K < N) — the two-sided count. K == 0/1 are
            # Neither/EitherOr and K == N is direct links, so start at K == 2,
            # which needs N >= 3 distinct categories (>= 4 total categories).
            if enable_exactly:
                for n_opts in range(3, len(non_anchor) + 1):
                    for k_exact in range(2, n_opts):
                        exactly.append(Exactly(anchor, distinct_opts(n_opts, k_exact), k_exact))

    # "All different": N terms on N distinct entities, in N pairwise-DISTINCT
    # categories — two same-category terms differ by definition, so allowing a
    # repeat would pad the clue with a vacuous pair ("7 coins and 13 coins belong
    # to different artisans"). Every pairwise fact is informative this way, at the
    # cost of capping N at the category count. N >= 3 (N == 2 is a Negative).
    for size in alldiff_sizes if enable_alldiff else ():
        if not 3 <= size <= min(n, k):
            continue
        for _ in range(4 * n):
            ents = rng.sample(range(n), size)
            cats = rng.sample(range(k), size)
            alldiff.append(
                AllDifferent([(cats[i], X[ents[i]][cats[i]]) for i in range(size)])
            )

    # Exclusive pairing: exactly K of N positive links hold. A true link joins
    # two terms on one entity; a false link joins two entities. K defaults to
    # `pairing_k`; with `pairing_two_prob` a 3-link draw can roll K == 2
    # ("exactly two of these are true") — extreme-tier flavour.
    for size in pairing_sizes if enable_pairing else ():
        if not 1 <= pairing_k < size:  # keep it ambiguous (never all-true/all-false)
            continue
        for _ in range(3 * n):
            k_draw = pairing_k
            if 2 < size and rng.random() < pairing_two_prob:
                k_draw = 2
            links = []
            for _ in range(k_draw):
                c1, c2 = rng.sample(range(k), 2)
                e = rng.randrange(n)
                links.append(((c1, X[e][c1]), (c2, X[e][c2])))
            for _ in range(size - k_draw):
                c1, c2 = rng.sample(range(k), 2)
                e1, e2 = rng.sample(range(n), 2)
                links.append(((c1, X[e1][c1]), (c2, X[e2][c2])))
            canon = {tuple(sorted(link)) for link in links}
            if len(canon) < size:  # a repeated link: intra-clue redundancy
                continue
            # Mostly independent alternatives ("A–X or B–Y"), plus a minority
            # of overlapping draws (a shared value "A–X or B–X", or a chain
            # "A–X or X–B") kept for texture. All-shared was the original
            # monotony (and reads like EitherOr / the Compound disjunction);
            # all-distinct was tried and is its own monotony.
            terms = [t for link in links for t in link]
            if len(set(terms)) == 2 * size or rng.random() < _PAIRING_OVERLAP_PROB:
                pairing.append(ExactlyKLinks(links, k_draw))

    # Group match: a left and right group cover the same N entities, paired in
    # unknown order ("between A and B, one is C..."). The categories are split
    # into disjoint left/right pools, so each group may span several categories
    # (e.g. a Pastry and a Customer) yet the two sides never share one — which
    # would otherwise read as "a Drink goes with another Drink".
    for size in match_sizes if enable_match else ():
        if not 2 <= size <= n:
            continue
        for _ in range(3 * n):
            ents = rng.sample(range(n), size)
            shuffled = list(range(k))
            rng.shuffle(shuffled)
            cut = rng.randint(1, k - 1)  # both pools non-empty
            left_cats, right_cats = shuffled[:cut], shuffled[cut:]
            left, right = [], []
            for e in ents:
                cl = rng.choice(left_cats)
                cr = rng.choice(right_cats)
                left.append((cl, X[e][cl]))
                right.append((cr, X[e][cr]))
            match.append(GroupMatch(left, right))

    # Conditional clues: "if {ante}, then {cons}" / "{ante} if and only if {cons}",
    # where ante and cons are embedded boolean *statements* over links (Link with
    # Not/And/Or/Xor). Both sides are built to the SAME truth under X, which keeps
    # every clue true and gives it a live trigger (both-true => modus ponens,
    # both-false => contrapositive; the biconditional holds either way). The
    # statement's nesting depth (`budget`) is sampled so most conditionals stay
    # simple (atom => atom, the classic implication/iff) and compound ones are
    # rarer — the grader then sorts puzzles by the reasoning each actually needs,
    # so complexity tracks measured difficulty. Hard only, n >= 3 so links don't
    # collapse to a 2-item equivalent.
    if enable_conditional and n >= 3 and k >= 3:
        # Grouped categories let a leaf be a GROUP instead of a named instance, so
        # "someone in the Hill Ward goes with X" can sit inside a conditional /
        # and / or / xor exactly like an ordinary link.
        cond_grouped = _grouped_categories(theme) if enable_group_instances else []

        def fresh_link(truth: bool, used: set):
            """A Link of the given truth under X whose atoms don't collide with
            this statement's other atoms. Two guards live in `used`: the cell key
            (a clue never repeats or negates its own atom) and the two *line* keys
            (term, other-category) — two atoms about one term in one category are
            partially decided by each other under the bijection, so allowing them
            can produce clues that are vacuous ("if Latte goes with the Bagel,
            then Latte does not go with the Scone") or disguised negatives."""
            for _ in range(16):
                c1, c2 = rng.sample(range(k), 2)
                if truth:
                    e = rng.randrange(n)
                    a, b = (c1, X[e][c1]), (c2, X[e][c2])
                else:
                    e1, e2 = rng.sample(range(n), 2)
                    a, b = (c1, X[e1][c1]), (c2, X[e2][c2])
                key = tuple(sorted((a, b)))
                lines = {("line", a, b[0]), ("line", b, a[0])}
                if key not in used and not (lines & used):
                    used.add(key)
                    used |= lines
                    return Link(a, b)
            return None

        def fresh_group_link(truth: bool, used: set):
            """A GroupLink leaf of the given truth: pick a grouped category and an
            anchor entity, then a group that does (truth) or does not (not truth)
            contain that entity's grouped item. Fresh per statement via `used`,
            including the (anchor, grouped-category) line key — groups partition
            the category, so two group atoms on one anchor (or a group atom plus a
            plain link into the grouped category) decide each other."""
            for _ in range(16):
                gc, labels, parts, group_of = rng.choice(cond_grouped)
                e = rng.randrange(n)
                gi = group_of.get(X[e][gc])
                if gi is None:
                    continue
                if not truth:
                    others = [j for j in range(len(parts)) if j != gi]
                    if not others:
                        continue
                    gi = rng.choice(others)
                co = rng.choice([c for c in range(k) if c != gc])
                anchor = (co, X[e][co])
                key = ("g", anchor, gc, gi)
                line = ("line", anchor, gc)
                if key not in used and line not in used:
                    used.add(key)
                    used.add(line)
                    return GroupLink(anchor, gc, labels[gi], parts[gi], subject=rng.random() < 0.5)
            return None

        def part_truths(op: str, target: bool, size: int):
            """Per-part truths so an `op` of `size` parts evaluates to `target`."""
            if op == "and":  # true iff all true; else exactly one part flips
                base = [True] * size if target else [False] + [True] * (size - 1)
            else:            # or: false iff all false; else exactly one part true
                base = [True] + [False] * (size - 1) if target else [False] * size
            rng.shuffle(base)
            return base

        def atom(target: bool, used: set):
            """A leaf: a (possibly negated, ~30%) link or group-membership of the
            given truth. A grouped leaf — a *group as instance* — appears ~25% of
            the time when the theme has groups."""
            if cond_grouped and rng.random() < 0.25:
                if rng.random() < 0.7:
                    g = fresh_group_link(target, used)
                else:
                    inner = fresh_group_link(not target, used)
                    g = Not(inner) if inner is not None else None
                if g is not None:
                    return g
            if rng.random() < 0.7:
                return fresh_link(target, used)
            inner = fresh_link(not target, used)
            return Not(inner) if inner is not None else None

        def build_stmt(target: bool, compound: bool, used: set):
            """A Statement with value(X) == target. When `compound`, one boolean
            operator over atom/negated-atom leaves (nesting capped at that for
            readability); otherwise a bare atom. None if atoms run out."""
            if not compound:
                return atom(target, used)
            op = rng.choice(("and", "or", "xor"))
            if op == "xor":  # true iff the two leaves differ
                if target:
                    pair = [True, False]
                    rng.shuffle(pair)
                else:
                    same = rng.random() < 0.5
                    pair = [same, same]
                p, q = atom(pair[0], used), atom(pair[1], used)
                return Xor(p, q) if p is not None and q is not None else None
            size = rng.choice((2, 2, 3))
            parts = [atom(t, used) for t in part_truths(op, target, size)]
            return (And if op == "and" else Or)(parts) if all(parts) else None

        seen_text: set = set()
        for _ in range(16 * n):
            # Bias hard toward simple atom=>atom conditionals (these are the strong,
            # minimization-surviving ones, so they keep conditionals common); a
            # compound side is the rarer, harder layer the grader can price in.
            # `conditional_compound_prob` gates it per tier (0 = atom=>atom only) —
            # compound sides push the parse cost hard, so only the extreme tiers
            # (giga/tera) offer them at all.
            ante_compound = rng.random() < conditional_compound_prob
            cons_compound = rng.random() < conditional_compound_prob
            biconditional = rng.random() < 0.35
            same_truth = rng.random() < 0.5  # both-true vs both-false (both are valid)
            used: set = set()
            ante = build_stmt(same_truth, ante_compound, used)
            cons = build_stmt(same_truth, cons_compound, used)
            if ante is None or cons is None:
                continue
            clue = Conditional(ante, cons, biconditional)
            if not clue.holds(X):  # construction guarantees this; guard anyway
                continue
            txt = clue.text(theme)
            if txt in seen_text:
                continue
            seen_text.add(txt)
            conditional.append(clue)

    # Bare two-link disjunctions with independent predicates — "either A goes
    # with X, or B goes with Y" read INCLUSIVELY (at least one holds; Or.text
    # brackets it), the complement of the exclusive pairing. No groups needed;
    # rides the conditional gate (rich tiers up). Triviality, duplicate sides,
    # and cross-family restatements are all left to _semantic_screen.
    if enable_conditional and k >= 2 and n >= 2:
        for _ in range(3 * n):
            c1, c2 = rng.sample(range(k), 2)
            et = rng.randrange(n)
            true_link = Link((c1, X[et][c1]), (c2, X[et][c2]))
            c3, c4 = rng.sample(range(k), 2)
            ea, eb = rng.sample(range(n), 2)
            other = Link((c3, X[ea][c3]), (c4, X[eb][c4]))  # false under X
            two = [true_link, other]
            rng.shuffle(two)
            clue = Compound(Or(two))
            if clue.holds(X):
                compounds.append(clue)

    # Group-instance disjunctions: a bare "either {named instance} or {someone in a
    # group}" clue — the group standing in as an alternative instance for the same
    # predicate. Built as Or/Xor over a Link and a GroupLink, with exactly one side
    # true under X so the clue actually bites (the solver forces the other side once
    # it rules one out). Needs a grouped category and n >= 3.
    if enable_group_instances and n >= 3 and k >= 2:
        seen_comp: set = set()
        for gc, labels, parts, group_of in _grouped_categories(theme):
            for _ in range(4 * n):
                qc = rng.choice([c for c in range(k) if c != gc])
                eq = rng.randrange(n)  # the entity holding the shared predicate Q
                pred = (qc, X[eq][qc])
                gi = group_of.get(X[eq][gc])
                if gi is None:
                    continue
                pc = rng.choice([c for c in range(k) if c != qc])
                if rng.random() < 0.5:  # the GROUP branch is the true one
                    ep = rng.choice([e for e in range(n) if e != eq])
                    # (A named link subsumed by the existential — the disjunction
                    # collapsing to its group branch — is rejected semantically by
                    # _semantic_screen's branch-subsumption check.)
                    link = Link((pc, X[ep][pc]), pred)  # false: a different entity
                    grp = GroupLink(pred, gc, labels[gi], parts[gi], subject=True)
                else:  # the NAMED branch is the true one
                    others = [j for j in range(len(parts)) if j != gi]
                    if not others:
                        continue
                    gj = rng.choice(others)
                    link = Link((pc, X[eq][pc]), pred)  # true: same entity
                    grp = GroupLink(pred, gc, labels[gj], parts[gj], subject=True)
                stmt = Xor(link, grp) if rng.random() < 0.5 else Or([link, grp])
                clue = Compound(stmt)
                if not clue.holds(X):  # exactly one side true -> guard anyway
                    continue
                txt = clue.text(theme)
                if txt in seen_comp:
                    continue
                seen_comp.add(txt)
                compounds.append(clue)

            # Mixed-predicate variant: the named link and the group existential
            # each constrain a DIFFERENT predicate ("either Beatrix goes with
            # Rope, or someone in the Hill Ward pays 14 coins") — the two
            # alternatives are fully independent facts.
            for _ in range(4 * n):
                qc_g = rng.choice([c for c in range(k) if c != gc])
                eg = rng.randrange(n)
                gi = group_of.get(X[eg][gc])
                if gi is None:
                    continue
                grp_true = rng.random() < 0.5
                if grp_true:
                    grp = GroupLink((qc_g, X[eg][qc_g]), gc, labels[gi], parts[gi], subject=True)
                else:
                    others = [j for j in range(len(parts)) if j != gi]
                    if not others:
                        continue
                    gj = rng.choice(others)
                    grp = GroupLink((qc_g, X[eg][qc_g]), gc, labels[gj], parts[gj], subject=True)
                c1 = rng.randrange(k)
                c2 = rng.choice([c for c in range(k) if c != c1])
                if grp_true:  # named side false: terms from two entities
                    e1, e2 = rng.sample(range(n), 2)
                else:  # named side true: one entity's own terms
                    e1 = e2 = rng.randrange(n)
                link = Link((c1, X[e1][c1]), (c2, X[e2][c2]))
                stmt = Xor(link, grp) if rng.random() < 0.5 else Or([link, grp])
                clue = Compound(stmt)
                if not clue.holds(X):
                    continue
                txt = clue.text(theme)
                if txt in seen_comp:
                    continue
                seen_comp.add(txt)
                compounds.append(clue)

        # Group-UNIVERSAL disjunctions: "either {a named entity belongs to guild B}
        # or {all members of ward A belong to guild B}" — a whole group standing in
        # as an instance via GroupSubset. Needs two partitions (the ward supplies A,
        # the guild supplies the shared target B). One branch is true under X.
        grouped = _grouped_categories(theme)
        for ia in range(len(grouped)):
            for ib in range(len(grouped)):
                if ia == ib:
                    continue
                ca, labs_a, parts_a, _ = grouped[ia]
                cb, labs_b, parts_b, _ = grouped[ib]
                for _ in range(3 * n):
                    gb = rng.randrange(len(parts_b))
                    B = parts_b[gb]
                    ga = rng.randrange(len(parts_a))
                    A = parts_a[ga]
                    a_ents = [e for e in range(n) if X[e][ca] in A]
                    if not a_ents:
                        continue
                    subset_true = all(X[e][cb] in set(B) for e in a_ents)
                    # the named branch "<subject> belongs to guild B": make it the
                    # true branch unless the universal already is (keep exactly one).
                    pool_named = (
                        [e for e in range(n) if X[e][cb] not in set(B)] if subset_true
                        else [e for e in range(n) if X[e][cb] in set(B)]
                    )
                    if not pool_named:
                        continue
                    e2 = rng.choice(pool_named)
                    named = GroupLink((0, X[e2][0]), cb, labs_b[gb], B, subject=False)
                    univ = GroupSubset(ca, A, labs_a[ga], cb, B, labs_b[gb])
                    stmt = Xor(named, univ) if rng.random() < 0.5 else Or([named, univ])
                    clue = Compound(stmt)
                    if not clue.holds(X):
                        continue
                    txt = clue.text(theme)
                    if txt in seen_comp:
                        continue
                    seen_comp.add(txt)
                    compounds.append(clue)

    # Hierarchy / group clues over a grouped category (e.g. Trade -> Guild). The
    # group is just a partition of that column's items, so these resolve on the
    # ordinary grid; they only exist when the theme attached a grouping. Needs
    # >= 2 groups present (sampled) to say anything non-trivial.
    for cat in range(k) if enable_groups else ():
        catobj = theme.categories[cat]
        if not catobj.has_groups:
            continue
        labels = [label for label, _ in catobj.groups]
        parts = [tuple(catobj.items.index(m) for m in members) for _, members in catobj.groups]
        if len(parts) < 2:
            continue
        group_of = {x: gi for gi, members in enumerate(parts) for x in members}
        noun = catobj.group_noun
        non_cat = [co for co in range(k) if co != cat]

        def anchor_for(e):  # name entity e by a random non-grouped category
            co = rng.choice(non_cat)
            return (co, X[e][co])

        for e in range(n):  # "X belongs to the <guild>" / "X does not belong to <guild>"
            gi = group_of.get(X[e][cat])
            if gi is None:
                continue
            groups.append(InGroup(anchor_for(e), cat, labels[gi], parts[gi]))
            # a guild this entity is NOT in (negative membership)
            others = [gj for gj in range(len(parts)) if gj != gi]
            if others:
                gj = rng.choice(others)
                groups.append(NotInGroup(anchor_for(e), cat, labels[gj], parts[gj]))

        for e1 in range(n):  # same- / different-group over entity pairs
            for e2 in range(e1 + 1, n):
                g1, g2 = group_of.get(X[e1][cat]), group_of.get(X[e2][cat])
                if g1 is None or g2 is None:
                    continue
                a, b = anchor_for(e1), anchor_for(e2)
                if g1 == g2:
                    groups.append(SameGroup(a, b, cat, noun, parts))
                else:
                    groups.append(DiffGroup(a, b, cat, noun, parts))

        # Cardinality clues: pick a subset of entities and a guild, count how many
        # of them are in it, and state it as exactly / at least / at most K. These
        # are the genuinely new "set" clues a bijection can't otherwise express.
        ents = list(range(n))
        for _ in range(2 * n):  # a handful of candidates; minimize keeps the useful ones
            size = rng.randint(2, min(4, n))
            subset = rng.sample(ents, size)
            gi = rng.randrange(len(parts))
            actual = sum(1 for e in subset if group_of.get(X[e][cat]) == gi)
            anchors = [anchor_for(e) for e in subset]
            # A true statement about this subset, phrased so it carries genuine "which
            # ones?" ambiguity. A bound that forces every anchor IN (K == size) or
            # every anchor OUT (K == 0) is just a conjunction of memberships in
            # disguise — the InGroup clues already say that — and reads as a fake
            # set-counting puzzle ("at least two of [two things]"). So K stays
            # strictly inside 1..size-1 for every mode; true K must also respect the
            # actual count (>= for atmost, <= for atleast).
            choices = []
            if 1 <= actual <= size - 1:                  # exactly K (not all / none)
                choices.append(("exactly", actual))
            hi = min(actual, size - 1)                    # at least K: K <= actual, < size
            if hi >= 1:
                choices.append(("atleast", rng.randint(1, hi)))
            lo = max(actual, 1)                           # at most K: K >= actual, >= 1
            if lo <= size - 1:
                choices.append(("atmost", rng.randint(lo, size - 1)))
            if not choices:                               # all-in / all-out subset -> skip
                continue
            mode, kk = rng.choice(choices)
            groups.append(GroupCount(anchors, cat, labels[gi], parts[gi], kk, mode))

        # Rare: couple the hierarchy to an ordered category. Only emit when two
        # guilds happen to be fully rank-separated under the true solution, so it
        # surfaces seldom — but when it does it's a genuine cross-group ordering.
        ocats = [c for c in range(k) if c != cat and theme.categories[c].ordered]
        order_cands = []
        for ocat in ocats:
            for g1 in range(len(parts)):
                for g2 in range(len(parts)):
                    if g1 == g2:
                        continue
                    clue = GroupOrder(cat, ocat, parts[g1], parts[g2], labels[g1], labels[g2])
                    if clue.holds(X):  # true (fully separated) under this solution
                        order_cands.append(clue)
        rng.shuffle(order_cands)
        groups.extend(order_cands[:2])  # keep it sparse

    # Cross-group clues: when two categories are both grouped, relate the two
    # hierarchies — counts and comparisons over the cross-tabulation that a single
    # partition can't express. Only possible when a second partition is present.
    if enable_groups:
        ginfo = {}
        for cat in range(k):
            co = theme.categories[cat]
            if co.has_groups:
                labs = [lab for lab, _ in co.groups]
                prts = [tuple(co.items.index(m) for m in mem) for _, mem in co.groups]
                if len(prts) >= 2:
                    ginfo[cat] = (labs, prts)
        gcats = sorted(ginfo)
        gidx = {c: {x: gi for gi, mem in enumerate(ginfo[c][1]) for x in mem} for c in gcats}

        def grp(cat, e):  # which group of `cat` entity e is in (or None)
            return gidx[cat].get(X[e][cat])

        for ci in range(len(gcats)):
            for cj in range(ci + 1, len(gcats)):
                c1, c2 = gcats[ci], gcats[cj]
                labs1, prts1 = ginfo[c1]
                labs2, prts2 = ginfo[c2]
                # "exactly/at least/at most K members of group A are in group B"
                cc = []
                for ga in range(len(prts1)):
                    for gb in range(len(prts2)):
                        actual = sum(1 for e in range(n) if grp(c1, e) == ga and grp(c2, e) == gb)
                        cap = min(len(prts1[ga]), len(prts2[gb]))  # most that could overlap
                        opts = [("exactly", actual)]
                        if actual >= 1:
                            opts.append(("atleast", rng.randint(1, actual)))
                        if actual <= cap - 1:
                            opts.append(("atmost", rng.randint(actual, cap - 1)))
                        mode, kk = rng.choice(opts)
                        cc.append(GroupGroupCount(c1, prts1[ga], labs1[ga], c2, prts2[gb], labs2[gb], kk, mode))
                rng.shuffle(cc)
                cross.extend(cc[:3])
                # "more members of A than B are in the shared group C" (both directions)
                cmp = []
                for (cs, labs_s, prts_s), (cg, labs_g, prts_g) in (
                    ((c1, labs1, prts1), (c2, labs2, prts2)),
                    ((c2, labs2, prts2), (c1, labs1, prts1)),
                ):
                    for gc in range(len(prts_g)):
                        for ga in range(len(prts_s)):
                            for gb in range(len(prts_s)):
                                if ga == gb:
                                    continue
                                ca = sum(1 for e in range(n) if grp(cs, e) == ga and grp(cg, e) == gc)
                                cb = sum(1 for e in range(n) if grp(cs, e) == gb and grp(cg, e) == gc)
                                if ca > cb:
                                    cmp.append(GroupGroupCompare(
                                        cs, prts_s[ga], labs_s[ga], prts_s[gb], labs_s[gb],
                                        cg, prts_g[gc], labs_g[gc]))
                rng.shuffle(cmp)
                cross.extend(cmp[:2])

    # General set-composition cardinality: "exactly/at least/at most K of <union of
    # named entities and whole groups> are associated with <a group or an item set>"
    # — a group, or "N members of a group", standing in wherever an instance can.
    # Subjects always include >= 1 group; K is non-degenerate (strictly interior, so
    # it never collapses to all/none) and true under X.
    if enable_set_count and n >= 3:
        grouped = _grouped_categories(theme)
        seen_sc: set = set()
        for _ in (range(6 * n) if grouped else ()):
            gc, glabels, gparts, _gof = rng.choice(grouped)
            ga = rng.randrange(len(gparts))
            subjects = [("group", gc, gparts[ga], glabels[ga])]
            # target first: another group (60%) or a small item set in some other
            # category — named subjects below must avoid the target's category.
            other = [g for g in grouped if g[0] != gc]
            if other and rng.random() < 0.6:
                tc, tlabels, tparts, _ = rng.choice(other)
                ti = rng.randrange(len(tparts))
                target_cells = [(tc, m) for m in tparts[ti]]
                tlabel, tgrp = tlabels[ti], True
            else:
                tcands = [c for c in range(1, k) if c != gc]
                if not tcands:
                    continue
                tc = rng.choice(tcands)
                its = rng.sample(range(n), 2)
                names = [theme.categories[tc].items[i] for i in its]
                target_cells = [(tc, i) for i in its]
                tlabel, tgrp = f"{names[0]} or {names[1]}", False
            # Named entities may join the union, but never named by the grouped
            # category (membership in the subject union would be a given) nor by
            # the target category (whether it hits the target would be decidable
            # a priori) — either way the term would be dead weight or a red herring.
            ecands = [c for c in range(k) if c not in (gc, tc)]
            if ecands and rng.random() < 0.5:  # mix in 1-2 named entities
                for _ in range(rng.randint(1, 2)):
                    ec = rng.choice(ecands)
                    term = (ec, X[rng.randrange(n)][ec])
                    if ("entity", term) not in subjects:
                        subjects.append(("entity", term))
            # distinct subject entities under X, then a true & non-degenerate K
            ents: set = set()
            for sub in subjects:
                if sub[0] == "entity":
                    ents.add(entity_of(X, sub[1]))
                else:
                    ms = set(sub[2])
                    ents.update(e for e in range(n) if X[e][sub[1]] in ms)
            size = len(ents)
            if size < 2:
                continue
            tset = set(target_cells)
            actual = sum(1 for e in ents if any(X[e][c] == i for c, i in tset))
            choices = []
            if 1 <= actual <= size - 1:
                choices.append(("exactly", actual))
            hi = min(actual, size - 1)
            if hi >= 1:
                choices.append(("atleast", rng.randint(1, hi)))
            lo = max(actual, 1)
            if lo <= size - 1:
                choices.append(("atmost", rng.randint(lo, size - 1)))
            if not choices:
                continue
            mode, kk = rng.choice(choices)
            clue = SetCount(subjects, target_cells, tlabel, tgrp, kk, mode)
            if not clue.holds(X):
                continue
            txt = clue.text(theme)
            if txt in seen_sc:
                continue
            seen_sc.add(txt)
            set_counts.append(clue)

    rng.shuffle(negatives)
    rng.shuffle(comparisons)
    rng.shuffle(among)
    rng.shuffle(either)
    rng.shuffle(neither)
    rng.shuffle(alldiff)
    rng.shuffle(pairing)
    rng.shuffle(match)
    rng.shuffle(atmost)
    rng.shuffle(exactly)
    rng.shuffle(conditional)
    rng.shuffle(groups)
    rng.shuffle(cross)
    rng.shuffle(compounds)
    rng.shuffle(set_counts)
    pool = (
        positives
        + negatives[:max_negatives]
        + comparisons[:max_comparisons]
        + among[:max_among]
        + either[:max_either]
        + neither[:max_neither]
        + alldiff[:max_alldiff]
        + pairing[:max_pairing]
        + match[:max_match]
        + atmost[:max_atmost]
        + exactly[:max_exactly]
        + conditional[: 2 * max_conditional]
        + groups[:max_groups]
        + cross[:max_cross]
        + compounds[:max_compounds]
        + set_counts[:max_set_count]
    )
    return _semantic_screen(theme, X, rng, pool)


# The named tiers, easiest first (see deduce.DIFFICULTY_ORDER / band_of). The
# *measured* difficulty (technique a solve forces) is what separates the tiers;
# the clue pool below only sets which clue families are even available.
DIFFICULTIES = ("normal", "hard", "mega", "giga", "tera")

# Which clue families each tier draws from. `normal` stays direct (is / is-not +
# same-category "one of two"); `hard` adds either-or / neither / all-different /
# groups / sequential; `mega`/`giga`/`tera` unlock the trickiest (at-least-K,
# exclusive pairing, group match, conditionals) — they share one rich pool and
# are pulled apart purely by the measured band the grader assigns. The one
# extreme-only extra: *compound* conditionals (a boolean and/or/xor side inside
# an if-then/iff) carry a heavy parse load for humans, so mega keeps
# conditionals atom=>atom and only giga/tera roll compound sides.
_NORMAL_POOL = dict(  # is / is-not only -> solvable by transitivity (no clue tricks)
    enable_among=False, enable_either=False, enable_neither=False,
    enable_alldiff=False, multi_match=False,
    enable_pairing=False, enable_match=False, enable_atmost=False,
    enable_exactly=False,
)
_HARD_POOL = dict(
    among_sizes=(2, 3), enable_either=True, enable_neither=True,
    enable_alldiff=True, multi_match=False,
    enable_pairing=False, enable_match=False,
    enable_groups=True,  # only fires when a theme attached a grouping
    include_sequential=True,  # only fires when an ordered category exists
)
_RICH_POOL = dict(
    among_sizes=(2, 3), enable_either=True, enable_neither=True,
    enable_alldiff=True, multi_match=True,
    enable_pairing=True, enable_match=True,
    enable_conditional=True,  # if-then / iff (conditional reasoning)
    conditional_compound_prob=0.0,  # atom=>atom only; compounds are extreme-tier
    enable_groups=True,
    enable_group_instances=True,  # groups as instances inside disjunctions / conditionals
    enable_set_count=True,  # cardinality over unions of set instances
    include_sequential=True,
)
# giga/tera additionally roll compound conditional sides ("if both A and B, then
# …") — the heaviest clue to read — and "exactly two of these three" pairings,
# reserved for the most extreme tiers.
_EXTREME_POOL = {**_RICH_POOL, "conditional_compound_prob": 0.28, "pairing_two_prob": 0.3}
_DIFFICULTY_POOL = {
    "normal": _NORMAL_POOL,
    "hard": _HARD_POOL,
    "mega": _RICH_POOL,
    "giga": _EXTREME_POOL,
    "tera": _EXTREME_POOL,
}

# Extra redundant clues as a fraction of the minimal set. `normal` hands back more
# (shorter chains); every harder tier stays minimal so the reasoning bites. The
# actual difficulty is *measured* by `grade`, so generate-and-grade selects by band.
_DIFFICULTY_EXTRA = {"normal": 0.6, "hard": 0.0, "mega": 0.0, "giga": 0.0, "tera": 0.0}


# Cap the uniqueness search per drop-attempt so minimize stays fast even on
# large grids; if a drop can't be confirmed unique within budget we keep the
# clue (the result stays unique, just slightly less minimal).
_MINIMIZE_NODE_BUDGET = 20000

# Diversity reserve: per tier, (depth, complexity_last) — how many clues OF
# EACH SUBSTANTIVE SHAPE minimize keeps to the very end of the removal order
# (chosen at random per puzzle), and whether that reserved block is ordered by
# reading complexity so the most intricate shapes survive best. Greedy
# minimization structurally selects against intricate clues — a cheaper clue
# can usually stand in — so without a reserve whole families stop shipping
# (measured on King's Guild censuses: pairings survived in ~4/30 puzzles,
# conditionals ~3/30). The reserve is data-driven — every clue type present in
# the pool participates, no curated type lists — except that direct facts
# (clue_cost below _RESERVE_MIN_COST: Positive, Negative) never need
# protecting and would only dilute harder tiers. complexity_last applies where
# complexity is a goal (the rich tiers): without it, abundant strong simple
# clues (sequential comparisons) crowd out the rare complex families; WITH it
# at hard, the cheap-to-read hierarchy clues get evicted instead, so hard
# keeps a random-order reserve. Protecting ALL clues of a type was tried and
# overshot (the ceiling-5 population slid from 18% mega / 51% giga / 31% tera
# to 6/29/65, starving the mega attempt budget).
_RESERVE = {
    "normal": (0, False),
    "hard": (2, False),
    "mega": (1, True),
    "giga": (2, True),
    "tera": (2, True),
}
_RESERVE_MIN_COST = 1.5  # direct is/is-not facts sit below; everything else above


def minimize(
    theme: Theme,
    clues: list,
    rng: random.Random,
    reserve: int = 0,
    complexity_last: bool = False,
) -> list:
    """Greedily remove clues while uniqueness is preserved.

    A clue set is locally minimal once no further single clue can be dropped.
    Removal order is randomised so the surviving minimal set varies between
    seeds; difficulty is then selected by ``generate_rated`` measuring the band,
    which keeps calibration honest. The one deliberate skew is the diversity
    reserve (see _RESERVE): up to `reserve` randomly-chosen clues of every
    substantive shape present are considered for removal last, so a puzzle
    that can keep a hierarchy clue, a cross-pair either/or, or a conditional
    tends to. This is safe because those clues carry real deductive weight, so
    keeping them doesn't push the measured band down — protecting *all* clues
    of the interesting shapes was tried twice and both times skewed the
    population (see the _RESERVE note).
    """
    removal_order = list(clues)
    rng.shuffle(removal_order)
    # post-shuffle first `reserve` of a shape == that many uniformly-random ones
    reserved: set = set()
    if reserve:
        taken: dict = {}
        for c in removal_order:
            name = type(c).__name__
            if clue_cost(c) < _RESERVE_MIN_COST:
                continue  # direct facts never need protecting
            if taken.get(name, 0) < reserve:
                taken[name] = taken.get(name, 0) + 1
                reserved.add(id(c))
    # With complexity_last, the reserve tries its cheapest reading for removal
    # first, so the most intricate shapes survive best (see the _RESERVE note).
    removal_order.sort(
        key=lambda c: (1, clue_cost(c) if complexity_last else 0.0)
        if id(c) in reserved
        else (0, 0.0)
    )

    current = list(clues)
    for cl in removal_order:
        trial = [c for c in current if c is not cl]
        if is_unique(theme, trial, max_nodes=_MINIMIZE_NODE_BUDGET):
            current = trial
    return current


def generate_puzzle(theme: Theme, rng: random.Random, difficulty: str = "normal") -> Puzzle:
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"unknown difficulty: {difficulty!r}")
    theme.validate()
    X = random_solution(theme, rng)
    pool = build_clue_pool(theme, X, rng, **_DIFFICULTY_POOL[difficulty])
    # positives alone pin the solution, so the full pool is necessarily unique
    if count_solutions(theme, pool, cap=2) != 1:
        raise RuntimeError("clue pool failed to yield a unique solution (internal error)")

    depth, complexity_last = _RESERVE[difficulty]
    best = minimize(theme, pool, rng, reserve=depth, complexity_last=complexity_last)
    clues = list(best)
    extra_frac = _DIFFICULTY_EXTRA[difficulty]
    if extra_frac > 0:  # easy: hand back extra true clues so less inference is needed
        chosen = {id(c) for c in best}
        extras = [c for c in pool if id(c) not in chosen]
        rng.shuffle(extras)
        clues += extras[: round(extra_frac * len(best))]
    rng.shuffle(clues)
    return Puzzle(theme=theme, solution=X, clues=clues)


# Sampling budget per target. The ceiling-5 population split depends on the
# target's diversity reserve (see _RESERVE): a deeper, complexity-ordered
# reserve keeps more intricate clues in the shipped set, shifting that pool
# toward the harder bands the request wants anyway. Re-measure with
# `python -m logicgrid.census --calibration` after touching pools, the screen,
# or the reserve (latest: 97/100 exact across the five bands, tera 20/20).
# Tera also recovers ambiguous candidates via the nested-what-if re-grade,
# widening its effective population further.
_RATED_ATTEMPTS = {"normal": 8, "hard": 9, "mega": 16, "giga": 14, "tera": 14}

# Wall-clock cap on the depth-2 Tera-recovery solve. A genuine nested what-if
# refutes well within this (early-exit finds the first refutation fast); only a
# depth-3 puzzle — which we don't ship — runs long, so blowing the budget means
# "skip". Generous enough not to drop legitimate recoveries on a large grid.
_TERA_RECOVERY_BUDGET_S = 3.0


def generate_rated(make_theme, rng: random.Random, target: str, max_attempts: int | None = None):
    """Generate-and-grade: sample candidates until one's *measured* difficulty
    band matches `target`, guaranteeing a logic-solvable (no-guessing) puzzle.

    `make_theme(rng)` builds a (possibly randomized) theme per attempt. Returns
    (theme, puzzle, report).

    Grading runs at a single what-if (depth 1) by default — cheap, and enough to
    place normal..giga. `tera` is the *catch-all* for anything harder: when a
    candidate stalls at depth 1 (graded `ambiguous`) on a `tera` request, it is
    re-graded at depth 2 to recover puzzles that need a nested what-if (a what-if
    inside a what-if) rather than discarding them — so the deepest reasoning lands
    in tera instead of the bin. The depth-2 pass is paid only on that stuck
    minority, keeping latency bounded. A candidate still ambiguous at depth 2 needs
    deeper nesting than we verify and is skipped; if the exact band is never hit
    within the attempt budget the closest solvable one is returned, so a tiny grid
    that simply can't reach `tera` degrades gracefully to the hardest it can manage.

    One soft preference: a `hard` request favours candidates that never touch
    tier 4 (grid set logic / expert counting) — 'hard' promises everyday clue
    logic, and ~40% of hard-band candidates would otherwise force one advanced
    forward move. An exact-band match that does touch tier 4 is kept as a backup
    and shipped only if no purer candidate appears within the budget.
    """
    import time

    from .deduce import SolveBudgetExceeded, grade  # local import avoids a module cycle

    if target not in DIFFICULTIES:
        raise ValueError(f"unknown difficulty: {target!r}")
    if max_attempts is None:
        max_attempts = _RATED_ATTEMPTS.get(target, 9)
    order = DIFFICULTIES
    fallback = None
    soft = None  # exact-band match that violates the soft (tier-4-free) preference
    # The attempt budget caps the search for an *exact* band match; the second
    # half of the range only runs in the pathological case where every single
    # candidate graded 'ambiguous' (nothing shippable at all), so we never
    # return None into callers that unpack (theme, puzzle, report).
    for attempt in range(2 * max_attempts):
        if attempt >= max_attempts and (fallback is not None or soft is not None):
            break
        theme = make_theme(rng)
        puzzle = generate_puzzle(theme, rng, difficulty=target)
        report = grade(theme, puzzle.clues)
        if report["band"] == "ambiguous" and target == "tera":
            # Tera catch-all: a puzzle that stalls at depth 1 but solves with a
            # nested what-if is the *deepest* reasoning we ship — recover it instead
            # of binning it. The early-exit (first=True) depth-2 solve is a cheap
            # solvability check (~0.2s vs ~70s exhaustive); being ambiguous at depth
            # 1 already proves it needs more than a single what-if, so it IS tera.
            # A puzzle that needs depth-3, though, makes even the early-exit scan
            # churn for tens of seconds proving no depth-2 refutation exists — so
            # cap it with a wall-clock deadline and skip anything that blows it.
            try:
                deep = grade(theme, puzzle.clues, max_hyp_depth=2, first=True,
                             deadline=time.monotonic() + _TERA_RECOVERY_BUDGET_S)
                if deep["solved"]:
                    deep["band"] = "tera"
                    report = deep
            except SolveBudgetExceeded:
                continue  # too deep to verify cheaply -> not shipping it
        if report["band"] == "ambiguous":
            continue  # needs deeper nesting than we verify — not shipping it
        if report["band"] == target:
            if target != "hard" or not report["steps"][4]:
                return theme, puzzle, report
            # hard, but it forces an advanced tier-4 move — keep hunting for a
            # persona-pure candidate; ship this one only if none appears.
            if soft is None:
                soft = (theme, puzzle, report)
            continue
        # keep the closest-by-band candidate as a fallback
        if fallback is None or abs(order.index(report["band"]) - order.index(target)) < abs(
            order.index(fallback[2]["band"]) - order.index(target)
        ):
            fallback = (theme, puzzle, report)
    if soft is not None:
        return soft
    if fallback is None:
        raise RuntimeError(
            f"no logic-solvable puzzle found for {target!r}: every candidate "
            "needed deeper contradiction nesting than we verify"
        )
    return fallback
