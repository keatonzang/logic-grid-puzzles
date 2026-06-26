"""Puzzle generation: random solution -> clue pool -> minimal unique clue set."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .clues import (
    Adjacent,
    AllDifferent,
    Among,
    Between,
    Diff,
    EitherOr,
    ExactlyKLinks,
    GroupMatch,
    Greater,
    Negative,
    Neither,
    Positive,
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
    same_category_prob: float = 0.5,
    alldiff_sizes: tuple[int, ...] = (3, 4),
    max_alldiff: int = 30,
    pairing_sizes: tuple[int, ...] = (2, 3),
    pairing_k: int = 1,
    max_pairing: int = 25,
    match_sizes: tuple[int, ...] = (2, 3),
    max_match: int = 25,
    enable_negatives: bool = True,
    enable_among: bool = True,
    enable_either: bool = True,
    enable_neither: bool = True,
    enable_alldiff: bool = True,
    enable_pairing: bool = True,
    enable_match: bool = True,
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
    categories) — always ambiguous, never K == N. `same_category_prob` is a
    future difficulty knob: the chance a threshold-1 disjunction draws all its
    options from one category (1.0 forces same-category, 0.0 spreads them).

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
    # higher/lower-than, exact-difference, between, immediately-before/after.
    # Reference terms come from any non-ordered category. Disabled by default.
    for cn in range(k) if include_sequential else ():
        cat = theme.categories[cn]
        if not cat.ordered:
            continue
        refs = [c for c in range(k) if c != cn]

        def ref(e):  # a random non-ordered reference term for entity e
            c = rng.choice(refs)
            return (c, X[e][c])

        rank = {e: X[e][cn] for e in range(n)}            # item index == rank
        by_rank = sorted(range(n), key=lambda e: rank[e])  # entities low -> high

        for e1 in range(n):  # higher-than + exact-difference for every ordered pair
            for e2 in range(n):
                if rank[e1] <= rank[e2]:
                    continue
                a, b = ref(e1), ref(e2)
                comparisons.append(Greater(cn, a, b))
                if cat.values is not None:
                    comparisons.append(
                        Diff(cn, a, b, cat.value(X[e1][cn]) - cat.value(X[e2][cn]), cat.values)
                    )

        for idx in range(n - 1):  # immediately-before/after (consecutive ranks)
            comparisons.append(Adjacent(cn, ref(by_rank[idx]), ref(by_rank[idx + 1])))

        for mid in range(n):  # between: a middle-ranked entity, one below + one above
            lows = [e for e in range(n) if rank[e] < rank[mid]]
            highs = [e for e in range(n) if rank[e] > rank[mid]]
            if lows and highs:
                comparisons.append(
                    Between(cn, ref(rng.choice(lows)), ref(rng.choice(highs)), ref(mid))
                )

    # "One of N" disjunctions over option terms. For each anchor entity e a term
    # (co, io) with co != ca is *true* iff it is e's real item there.
    #
    # make_options rolls each threshold-1 clue's options as either all in one
    # category (probability `same_category_prob`) or spread across categories.
    # All-same-category is only possible at threshold 1; the "at least K" path
    # (K >= 2) below requires distinct categories.
    for e in range(n):
        for ca in range(k):
            anchor = (ca, X[e][ca])
            non_anchor = [co for co in range(k) if co != ca]
            true_terms = [(co, X[e][co]) for co in non_anchor]
            false_terms = [
                (co, io) for co in non_anchor for io in range(n) if io != X[e][co]
            ]

            def make_options(size, include_true):
                """`size` option terms (one true if include_true), or None if
                infeasible. Same-category lists must stay below n items so they
                never cover a whole category (which would be trivially true)."""
                if rng.random() < same_category_prob:
                    co = rng.choice(non_anchor)
                    pool = [i for i in range(n) if i != X[e][co]]
                    need = size - 1 if include_true else size
                    if (include_true and size >= n) or len(pool) < need:
                        return None
                    decoys = [(co, i) for i in rng.sample(pool, need)]
                    return [(co, X[e][co]), *decoys] if include_true else decoys
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

            # "At least K of N" Among over DISTINCT categories. Always ambiguous:
            # K is kept strictly below N (K == N would just be N direct links), so
            # it needs N >= 3 distinct categories. Exactly K options are true.
            if multi_match:
                for n_opts in range(3, len(non_anchor) + 1):
                    for at_least in range(2, n_opts):
                        cats = rng.sample(non_anchor, n_opts)
                        true_cats = set(rng.sample(cats, at_least))
                        opts = [
                            (co, X[e][co])
                            if co in true_cats
                            else (co, rng.choice([i for i in range(n) if i != X[e][co]]))
                            for co in cats
                        ]
                        among.append(Among(anchor, opts, at_least=at_least))

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

    rng.shuffle(negatives)
    rng.shuffle(comparisons)
    rng.shuffle(among)
    rng.shuffle(either)
    rng.shuffle(neither)
    rng.shuffle(alldiff)
    rng.shuffle(pairing)
    rng.shuffle(match)
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
    )


DIFFICULTIES = ("easy", "medium", "hard")

# Which clue families each difficulty draws from. Easy stays direct (is / is-not
# + same-category "one of two"); medium adds either-or / neither / all-different;
# hard unlocks the trickiest (at-least-K, exclusive pairing, group match).
_DIFFICULTY_POOL = {
    "easy": dict(  # is / is-not only -> solvable by transitivity (no clue tricks)
        enable_among=False, enable_either=False, enable_neither=False,
        enable_alldiff=False, multi_match=False,
        enable_pairing=False, enable_match=False,
    ),
    "medium": dict(
        among_sizes=(2, 3), enable_either=True, enable_neither=True,
        enable_alldiff=True, multi_match=False,
        enable_pairing=False, enable_match=False,
        include_sequential=True,  # only fires when an ordered category exists
    ),
    "hard": dict(
        among_sizes=(2, 3), enable_either=True, enable_neither=True,
        enable_alldiff=True, multi_match=True,
        enable_pairing=True, enable_match=True,
        include_sequential=True,
    ),
}

# Extra redundant clues as a fraction of the minimal set. Easy hands back more
# (shorter chains). The actual difficulty is *measured* by `grade`, so we no
# longer over-minimize — generate-and-grade selects by the measured band.
_DIFFICULTY_EXTRA = {"easy": 0.6, "medium": 0.0, "hard": 0.0}


def minimize(theme: Theme, clues: list, rng: random.Random) -> list:
    """Greedily remove clues in random order while uniqueness is preserved.

    A clue set is locally minimal once no further single clue can be dropped.
    Random removal order yields a natural mix of clue types in a compact set.
    """
    removal_order = list(clues)
    rng.shuffle(removal_order)

    current = list(clues)
    for cl in removal_order:
        trial = [c for c in current if c is not cl]
        if is_unique(theme, trial):
            current = trial
    return current


def generate_puzzle(theme: Theme, rng: random.Random, difficulty: str = "medium") -> Puzzle:
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


def generate_rated(make_theme, rng: random.Random, target: str, max_attempts: int = 16):
    """Generate-and-grade: sample candidates until one's *measured* difficulty
    band matches `target`, guaranteeing a logic-solvable (no-guessing) puzzle.

    `make_theme(rng)` builds a (possibly randomized) theme per attempt. Returns
    (theme, puzzle, report). Ambiguous puzzles (need techniques beyond tier 4)
    are skipped; if the exact band is never hit, the closest solvable one is
    returned.
    """
    from .deduce import grade  # local import avoids a module cycle

    if target not in DIFFICULTIES:
        raise ValueError(f"unknown difficulty: {target!r}")
    order = ("easy", "medium", "hard")
    fallback = None
    for _ in range(max_attempts):
        theme = make_theme(rng)
        puzzle = generate_puzzle(theme, rng, difficulty=target)
        report = grade(theme, puzzle.clues)
        if report["band"] == "ambiguous":
            continue  # needs tier 5+ (nested hypotheticals) — not shipping yet
        if report["band"] == target:
            return theme, puzzle, report
        # keep the closest-by-band candidate as a fallback
        if fallback is None or abs(order.index(report["band"]) - order.index(target)) < abs(
            order.index(fallback[2]["band"]) - order.index(target)
        ):
            fallback = (theme, puzzle, report)
    return fallback
