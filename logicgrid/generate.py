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
    Conditional,
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
    Xor,
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
    max_pairing: int = 25,
    match_sizes: tuple[int, ...] = (2, 3),
    max_match: int = 25,
    max_atmost: int = 20,
    max_exactly: int = 20,
    max_conditional: int = 14,
    max_groups: int = 24,
    max_cross: int = 6,
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
                    if opts is not None:
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

    # "All different": N terms on N distinct entities, spanning >= 2 categories
    # (categories may repeat). Generated for N >= 3 (N == 2 would be a Negative).
    for size in alldiff_sizes if enable_alldiff else ():
        if not 3 <= size <= n:
            continue
        for _ in range(4 * n):
            ents = rng.sample(range(n), size)
            cats = [rng.randrange(k) for _ in range(size)]
            if len(set(cats)) < 2:  # force the required >= 2 distinct categories
                j = rng.randrange(size)
                cats[j] = (cats[j] + 1) % k
            alldiff.append(
                AllDifferent([(cats[i], X[ents[i]][cats[i]]) for i in range(size)])
            )

    # Exclusive pairing: exactly `pairing_k` of N positive links hold. A true
    # link joins two terms on one entity; a false link joins two entities.
    for size in pairing_sizes if enable_pairing else ():
        if not 1 <= pairing_k < size:  # keep it ambiguous (never all-true/all-false)
            continue
        for _ in range(3 * n):
            links = []
            for _ in range(pairing_k):
                c1, c2 = rng.sample(range(k), 2)
                e = rng.randrange(n)
                links.append(((c1, X[e][c1]), (c2, X[e][c2])))
            for _ in range(size - pairing_k):
                c1, c2 = rng.sample(range(k), 2)
                e1, e2 = rng.sample(range(n), 2)
                links.append(((c1, X[e1][c1]), (c2, X[e2][c2])))
            clue = ExactlyKLinks(links, pairing_k)
            if len(set(clue.links)) == size:  # skip draws with a repeated link
                pairing.append(clue)

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
        def fresh_link(truth: bool, used: set):
            """A Link of the given truth under X whose cell isn't already used in
            this statement (so a clue never repeats or negates its own atom)."""
            for _ in range(16):
                c1, c2 = rng.sample(range(k), 2)
                if truth:
                    e = rng.randrange(n)
                    a, b = (c1, X[e][c1]), (c2, X[e][c2])
                else:
                    e1, e2 = rng.sample(range(n), 2)
                    a, b = (c1, X[e1][c1]), (c2, X[e2][c2])
                key = tuple(sorted((a, b)))
                if key not in used:
                    used.add(key)
                    return Link(a, b)
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
            """A leaf: a link, or a negated link (~30%), of the given truth."""
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
            ante_compound = rng.random() < 0.28
            cons_compound = rng.random() < 0.28
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
            # a true statement about this subset; vary the relation we phrase it as
            choices = [("exactly", actual)]
            if actual >= 1:
                choices.append(("atleast", rng.randint(1, actual)))
            if actual <= size - 1:
                choices.append(("atmost", rng.randint(actual, size - 1)))
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
    return (
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
    )


# The named tiers, easiest first (see deduce.DIFFICULTY_ORDER / band_of). The
# *measured* difficulty (technique a solve forces) is what separates the tiers;
# the clue pool below only sets which clue families are even available.
DIFFICULTIES = ("normal", "hard", "mega", "giga", "tera")

# Which clue families each tier draws from. `normal` stays direct (is / is-not +
# same-category "one of two"); `hard` adds either-or / neither / all-different /
# groups / sequential; `mega`/`giga`/`tera` unlock the trickiest (at-least-K,
# exclusive pairing, group match, conditionals) — they share one rich pool and
# are pulled apart purely by the measured band the grader assigns.
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
    enable_groups=True,
    include_sequential=True,
)
_DIFFICULTY_POOL = {
    "normal": _NORMAL_POOL,
    "hard": _HARD_POOL,
    "mega": _RICH_POOL,
    "giga": _RICH_POOL,
    "tera": _RICH_POOL,
}

# Extra redundant clues as a fraction of the minimal set. `normal` hands back more
# (shorter chains); every harder tier stays minimal so the reasoning bites. The
# actual difficulty is *measured* by `grade`, so generate-and-grade selects by band.
_DIFFICULTY_EXTRA = {"normal": 0.6, "hard": 0.0, "mega": 0.0, "giga": 0.0, "tera": 0.0}


# Cap the uniqueness search per drop-attempt so minimize stays fast even on
# large grids; if a drop can't be confirmed unique within budget we keep the
# clue (the result stays unique, just slightly less minimal).
_MINIMIZE_NODE_BUDGET = 20000

# Clue types that name a hierarchy/group; minimize keeps these to the end of the
# removal order so they survive into the minimal set more often (see minimize).
_GROUP_CLUES = {
    "InGroup", "SameGroup", "DiffGroup", "NotInGroup", "GroupCount", "GroupOrder",
    "GroupGroupCount", "GroupGroupCompare",
}


def minimize(theme: Theme, clues: list, rng: random.Random) -> list:
    """Greedily remove clues while uniqueness is preserved.

    A clue set is locally minimal once no further single clue can be dropped.
    Removal order is randomised so the surviving minimal set varies between
    seeds; difficulty is then selected by ``generate_rated`` measuring the band,
    which keeps calibration honest. The one deliberate skew: *group* clues are
    considered for removal last, so a puzzle that can keep a hierarchy clue
    tends to (guilds appear in ~half of hard King's Guild puzzles instead of
    ~5%). This is safe because group clues carry real deductive weight, so
    keeping them doesn't push the measured band down — a broader "keep all the
    interesting clues" bias was tried and it skewed medium puzzles to easy.
    """
    removal_order = list(clues)
    rng.shuffle(removal_order)
    removal_order.sort(key=lambda c: 1 if type(c).__name__ in _GROUP_CLUES else 0)

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

    best = minimize(theme, pool, rng)
    clues = list(best)
    extra_frac = _DIFFICULTY_EXTRA[difficulty]
    if extra_frac > 0:  # easy: hand back extra true clues so less inference is needed
        chosen = {id(c) for c in best}
        extras = [c for c in pool if id(c) not in chosen]
        rng.shuffle(extras)
        clues += extras[: round(extra_frac * len(best))]
    rng.shuffle(clues)
    return Puzzle(theme=theme, solution=X, clues=clues)


# Sampling budget per target. With the composite index split into equal tertiles,
# giga/tera are now hit in a few attempts; the laggard is mega — the *easiest*
# third of the contradiction tier, which the rich clue pool produces least often —
# so it gets the largest budget while the once-rare top tiers are trimmed back
# (which also caps their worst-case generation latency).
_RATED_ATTEMPTS = {"normal": 8, "hard": 9, "mega": 16, "giga": 14, "tera": 14}


def generate_rated(make_theme, rng: random.Random, target: str, max_attempts: int | None = None):
    """Generate-and-grade: sample candidates until one's *measured* difficulty
    band matches `target`, guaranteeing a logic-solvable (no-guessing) puzzle.

    `make_theme(rng)` builds a (possibly randomized) theme per attempt. Returns
    (theme, puzzle, report). Ambiguous puzzles (need deeper nesting than the grader
    verifies) are skipped; if the exact band is never hit within the attempt budget
    the closest solvable one is returned, so a tiny grid that simply can't reach
    `tera` degrades gracefully to the hardest it can manage.
    """
    from .deduce import grade  # local import avoids a module cycle

    if target not in DIFFICULTIES:
        raise ValueError(f"unknown difficulty: {target!r}")
    if max_attempts is None:
        max_attempts = _RATED_ATTEMPTS.get(target, 9)
    order = DIFFICULTIES
    fallback = None
    for _ in range(max_attempts):
        theme = make_theme(rng)
        puzzle = generate_puzzle(theme, rng, difficulty=target)
        report = grade(theme, puzzle.clues)
        if report["band"] == "ambiguous":
            continue  # needs deeper nesting than we verify — not shipping it
        if report["band"] == target:
            return theme, puzzle, report
        # keep the closest-by-band candidate as a fallback
        if fallback is None or abs(order.index(report["band"]) - order.index(target)) < abs(
            order.index(fallback[2]["band"]) - order.index(target)
        ):
            fallback = (theme, puzzle, report)
    return fallback
