"""Clue types.

A *term* is a (category_index, item_index) pair. It identifies the unique
entity `e` whose solution has X[e][category] == item. Each clue knows:

  * `involved`  -- frozenset of category indices it reads
  * `holds(X)`  -- whether it is true given a (partially) assigned grid; only
                   the involved columns need be assigned for this to be valid
  * `text(theme)` -- a human-readable phrasing
  * `removal_class` -- 0 positive, 1 comparison, 2 negative; used to bias the
                   minimizer toward dropping easy (positive) clues first.

The grid X[entity][category] uses item indices; column `category` must be a
full permutation for `entity_of` to resolve a term.
"""

from __future__ import annotations

from itertools import combinations

from .model import Contradiction, Theme

Term = tuple[int, int]  # (category_index, item_index)


def entity_of(X: list[list[int]], term: Term) -> int:
    """The entity carrying `item` in `category` (column must be assigned)."""
    cat, item = term
    col = X
    for e in range(len(col)):
        if col[e][cat] == item:
            return e
    raise ValueError(f"term {term} not found; column {cat} not fully assigned?")


def _label(theme: Theme, term: Term) -> str:
    cat, item = term
    return theme.categories[cat].items[item]


def _ref(theme: Theme, term: Term) -> str:
    """Name the entity that `term` identifies, as a noun phrase for clue text.

    The subject category (index 0) IS the entity's identity, so it reads as the
    bare item — a name ("Ava"). Any other category reads as a descriptive phrase:
    the category's ``referent`` template if it has one ("the person studying
    Debate"), else the generic "the {entity_noun} with {item}" ("the order with
    Latte")."""
    cat = theme.categories[term[0]]
    item = cat.items[term[1]]
    if term[0] == 0:
        return item
    if cat.referent:
        return cat.referent.format(item)
    return f"the {theme.entity_noun} with {item}"


def _poss(theme: Theme, term: Term) -> str:
    """Possessive of ``_ref``: "Ava's", "Ellis'", "the person studying Debate's"."""
    ref = _ref(theme, term)
    return ref + ("'" if ref.endswith("s") else "'s")


def _cap(s: str) -> str:
    """Capitalise the first letter (referents may begin with a lowercase "the")."""
    return s[:1].upper() + s[1:]


def _low(s: str) -> str:
    """Lower-case the first letter, for a category name used mid-sentence: the
    catalogue stores Title-Case names ("Price", "Grade"), but in clue prose they
    read as common nouns — "the order with Onyx's price", not "…Onyx's Price"."""
    return s[:1].lower() + s[1:]


def _multi_ordered(theme: Theme) -> bool:
    """Whether the puzzle has more than one ordered category — the case where a
    bare comparison partner ("…next to Dasari") is ambiguous about *which*
    sequential scale is meant."""
    return sum(1 for c in theme.categories if c.ordered) >= 2


def _side(theme: Theme, term: Term, cat: int) -> str:
    """The non-subject side of a sequential comparison on ordered category ``cat``.

    Normally the bare entity reference ("Dasari", "the order with Latte") — the
    scale is already named once on the leading side. But when the puzzle has more
    than one ordered category, restate the dimension on the partner too
    ("Dasari's distance") so it's unambiguous which ranking the comparison reads."""
    if _multi_ordered(theme):
        return f"{_poss(theme, term)} {_low(theme.categories[cat].name)}"
    return _ref(theme, term)


class Clue:
    removal_class = 1
    involved: frozenset

    def holds(self, X) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def text(self, theme: Theme) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class Positive(Clue):
    """`a` and `b` belong to the same entity."""

    removal_class = 0

    def __init__(self, a: Term, b: Term):
        self.a, self.b = a, b
        self.involved = frozenset({a[0], b[0]})

    def holds(self, X) -> bool:
        return entity_of(X, self.a) == entity_of(X, self.b)

    def text(self, theme: Theme) -> str:
        return f"{_label(theme, self.a)} goes with {_label(theme, self.b)}."


class Negative(Clue):
    """`a` and `b` belong to different entities."""

    removal_class = 2

    def __init__(self, a: Term, b: Term):
        self.a, self.b = a, b
        self.involved = frozenset({a[0], b[0]})

    def holds(self, X) -> bool:
        return entity_of(X, self.a) != entity_of(X, self.b)

    def text(self, theme: Theme) -> str:
        return f"{_label(theme, self.a)} does not go with {_label(theme, self.b)}."


class Greater(Clue):
    """Entity of `a` ranks strictly higher in ordered category `cat` than entity of `b`."""

    removal_class = 1

    def __init__(self, cat: int, a: Term, b: Term):
        self.cat, self.a, self.b = cat, a, b
        self.involved = frozenset({cat, a[0], b[0]})

    def holds(self, X) -> bool:
        # ordered categories list items ascending, so item index == rank
        ea, eb = entity_of(X, self.a), entity_of(X, self.b)
        return X[ea][self.cat] > X[eb][self.cat]

    def text(self, theme: Theme) -> str:
        cat = theme.categories[self.cat]
        cn = _low(cat.name)
        if _multi_ordered(theme):
            # Parallel possessive form ("X's placing is higher than Y's placing"),
            # matching the other sequential clues — avoids the doubled-noun read
            # "a higher placing than Y's placing" when the partner restates the scale.
            return f"{_cap(_poss(theme, self.a))} {cn} {cat.verb} {cat.more_word} than {_side(theme, self.b, self.cat)}."
        return f"{_cap(_ref(theme, self.a))} has {cat.article}{cat.more_word} {cn} than {_ref(theme, self.b)}."


class Diff(Clue):
    """Entity of `a` exceeds entity of `b` by exactly `delta` in numeric category `cat`."""

    removal_class = 1

    def __init__(self, cat: int, a: Term, b: Term, delta: int, values: list[int]):
        self.cat, self.a, self.b, self.delta = cat, a, b, delta
        self._values = values
        self.involved = frozenset({cat, a[0], b[0]})

    def holds(self, X) -> bool:
        ea, eb = entity_of(X, self.a), entity_of(X, self.b)
        return self._values[X[ea][self.cat]] - self._values[X[eb][self.cat]] == self.delta

    def text(self, theme: Theme) -> str:
        cat = theme.categories[self.cat]
        return (
            f"{_cap(_poss(theme, self.a))} {_low(cat.name)} {cat.verb} exactly {cat.amount(self.delta)} more "
            f"than {_side(theme, self.b, self.cat)}."
        )


class Between(Clue):
    """Entity of `c` ranks strictly between entities of `a` and `b` in ordered
    category `cat` (endpoints in either order)."""

    removal_class = 1

    def __init__(self, cat: int, a: Term, b: Term, c: Term):
        self.cat, self.a, self.b, self.c = cat, a, b, c
        self.involved = frozenset({cat, a[0], b[0], c[0]})

    def holds(self, X) -> bool:
        ra = X[entity_of(X, self.a)][self.cat]
        rb = X[entity_of(X, self.b)][self.cat]
        rc = X[entity_of(X, self.c)][self.cat]
        return min(ra, rb) < rc < max(ra, rb)

    def text(self, theme: Theme) -> str:
        cat = theme.categories[self.cat]
        cn = _low(cat.name)
        return (
            f"{_cap(_poss(theme, self.c))} {cn} {cat.verb} between {_side(theme, self.a, self.cat)} "
            f"and {_side(theme, self.b, self.cat)}."
        )


class Adjacent(Clue):
    """Entity of `b` ranks exactly one step above entity of `a` in ordered
    category `cat` (immediately before/after)."""

    removal_class = 1

    def __init__(self, cat: int, a: Term, b: Term):
        self.cat, self.a, self.b = cat, a, b
        self.involved = frozenset({cat, a[0], b[0]})

    def holds(self, X) -> bool:
        return X[entity_of(X, self.b)][self.cat] == X[entity_of(X, self.a)][self.cat] + 1

    def text(self, theme: Theme) -> str:
        cat = theme.categories[self.cat]
        cn = _low(cat.name)
        # Default vocabulary keeps the classic "immediately below"; a custom
        # compare pair reads through its lesser word ("immediately earlier than").
        rel = "below" if not cat.compare else f"{cat.less_word} than"
        return f"{_cap(_poss(theme, self.a))} {cn} {cat.verb} immediately {rel} {_side(theme, self.b, self.cat)}."


class NextTo(Clue):
    """Entities of `a` and `b` sit on consecutive ranks in ordered category `cat`
    (|rank difference| == 1) — immediately next to each other, in either
    direction. The undirected sibling of Adjacent."""

    removal_class = 1

    def __init__(self, cat: int, a: Term, b: Term):
        self.cat, self.a, self.b = cat, a, b
        self.involved = frozenset({cat, a[0], b[0]})

    def holds(self, X) -> bool:
        ra = X[entity_of(X, self.a)][self.cat]
        rb = X[entity_of(X, self.b)][self.cat]
        return abs(ra - rb) == 1

    def text(self, theme: Theme) -> str:
        cat = theme.categories[self.cat]
        cn = _low(cat.name)
        return f"{_cap(_poss(theme, self.a))} {cn} {cat.verb} immediately next to {_side(theme, self.b, self.cat)}."


class AtLeastApart(Clue):
    """Entity of `a` exceeds entity of `b` by *at least* `delta` in value — a
    loose, ranged version of exact-difference (an inequality, so it narrows
    rather than pinning)."""

    removal_class = 1

    def __init__(self, cat: int, a: Term, b: Term, delta: int, values: list[int]):
        self.cat, self.a, self.b, self.delta = cat, a, b, delta
        self._values = values
        self.involved = frozenset({cat, a[0], b[0]})

    def holds(self, X) -> bool:
        ea, eb = entity_of(X, self.a), entity_of(X, self.b)
        return self._values[X[ea][self.cat]] - self._values[X[eb][self.cat]] >= self.delta

    def text(self, theme: Theme) -> str:
        cat = theme.categories[self.cat]
        return (
            f"{_cap(_poss(theme, self.a))} {_low(cat.name)} {cat.verb} at least {cat.amount(self.delta)} more "
            f"than {_side(theme, self.b, self.cat)}."
        )


class AbsApart(Clue):
    """Entities of `a` and `b` differ by at least / at most `delta` in numeric
    category `cat`, as an absolute distance (direction-free) — "at least N away
    from" / "at most N away from". Unlike AtLeastApart it says nothing about
    which is larger; "at most" is the only clue that bounds two items *close*
    together."""

    removal_class = 1

    def __init__(self, cat: int, a: Term, b: Term, delta: int, at_least: bool, values: list[int]):
        self.cat, self.a, self.b, self.delta = cat, a, b, delta
        self.at_least = at_least
        self._values = values
        self.involved = frozenset({cat, a[0], b[0]})

    def holds(self, X) -> bool:
        ea, eb = entity_of(X, self.a), entity_of(X, self.b)
        gap = abs(self._values[X[ea][self.cat]] - self._values[X[eb][self.cat]])
        return gap >= self.delta if self.at_least else gap <= self.delta

    def text(self, theme: Theme) -> str:
        cat = theme.categories[self.cat]
        rel = "at least" if self.at_least else "at most"
        return (
            f"{_cap(_poss(theme, self.a))} {_low(cat.name)} {cat.verb} {rel} {cat.amount(self.delta)} away "
            f"from {_side(theme, self.b, self.cat)}."
        )


class RanksApart(Clue):
    """Entities of `a` and `b` sit at least / at most `k` RANKS apart in
    ordered category `cat` — ranged proximity for rank-only dials ("within
    two periods of", "at least three placings apart"). The rank-space
    sibling of AbsApart, which needs values; on a valued dial AbsApart
    already says this in the category's own units, so this family only
    generates where values are absent. k >= 2 keeps it distinct from
    NextTo (k == 1) and from the trivial "some gap exists"."""

    removal_class = 1

    def __init__(self, cat: int, a: Term, b: Term, k: int, at_least: bool):
        self.cat, self.a, self.b = cat, a, b
        self.k = k
        self.at_least = at_least
        self.involved = frozenset({cat, a[0], b[0]})

    def holds(self, X) -> bool:
        gap = abs(
            X[entity_of(X, self.a)][self.cat] - X[entity_of(X, self.b)][self.cat]
        )
        return gap >= self.k if self.at_least else gap <= self.k

    def text(self, theme: Theme) -> str:
        cat = theme.categories[self.cat]
        cn = _low(cat.name)
        if self.at_least:
            return (
                f"{_cap(_poss(theme, self.a))} {cn} {cat.verb} at least "
                f"{self.k} {_plural(cn)} away from {_side(theme, self.b, self.cat)}."
            )
        return (
            f"{_cap(_poss(theme, self.a))} {cn} {cat.verb} within "
            f"{self.k} {_plural(cn)} of {_side(theme, self.b, self.cat)}."
        )


class MultiCompare(Clue):
    """Entity of `c` ranks above (greater) or below ALL of `others` in ordered
    category `cat` — e.g. "less than both A and B"."""

    removal_class = 1

    def __init__(self, cat: int, c: Term, others, greater: bool):
        self.cat, self.c, self.greater = cat, c, greater
        self.others = tuple(sorted(others))
        self.involved = frozenset({cat, c[0], *(o[0] for o in self.others)})

    def holds(self, X) -> bool:
        rc = X[entity_of(X, self.c)][self.cat]
        ro = [X[entity_of(X, o)][self.cat] for o in self.others]
        return all(rc > r for r in ro) if self.greater else all(rc < r for r in ro)

    def text(self, theme: Theme) -> str:
        cat = theme.categories[self.cat]
        cn = _low(cat.name)
        labels = [_side(theme, o, self.cat) for o in self.others]
        # "higher/lower", matching Greater — NOT "more/less": on a reversed-rank
        # ordinal (Placing, where 1st = highest rank) "less placing" reads as a
        # numerically smaller (better) place, the opposite of what is enforced.
        rel = cat.more_word if self.greater else cat.less_word
        joiner = "both " if len(labels) == 2 else "all of "
        return f"{_cap(_poss(theme, self.c))} {cn} {cat.verb} {rel} than {joiner}{_join(labels, 'and')}."


def _join(labels: list[str], conj: str) -> str:
    """'A <conj> B' / 'A, B, <conj> C' — Oxford-comma list with a conjunction."""
    if len(labels) == 2:
        return f"{labels[0]} {conj} {labels[1]}"
    return ", ".join(labels[:-1]) + f", {conj} {labels[-1]}"


def _join_or(labels: list[str]) -> str:
    return _join(labels, "or")


_NUM_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}


def _count_word(n: int) -> str:
    return _NUM_WORDS.get(n, str(n))


def _plural(noun: str) -> str:
    """Naive English pluralisation good enough for entity and group nouns
    (case, ship, entry -> cases, ships, entries). A head-noun phrase
    pluralises its head: "side of town" -> "sides of town"."""
    head, sep, rest = noun.partition(" of ")
    if sep:
        return f"{_plural(head)} of {rest}"
    if noun.endswith("y") and (len(noun) < 2 or noun[-2] not in "aeiou"):
        return noun[:-1] + "ies"
    if noun.endswith(("s", "x", "z", "ch", "sh")):
        return noun + "es"
    return noun + "s"


class OrderAgree(Clue):
    """Cross-dial coupling: for the entities of `a` and `b`, their order in
    ordered category `cat1` and their order in ordered category `cat2` either
    match (`agree=True`: "whoever has the higher grade also sits in the later
    period") or oppose (`agree=False`: "... sits in the earlier period").

    A constraint on the JOIN of two orderings that no per-dial clue (or
    conditional over links) can express: learn either dial's order for the
    pair and the other dial's follows. Only meaningful — and only generated —
    when a puzzle carries two ordered categories."""

    removal_class = 2

    def __init__(self, cat1: int, cat2: int, a: Term, b: Term, agree: bool):
        self.cat1, self.cat2 = cat1, cat2
        self.a, self.b = a, b
        self.agree = agree
        self.involved = frozenset({cat1, cat2, a[0], b[0]})

    def holds(self, X) -> bool:
        ea, eb = entity_of(X, self.a), entity_of(X, self.b)
        same = (X[ea][self.cat1] > X[eb][self.cat1]) == (
            X[ea][self.cat2] > X[eb][self.cat2]
        )
        return same == self.agree

    def text(self, theme: Theme) -> str:
        c1, c2 = theme.categories[self.cat1], theme.categories[self.cat2]
        second = c2.more_word if self.agree else c2.less_word
        return (
            f"Of {_ref(theme, self.a)} and {_ref(theme, self.b)}, whoever has "
            f"the {c1.more_word} {_low(c1.name)} has the {second} {_low(c2.name)}."
        )


class Count(Clue):
    """The unifying cardinality engine: between `lo` and `hi` of the given term
    pairs share an entity.

    Every counting family is a thin phrasing over this one shape — Among is a
    floor over anchor-shared pairs, EitherOr the window [1,1], Neither [0,0],
    AtMost a ceiling, Exactly / ExactlyKLinks a two-sided window, AllDifferent
    the window [0,0] over a term set's cross-category pairs — and one generic
    propagator in deduce (`_prop_count`) serves them all. New window/atom
    combinations become clues without new machinery.

    Atoms must be pairwise distinct: a repeated atom ("A goes with X ... or A
    goes with X") is intra-clue redundancy and is rejected outright.
    """

    def __init__(self, pairs, lo: int, hi: int):
        canon = tuple(tuple(sorted(p)) for p in pairs)
        if len(set(canon)) != len(canon):
            raise ValueError("intra-clue redundancy: duplicate atom in Count")
        self.pairs = canon
        self.lo, self.hi = lo, hi
        self.involved = frozenset(t[0] for p in canon for t in p)

    def _true_count(self, X) -> int:
        return sum(entity_of(X, a) == entity_of(X, b) for a, b in self.pairs)

    def holds(self, X) -> bool:
        return self.lo <= self._true_count(X) <= self.hi


class _Disjunction(Count):
    """Shared machinery for "one of N" clues over option *terms*.

    `options` is a list of terms (category_index, item_index), each in a category
    other than the anchor's. The terms may span several categories — e.g. a
    Pastry and a Drink — so a clue can read "Ava goes with ... Bagel or Latte".
    Subclasses differ only in the Count window over the (anchor, option) pairs.

    `_matches(X)` counts how many option items belong to the anchor's entity.
    """

    def __init__(self, anchor: Term, options, lo: int, hi: int):
        self.anchor = anchor
        self.options = tuple(sorted(options))  # stable order; item labels unique
        super().__init__([(anchor, o) for o in self.options], lo, hi)
        self.involved = frozenset({anchor[0], *(o[0] for o in self.options)})

    def _matches(self, X) -> int:
        e = entity_of(X, self.anchor)
        return sum(1 for (co, io) in self.options if X[e][co] == io)

    def _labels(self, theme: Theme) -> list[str]:
        return [_label(theme, o) for o in self.options]


class Among(_Disjunction):
    """At least `at_least` of the option items belong to the anchor's entity.

    Inclusive: it never reveals *which* options match. With at_least == 1 this is
    the plain "one of N". For at_least >= 2 the options must lie in distinct
    categories — an entity holds one item per category, so it can match at most
    one option per category; the generator guarantees this.
    """

    removal_class = 1

    def __init__(self, anchor: Term, options, at_least: int = 1):
        super().__init__(anchor, options, at_least, len(options))
        self.at_least = at_least

    def text(self, theme: Theme) -> str:
        labels = self._labels(theme)
        if self.at_least == 1:
            body = f"at least one of {_join_or(labels)}"
        else:
            body = f"at least {_count_word(self.at_least)} of {_join(labels, 'and')}"
        return f"{_label(theme, self.anchor)} goes with {body}."


class EitherOr(_Disjunction):
    """Exactly one option item belongs to the anchor's entity (exclusive).

    Exclusivity is the extra bite: if two options belonged to the same entity the
    count could never be 1, so a true EitherOr implies its options sit on
    distinct entities. Takes any N >= 2.
    """

    removal_class = 1

    def __init__(self, anchor: Term, options):
        super().__init__(anchor, options, 1, 1)

    def text(self, theme: Theme) -> str:
        labels = self._labels(theme)
        if len(labels) == 2:
            phrase = f"either {labels[0]} or {labels[1]}"
            # Options in one category exclude each other anyway; options across
            # categories could both hold, so the enforced exclusivity must be
            # said out loud — a bare "either … or" reads as inclusive (cf. Or vs
            # Xor in Compound clues) and would hide the no-link deduction.
            if len({c for c, _ in self.options}) > 1:
                phrase += " (but not both)"
        else:
            phrase = f"exactly one of {_join_or(labels)}"
        return f"{_label(theme, self.anchor)} goes with {phrase}."


class Neither(_Disjunction):
    """No option item belongs to the anchor's entity (the negative "one of N").

    Note: at N == 1 this is equivalent to a plain Negative ("X does not go with
    Y"). The two are kept as separate rules for now — see the future-merge note.
    """

    removal_class = 2

    def __init__(self, anchor: Term, options):
        super().__init__(anchor, options, 0, 0)

    def text(self, theme: Theme) -> str:
        labels = self._labels(theme)
        if len(labels) == 2:
            phrase = f"neither {labels[0]} nor {labels[1]}"
        else:
            phrase = f"none of {_join_or(labels)}"
        return f"{_label(theme, self.anchor)} goes with {phrase}."


class AtMost(_Disjunction):
    """At most `k` of the option items belong to the anchor's entity — the
    complement of Among. Needs distinct-category options (else trivially true,
    since an entity matches at most one item per category)."""

    removal_class = 2

    def __init__(self, anchor: Term, options, k: int):
        super().__init__(anchor, options, 0, k)
        self.k = k

    def text(self, theme: Theme) -> str:
        return (
            f"{_label(theme, self.anchor)} goes with at most "
            f"{_count_word(self.k)} of {_join(self._labels(theme), 'and')}."
        )


class Exactly(_Disjunction):
    """Exactly `k` of the option items belong to the anchor's entity.

    The two-sided count — the intersection of Among (>= k) and AtMost (<= k). At
    k == 0 this is Neither and at k == 1 EitherOr, so it is generated only for
    k >= 2, which forces the options into distinct categories (an entity holds one
    item per category, so it can match at most one option per category). Likewise
    k must stay below the option count, else "all of them" is just direct links.
    """

    removal_class = 2

    def __init__(self, anchor: Term, options, k: int):
        super().__init__(anchor, options, k, k)
        self.k = k

    def text(self, theme: Theme) -> str:
        return (
            f"{_label(theme, self.anchor)} goes with exactly "
            f"{_count_word(self.k)} of {_join(self._labels(theme), 'and')}."
        )


class AllDifferent(Count):
    """The listed terms all belong to distinct entities — "A, B, and C are all
    different".

    The terms span >= 2 categories (within one category items are always on
    different entities, so a single-category list would be trivial), and
    categories may repeat — "Ava, Ben, Chai, and Latte are all different" mixes
    two Customers and two Drinks. Logically it is the conjunction of the pairwise
    "is not" facts among its terms — the Count window [0, 0] over the
    cross-category pairs (same-category pairs are distinct by the bijection); at
    N == 2 that is just a Negative, so it is generated only for N >= 3.
    """

    removal_class = 2

    def __init__(self, terms):
        self.terms = tuple(sorted(terms))
        super().__init__(
            [(p, q) for p, q in combinations(self.terms, 2) if p[0] != q[0]], 0, 0
        )
        self.involved = frozenset(t[0] for t in self.terms)

    def text(self, theme: Theme) -> str:
        # "belong to different <entities>" reads correctly even when the listed
        # terms span categories (a Wares and a Quarter aren't themselves artisans).
        labels = [_label(theme, t) for t in self.terms]
        return f"{_join(labels, 'and')} belong to different {_plural(theme.entity_noun)}."


class ExactlyKLinks(Count):
    """Exactly `k` of the given positive links hold — Count window [k, k] over
    free-form links.

    Each link is a pair of terms asserting they share an entity. K == 1, N == 2
    is the classic exclusive pairing — "either A goes with X, or B goes with Y,
    but not both" — and both K and N are free for richer variants.
    """

    removal_class = 1

    def __init__(self, links, k: int):
        super().__init__(sorted(tuple(sorted(link)) for link in links), k, k)
        self.links = self.pairs  # legacy alias (sorted canonical form)
        self.k = k

    def text(self, theme: Theme) -> str:
        parts = [f"{_label(theme, a)} goes with {_label(theme, b)}" for a, b in self.links]
        if self.k == 1 and len(parts) == 2:
            return f"Either {parts[0]}, or {parts[1]} — but not both."
        verb = "is" if self.k == 1 else "are"
        return f"Exactly {_count_word(self.k)} of these {verb} true: " + "; ".join(parts) + "."


class GroupMatch(Clue):
    """Two equal-size groups of terms cover the same set of entities, in unknown
    order — a bijection.

    N == 2 reads "between A and B, one goes with C and the other with D". For
    larger N the groups pair up one-to-one but which-with-which is hidden. Each
    group may mix categories ("between Muffin and Ava, ...") as long as the two
    sides' categories stay disjoint (else a Drink could "go with" another Drink).
    """

    removal_class = 1

    def __init__(self, left, right):
        self.left = tuple(sorted(left))
        self.right = tuple(sorted(right))
        self.involved = frozenset(t[0] for t in self.left + self.right)

    def holds(self, X) -> bool:
        le = sorted(entity_of(X, t) for t in self.left)
        re = sorted(entity_of(X, t) for t in self.right)
        return le == re and len(set(le)) == len(self.left)

    def text(self, theme: Theme) -> str:
        left = [_label(theme, t) for t in self.left]
        right = [_label(theme, t) for t in self.right]
        if len(left) == 2:
            return (
                f"Between {left[0]} and {left[1]}, one goes with {right[0]} "
                f"and the other with {right[1]}."
            )
        return f"{_join(left, 'and')} go with {_join(right, 'and')}, in some order."


# --- Conditionals over embedded boolean statements ---------------------------
# A *link* is a pair of terms in distinct categories, asserting they share an
# entity — the atom of the statement algebra below. A `Statement` is a boolean
# expression over links (Link / Not / And / Or / Xor) that knows three things:
#   * value(X)        -- its truth under a full solution
#   * eval(board)     -- its Kleene three-valued state (Y/N/U) on a partial board
#   * constrain(board, target) -- force it to `target` (Y/N), pushing the
#                        consequences down to its atoms; returns cells changed
# `Conditional` then wires two statements together as if-then / if-and-only-if,
# delegating all propagation to eval/constrain so arbitrarily nested antecedents
# and consequents stay sound. `board` is any object exposing deduce.Board's
# get/set (so the algebra needs no import of the solver).

_U, _Y, _N = 0, 1, 2  # mirror deduce.Board's unknown / linked / not-linked codes


def _flip(v: int) -> int:
    """Negate a three-valued cell (unknown stays unknown)."""
    return _U if v == _U else (_N if v == _Y else _Y)


class Statement:
    """Base class for the embeddable boolean expressions (see module comment)."""

    cats: frozenset

    def value(self, X) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def eval(self, board) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def constrain(self, board, target: int) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def text(self, theme: Theme) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class Link(Statement):
    """Atom: terms `a` and `b` (distinct categories) share an entity."""

    def __init__(self, a: Term, b: Term):
        self.a, self.b = a, b
        self.cats = frozenset({a[0], b[0]})

    def value(self, X) -> bool:
        return entity_of(X, self.a) == entity_of(X, self.b)

    def eval(self, board) -> int:
        return board.get(self.a[0], self.a[1], self.b[0], self.b[1])

    def constrain(self, board, target: int) -> int:
        return board.set(self.a[0], self.a[1], self.b[0], self.b[1], target)

    def text(self, theme: Theme) -> str:
        return f"{_label(theme, self.a)} goes with {_label(theme, self.b)}"


class Not(Statement):
    """Negation of a sub-statement."""

    def __init__(self, s: Statement):
        self.s = s
        self.cats = s.cats

    def value(self, X) -> bool:
        return not self.s.value(X)

    def eval(self, board) -> int:
        return _flip(self.s.eval(board))

    def constrain(self, board, target: int) -> int:
        return self.s.constrain(board, _flip(target))

    def text(self, theme: Theme) -> str:
        if isinstance(self.s, Link):  # read a negated link inline
            return f"{_label(theme, self.s.a)} does not go with {_label(theme, self.s.b)}"
        if isinstance(self.s, GroupLink):  # read a negated group membership inline
            g = self.s
            if g.subject:
                return f"no one in the {g.label} goes with {_label(theme, g.anchor)}"
            return f"{_ref(theme, g.anchor)} does not belong to the {g.label}"
        if isinstance(self.s, GroupSubset):  # read a negated universal inline
            gs = self.s
            return f"at least one member of the {gs.label_a} does not belong to the {gs.label_b}"
        return f"it is not the case that {self.s.text(theme)}"


class And(Statement):
    """Conjunction: every part holds."""

    def __init__(self, parts):
        self.parts = tuple(parts)
        self.cats = frozenset().union(*(p.cats for p in self.parts))

    def value(self, X) -> bool:
        return all(p.value(X) for p in self.parts)

    def eval(self, board) -> int:
        vs = [p.eval(board) for p in self.parts]
        if _N in vs:
            return _N
        return _Y if all(v == _Y for v in vs) else _U

    def constrain(self, board, target: int) -> int:
        changed = 0
        if target == _Y:  # all parts must hold
            for p in self.parts:
                changed += p.constrain(board, _Y)
        else:  # whole conj must be false: only forced once all but one are true
            vs = [p.eval(board) for p in self.parts]
            unknown = [p for p, v in zip(self.parts, vs) if v == _U]
            if _N not in vs and not unknown:  # every part holds — can't be false
                raise Contradiction("conjunction required false but fully true")
            if _N not in vs and len(unknown) == 1:
                changed += unknown[0].constrain(board, _N)
        return changed

    def text(self, theme: Theme) -> str:
        # bracket the conjunction so it reads as one unit inside a conditional
        parts = [p.text(theme) for p in self.parts]
        if len(parts) == 2:
            return f"both {parts[0]} and {parts[1]}"
        return "all of " + _join(parts, "and")


class Or(Statement):
    """Inclusive disjunction: at least one part holds."""

    def __init__(self, parts):
        self.parts = tuple(parts)
        self.cats = frozenset().union(*(p.cats for p in self.parts))

    def value(self, X) -> bool:
        return any(p.value(X) for p in self.parts)

    def eval(self, board) -> int:
        vs = [p.eval(board) for p in self.parts]
        if _Y in vs:
            return _Y
        return _N if all(v == _N for v in vs) else _U

    def constrain(self, board, target: int) -> int:
        changed = 0
        if target == _N:  # every part must fail
            for p in self.parts:
                changed += p.constrain(board, _N)
        else:  # need at least one: forced once all but one are false
            vs = [p.eval(board) for p in self.parts]
            unknown = [p for p, v in zip(self.parts, vs) if v == _U]
            if _Y not in vs and not unknown:  # every part failed — can't hold
                raise Contradiction("disjunction required true but fully false")
            if _Y not in vs and len(unknown) == 1:
                changed += unknown[0].constrain(board, _Y)
        return changed

    def text(self, theme: Theme) -> str:
        # "either … or …" brackets the (inclusive) disjunction as one unit; the
        # explicit Xor carries "(but not both)", so plain or reads as inclusive.
        parts = [p.text(theme) for p in self.parts]
        if len(parts) == 2:
            return f"either {parts[0]} or {parts[1]}"
        return "at least one of " + _join_or(parts)


class Xor(Statement):
    """Exclusive or of two sub-statements: exactly one holds."""

    def __init__(self, p: Statement, q: Statement):
        self.p, self.q = p, q
        self.cats = p.cats | q.cats

    def value(self, X) -> bool:
        return self.p.value(X) != self.q.value(X)

    def eval(self, board) -> int:
        vp, vq = self.p.eval(board), self.q.eval(board)
        if vp == _U or vq == _U:
            return _U
        return _Y if vp != vq else _N

    def constrain(self, board, target: int) -> int:
        vp, vq = self.p.eval(board), self.q.eval(board)
        # target Y => the two differ; target N => they match. Pin the unknown side
        # off the known one (no move until exactly one side is known).
        want_same = target == _N
        if vp != _U and vq != _U and (vp == vq) != want_same:
            raise Contradiction("xor sides settled against the required parity")
        if vp != _U and vq == _U:
            return self.q.constrain(board, vp if want_same else _flip(vp))
        if vq != _U and vp == _U:
            return self.p.constrain(board, vq if want_same else _flip(vq))
        return 0

    def text(self, theme: Theme) -> str:
        return f"either {self.p.text(theme)} or {self.q.text(theme)} (but not both)"


class GroupLink(Statement):
    """Atom: the entity of `anchor` belongs to group `label` — a named block of
    grouped category `cat`'s items (members are its item indices). The Statement
    form of InGroup, so a *group* can stand in as an instance anywhere the boolean
    algebra reaches: a disjunct ("... or someone in the Hill Ward goes with X"), a
    conditional leaf ("if the artisan with X belongs to the Hill Ward, ..."), an
    Xor operand, and so on.

    `subject` only flips the English (the logic is identical): False reads the
    anchor as subject ("<anchor> belongs to the <label>"); True reads the group as
    an existential subject ("someone in the <label> goes with <anchor's item>") —
    the natural phrasing when the group is an alternative to a named instance."""

    def __init__(self, anchor: Term, cat: int, label: str, members, subject: bool = False):
        self.anchor = anchor
        self.cat = cat
        self.label = label
        self.members = tuple(sorted(members))
        self.subject = subject
        self.cats = frozenset({anchor[0], cat})

    def value(self, X) -> bool:
        return X[entity_of(X, self.anchor)][self.cat] in self.members

    def eval(self, board) -> int:
        ac, ai = self.anchor
        states = [board.get(ac, ai, self.cat, w) for w in self.members]
        if _Y in states:  # anchor pinned to a member -> definitely in the group
            return _Y
        if all(s == _N for s in states):  # ruled out of every member -> not in it
            return _N
        return _U

    def constrain(self, board, target: int) -> int:
        ac, ai = self.anchor
        if target == _Y:  # in the group: the anchor cannot hold any non-member item
            members = set(self.members)
            return sum(
                board.set(ac, ai, self.cat, u, _N)
                for u in range(board.n)
                if u not in members
            )
        # not in the group: the anchor cannot hold any member item
        return sum(board.set(ac, ai, self.cat, w, _N) for w in self.members)

    def text(self, theme: Theme) -> str:
        if self.subject:
            return f"someone in the {self.label} goes with {_label(theme, self.anchor)}"
        return f"{_ref(theme, self.anchor)} belongs to the {self.label}"


class GroupSubset(Statement):
    """Universal atom: EVERY member of group A (block `members_a` of category
    `cat_a`) also belongs to group B (block `members_b` of category `cat_b`) — i.e.
    A ⊆ B membership-wise. The set form of GroupLink: a whole group stands in as an
    instance ("both members of the Hill Ward belong to the Joiner's Guild").

    It reduces to a block of pairwise non-links: A ⊆ B holds iff no A-member item is
    linked to any non-B item of `cat_b` (a member of A sitting outside B is the only
    way to break it). That makes the three-valued eval/constrain exact for the
    asserted-true direction and sound (partial) for the false direction."""

    def __init__(self, cat_a: int, members_a, label_a: str, cat_b: int, members_b, label_b: str):
        self.cat_a = cat_a
        self.members_a = tuple(sorted(members_a))
        self.label_a = label_a
        self.cat_b = cat_b
        self.members_b = tuple(sorted(members_b))
        self.label_b = label_b
        self.cats = frozenset({cat_a, cat_b})

    def _bad_pairs(self, n: int):
        """The (a-item, b-item) cells whose link would violate A ⊆ B: an A-member
        carried by an entity whose `cat_b` item is OUTSIDE B."""
        mb = set(self.members_b)
        return [(a, b) for a in self.members_a for b in range(n) if b not in mb]

    def value(self, X) -> bool:
        mb = set(self.members_b)
        ma = set(self.members_a)
        return all(X[e][self.cat_b] in mb for e in range(len(X)) if X[e][self.cat_a] in ma)

    def eval(self, board) -> int:
        states = [board.get(self.cat_a, a, self.cat_b, b) for a, b in self._bad_pairs(board.n)]
        if _Y in states:  # an A-member is pinned outside B -> the universal is broken
            return _N
        if all(s == _N for s in states):  # no A-member can sit outside B -> holds
            return _Y
        return _U

    def constrain(self, board, target: int) -> int:
        bad = self._bad_pairs(board.n)
        if target == _Y:  # all of A in B: no A-member may link to a non-B item
            return sum(board.set(self.cat_a, a, self.cat_b, b, _N) for a, b in bad)
        # target N: some A-member sits outside B. Only forced once a single such
        # link remains open (the rest ruled out) -> pin it true.
        states = [board.get(self.cat_a, a, self.cat_b, b) for a, b in bad]
        if _Y in states:
            return 0  # already witnessed
        unknown = [(a, b) for (a, b), s in zip(bad, states) if s == _U]
        if not unknown:  # no witness possible — the universal can't be broken
            raise Contradiction("subset required broken but provably holds")
        if len(unknown) == 1:
            a, b = unknown[0]
            return board.set(self.cat_a, a, self.cat_b, b, _Y)
        return 0

    def _members_phrase(self) -> str:
        word = "both" if len(self.members_a) == 2 else "all"
        return f"{word} members of the {self.label_a}"

    def text(self, theme: Theme) -> str:
        return f"{self._members_phrase()} belong to the {self.label_b}"


class Conditional(Clue):
    """A general if-then / if-and-only-if over two embedded `Statement`s.

    ``biconditional=False`` reads "if {ante}, then {cons}" and fires modus ponens
    (antecedent true => consequent true) plus its contrapositive (consequent false
    => antecedent false). ``True`` reads "{ante} if and only if {cons}" and carries
    each side's known truth to the other, both polarities. All narrowing is
    delegated to the statements' three-valued eval/constrain, so the antecedent and
    consequent may be arbitrarily nested boolean expressions (Not/And/Or/Xor over
    links) and propagation stays sound. The atom-only case (Link => Link, Link iff
    Link) is the classic implication/biconditional."""

    removal_class = 2

    def __init__(self, ante: Statement, cons: Statement, biconditional: bool = False):
        self.ante = ante
        self.cons = cons
        self.biconditional = biconditional
        self.involved = ante.cats | cons.cats

    def holds(self, X) -> bool:
        a, c = self.ante.value(X), self.cons.value(X)
        return (a == c) if self.biconditional else ((not a) or c)

    def propagate(self, board) -> int:
        a = self.ante.eval(board)
        c = self.cons.eval(board)
        changed = 0
        if self.biconditional:
            if a != _U and c != _U and a != c:
                raise Contradiction("biconditional sides disagree")
            if a != _U:
                changed += self.cons.constrain(board, a)
            if c != _U:
                changed += self.ante.constrain(board, c)
        else:
            if a == _Y and c == _N:  # implication violated
                raise Contradiction("antecedent holds but consequent fails")
            if a == _Y:  # modus ponens
                changed += self.cons.constrain(board, _Y)
            if c == _N:  # contrapositive
                changed += self.ante.constrain(board, _N)
        return changed

    def text(self, theme: Theme) -> str:
        at, ct = self.ante.text(theme), self.cons.text(theme)
        if self.biconditional:
            return f"{_cap(at)} if and only if {ct}."
        return f"If {at}, then {ct}."


class Compound(Clue):
    """A standalone assertion that an embedded boolean `Statement` simply holds —
    the Statement algebra (Link / Not / And / Or / Xor / GroupLink) promoted to a
    top-level clue instead of only living inside a Conditional. This is what lets a
    bare disjunction mix a named instance with a group existential: "either Beatrix
    goes with X, or someone in the Hill Ward does"."""

    removal_class = 1

    def __init__(self, stmt: Statement):
        self.stmt = stmt
        self.involved = stmt.cats

    def holds(self, X) -> bool:
        return self.stmt.value(X)

    def propagate(self, board) -> int:
        if self.stmt.eval(board) == _N:  # asserted true but provably false
            raise Contradiction("compound statement can no longer hold")
        return self.stmt.constrain(board, _Y)  # the statement is asserted true

    def text(self, theme: Theme) -> str:
        return _cap(self.stmt.text(theme)) + "."


# --- Hierarchy / groups ------------------------------------------------------
# A *group* is a named block of one category's items (Trades -> Guilds). These
# clues constrain which group an entity's item falls in; they read in the group's
# vocabulary but resolve entirely on the grouped category's ordinary column.

def _group_index(partition, item_index: int) -> int:
    for gi, members in enumerate(partition):
        if item_index in members:
            return gi
    return -1


class InGroup(Clue):
    """The entity of `anchor` has, in grouped category `cat`, an item belonging to
    the group `label` — "Aldric belongs to the Smiths' Guild"."""

    removal_class = 2

    def __init__(self, anchor: Term, cat: int, label: str, members):
        self.anchor = anchor
        self.cat = cat
        self.label = label
        self.members = tuple(sorted(members))  # item indices of the group in `cat`
        self.involved = frozenset({anchor[0], cat})

    def holds(self, X) -> bool:
        return X[entity_of(X, self.anchor)][self.cat] in self.members

    def text(self, theme: Theme) -> str:
        return f"{_cap(_ref(theme, self.anchor))} belongs to the {self.label}."


class SameGroup(Clue):
    """Entities of `a` and `b` fall in the *same* group of category `cat` —
    "Aldric and Beatrix are in the same guild"."""

    removal_class = 2

    def __init__(self, a: Term, b: Term, cat: int, group_noun: str, partition):
        self.a, self.b = a, b
        self.cat = cat
        self.group_noun = group_noun
        self.partition = tuple(tuple(sorted(g)) for g in partition)
        self.involved = frozenset({a[0], b[0], cat})

    def holds(self, X) -> bool:
        ga = _group_index(self.partition, X[entity_of(X, self.a)][self.cat])
        gb = _group_index(self.partition, X[entity_of(X, self.b)][self.cat])
        return ga >= 0 and ga == gb

    def text(self, theme: Theme) -> str:
        return (
            f"{_cap(_ref(theme, self.a))} and {_ref(theme, self.b)} are in the "
            f"same {self.group_noun}."
        )


class DiffGroup(Clue):
    """Entities of `a` and `b` fall in *different* groups of category `cat` —
    "Aldric and Beatrix are in different guilds"."""

    removal_class = 2

    def __init__(self, a: Term, b: Term, cat: int, group_noun: str, partition):
        self.a, self.b = a, b
        self.cat = cat
        self.group_noun = group_noun
        self.partition = tuple(tuple(sorted(g)) for g in partition)
        self.involved = frozenset({a[0], b[0], cat})

    def holds(self, X) -> bool:
        ga = _group_index(self.partition, X[entity_of(X, self.a)][self.cat])
        gb = _group_index(self.partition, X[entity_of(X, self.b)][self.cat])
        return ga >= 0 and gb >= 0 and ga != gb

    def text(self, theme: Theme) -> str:
        return (
            f"{_cap(_ref(theme, self.a))} and {_ref(theme, self.b)} are in "
            f"different {_plural(self.group_noun)}."
        )


class NotInGroup(Clue):
    """The entity of `anchor` does NOT belong to group `label` of category `cat`
    — "the artisan with the Riverside workshop does not belong to the Clothiers'
    Guild". The negative of InGroup; equivalently a universal-negative ("no
    member of that guild has the Riverside workshop")."""

    removal_class = 2

    def __init__(self, anchor: Term, cat: int, label: str, members):
        self.anchor = anchor
        self.cat = cat
        self.label = label
        self.members = tuple(sorted(members))
        self.involved = frozenset({anchor[0], cat})

    def holds(self, X) -> bool:
        return X[entity_of(X, self.anchor)][self.cat] not in self.members

    def text(self, theme: Theme) -> str:
        return f"{_cap(_ref(theme, self.anchor))} does not belong to the {self.label}."


class GroupCount(Clue):
    """A cardinality clue over group membership: among `anchors`, the number whose
    entity falls in group `label` of category `cat` is `>= / <= / == k` (per
    `mode`). The set-counting clue the bijection alone can't express — e.g.
    "exactly two of Aldric, Beatrix, and Cedric belong to the Joiners' Guild"."""

    removal_class = 2

    def __init__(self, anchors, cat: int, label: str, members, k: int, mode: str):
        assert mode in ("atleast", "atmost", "exactly")
        self.anchors = tuple(sorted(anchors))
        self.cat = cat
        self.label = label
        self.members = tuple(sorted(members))
        self.k = k
        self.mode = mode
        self.involved = frozenset({cat, *(a[0] for a in self.anchors)})

    def _count(self, X) -> int:
        ms = set(self.members)
        return sum(1 for a in self.anchors if X[entity_of(X, a)][self.cat] in ms)

    def holds(self, X) -> bool:
        c = self._count(X)
        if self.mode == "atleast":
            return c >= self.k
        if self.mode == "atmost":
            return c <= self.k
        return c == self.k

    def text(self, theme: Theme) -> str:
        refs = _join([_ref(theme, a) for a in self.anchors], "and")
        if self.k == 0:  # "exactly 0" / "at most 0" read better as "none"
            return f"None of {refs} belong to the {self.label}."
        prefix = {"atleast": "At least", "atmost": "At most", "exactly": "Exactly"}[self.mode]
        verb = "belongs" if self.k == 1 else "belong"
        return f"{prefix} {_count_word(self.k)} of {refs} {verb} to the {self.label}."


class GroupOrder(Clue):
    """Every entity in group `higher` outranks every entity in group `lower` on the
    ordered category `ocat` — "everyone in the Ironmongers' Guild ranks higher in
    dues than everyone in the Clothiers' Guild". Couples the hierarchy to an
    ordered scale; only true (and generated) when the two guilds happen to be
    fully rank-separated, which makes it rare."""

    removal_class = 2

    def __init__(self, gcat: int, ocat: int, higher, lower, higher_label: str, lower_label: str):
        self.gcat = gcat          # the grouped category (e.g. Trade)
        self.ocat = ocat          # the ordered category (e.g. Dues)
        self.higher = tuple(sorted(higher))  # item indices of the top guild in gcat
        self.lower = tuple(sorted(lower))    # item indices of the bottom guild
        self.higher_label = higher_label
        self.lower_label = lower_label
        self.involved = frozenset({gcat, ocat})

    def _rank(self, X, t: int) -> int:
        return X[entity_of(X, (self.gcat, t))][self.ocat]  # ordered items are rank-sorted

    def holds(self, X) -> bool:
        return min(self._rank(X, t) for t in self.higher) > max(self._rank(X, t) for t in self.lower)

    def text(self, theme: Theme) -> str:
        oname = _low(theme.categories[self.ocat].name)
        return (
            f"Everyone in the {self.higher_label} ranks higher in {oname} than "
            f"everyone in the {self.lower_label}."
        )


class GroupGroupCount(Clue):
    """Cross-tabulation count between two hierarchies: how many entities sit in
    group A of category `cat1` *and* group B of category `cat2` is `== / >= / <= k`
    — "exactly two members of the Ironmongers' Guild live in the Hill Ward".
    Needs two grouped categories, so it's the payoff of a second partition."""

    removal_class = 2

    def __init__(self, cat1: int, membersA, labelA: str, cat2: int, membersB, labelB: str, k: int, mode: str):
        assert mode in ("atleast", "atmost", "exactly")
        self.cat1, self.cat2 = cat1, cat2
        self.membersA = tuple(sorted(membersA))
        self.membersB = tuple(sorted(membersB))
        self.labelA, self.labelB = labelA, labelB
        self.k, self.mode = k, mode
        self.involved = frozenset({cat1, cat2})

    def _count(self, X) -> int:
        A, B = set(self.membersA), set(self.membersB)
        return sum(1 for e in range(len(X)) if X[e][self.cat1] in A and X[e][self.cat2] in B)

    def holds(self, X) -> bool:
        c = self._count(X)
        if self.mode == "atleast":
            return c >= self.k
        if self.mode == "atmost":
            return c <= self.k
        return c == self.k

    def text(self, theme: Theme) -> str:
        if self.k == 0:  # exactly/at-most zero
            return f"No members of the {self.labelA} are in the {self.labelB}."
        prefix = {"atleast": "At least", "atmost": "At most", "exactly": "Exactly"}[self.mode]
        noun, verb = ("member", "is") if self.k == 1 else ("members", "are")
        return (
            f"{prefix} {_count_word(self.k)} {noun} of the {self.labelA} "
            f"{verb} in the {self.labelB}."
        )


class GroupGroupCompare(Clue):
    """More entities are in (group A of `cat1`) ∩ (group C of `cat2`) than are in
    (group B of `cat1`) ∩ (the same group C) — "more members of the Ironmongers'
    Guild live in the Hill Ward than members of the Clothiers' Guild"."""

    removal_class = 2

    def __init__(self, cat1: int, membersA, labelA: str, membersB, labelB: str, cat2: int, membersC, labelC: str):
        self.cat1, self.cat2 = cat1, cat2
        self.membersA = tuple(sorted(membersA))
        self.membersB = tuple(sorted(membersB))
        self.membersC = tuple(sorted(membersC))
        self.labelA, self.labelB, self.labelC = labelA, labelB, labelC
        self.involved = frozenset({cat1, cat2})

    def _count(self, X, members) -> int:
        m, C = set(members), set(self.membersC)
        return sum(1 for e in range(len(X)) if X[e][self.cat1] in m and X[e][self.cat2] in C)

    def holds(self, X) -> bool:
        return self._count(X, self.membersA) > self._count(X, self.membersB)

    def text(self, theme: Theme) -> str:
        return (
            f"More members of the {self.labelA} are in the {self.labelC} than "
            f"members of the {self.labelB}."
        )


# --- General set composition -------------------------------------------------
# The "instance OR group OR N-members-of-a-group, anywhere" clue: a cardinality
# over a UNION of subjects (named entities and whole groups), counted as distinct
# entities, each tested against a target (a group, or a set of items). Subsumes
# "two members of the Hill Ward pay 5 or 6 coins" and "exactly two of (the River
# Ward members and the tanner) belong to the Joiners' Guild".

class SetCount(Clue):
    """Exactly / at least / at most K of a union of `subjects` are associated with
    a `target`. Subjects mix named entities and whole groups; the count is over the
    DISTINCT entities in the union. The target is a set of (category, item) cells (a
    group contributes its whole block); an entity is "associated" iff it is linked
    to at least one target cell.

    Subjects: a tuple of ``("entity", term)`` and ``("group", cat, members,
    label)``. Counting over uncertain & possibly-overlapping subject sets makes
    propagation sound but PARTIAL (`deduce._prop_set_count`): it bound-checks the
    count and unit-propagates the determinate side of each entity's
    (in-subject AND hits-target) once the other side is pinned."""

    removal_class = 2

    def __init__(self, subjects, target_cells, target_label, target_is_group, k, mode):
        assert mode in ("exactly", "atleast", "atmost")
        self.subjects = tuple(subjects)
        self.target_cells = tuple(sorted(set(target_cells)))
        self.target_label = target_label
        self.target_is_group = target_is_group
        self.k = k
        self.mode = mode
        cats = {0}  # entities are addressed through the subject column
        for sub in self.subjects:
            cats.add(sub[1][0] if sub[0] == "entity" else sub[1])
        cats.update(c for c, _ in self.target_cells)
        self.involved = frozenset(cats)

    def subject_entities(self, X) -> set:
        ents = set()
        for sub in self.subjects:
            if sub[0] == "entity":
                ents.add(entity_of(X, sub[1]))
            else:
                _, cat, members, _label = sub
                ms = set(members)
                ents.update(e for e in range(len(X)) if X[e][cat] in ms)
        return ents

    def _associated(self, X, e) -> bool:
        return any(X[e][c] == i for c, i in self.target_cells)

    def _count(self, X) -> int:
        return sum(1 for e in self.subject_entities(X) if self._associated(X, e))

    def holds(self, X) -> bool:
        c = self._count(X)
        if self.mode == "atleast":
            return c >= self.k
        if self.mode == "atmost":
            return c <= self.k
        return c == self.k

    def _subject_phrase(self, theme: Theme) -> str:
        parts = []
        for sub in self.subjects:
            if sub[0] == "entity":
                parts.append(_ref(theme, sub[1]))
            else:
                parts.append(f"the members of the {sub[3]}")
        return _join(parts, "and")

    def text(self, theme: Theme) -> str:
        prefix = {"atleast": "At least", "atmost": "At most", "exactly": "Exactly"}[self.mode]
        kw = _count_word(self.k)
        single_group = len(self.subjects) == 1 and self.subjects[0][0] == "group"
        if single_group:  # "Exactly two members of the Hill Ward ..." (no ambiguity)
            noun = "member" if self.k == 1 else "members"
            head = f"{prefix} {kw} {noun} of the {self.subjects[0][3]}"
        else:  # a union of instances/groups -> bracket so the set boundary is clear
            head = f"{prefix} {kw} of ({self._subject_phrase(theme)})"
        if self.target_is_group:  # a single named group reads unambiguously as-is
            verb = "belongs to" if self.k == 1 else "belong to"
            return f"{head} {verb} the {self.target_label}."
        verb = "goes with" if self.k == 1 else "go with"
        # a multi-item target set carries an internal "or" -> bracket it too
        tgt = f"({self.target_label})" if len(self.target_cells) > 1 else self.target_label
        return f"{head} {verb} {tgt}."


# --- Cognitive complexity --------------------------------------------------
# A *structural* read of how much work a clue is to parse and apply — independent
# of where it lands in a solve. It rises with case analysis (disjunction /
# conditional / xor), negation, arithmetic, the number of entities a clue ties
# together, and nesting depth. This is the "hard to read" axis the technique-tier
# grade can't see (two same-tier puzzles differ a lot if one is all "is/is-not"
# and the other is nested conditionals). Weights are deliberately gentle and
# relative; they feed the difficulty grader, not the solver.

def statement_cost(s: Statement) -> float:
    """Cognitive weight of an embedded boolean statement (recursive)."""
    if isinstance(s, Link):
        return 1.0
    if isinstance(s, GroupLink):  # a set-membership instance — a touch heavier
        return 1.4
    if isinstance(s, GroupSubset):  # a universal over a whole group — heavier still
        return 2.2
    if isinstance(s, Not):
        return 0.6 + statement_cost(s.s)
    if isinstance(s, (And, Or)):  # case analysis grows with the operands
        return 0.8 * len(s.parts) + sum(statement_cost(p) for p in s.parts)
    if isinstance(s, Xor):
        return 1.2 + statement_cost(s.p) + statement_cost(s.q)
    return 1.0


def clue_cost(clue: Clue) -> float:
    """Cognitive weight of a single clue (see module section comment)."""
    if isinstance(clue, Positive):
        return 1.0
    if isinstance(clue, Negative):
        return 1.3
    if isinstance(clue, Greater):
        return 2.0
    if isinstance(clue, (Adjacent, NextTo)):
        return 2.2
    if isinstance(clue, Between):
        return 2.8
    if isinstance(clue, (Diff, AtLeastApart, AbsApart, RanksApart)):
        return 2.6
    if isinstance(clue, MultiCompare):
        return 2.4 + 0.5 * len(clue.others)
    if isinstance(clue, OrderAgree):
        return 3.2  # two dials held in mind at once — compound comparison
    if isinstance(clue, (Among, EitherOr, Neither, AtMost, Exactly)):
        return 1.6 + 0.6 * len(clue.options)  # disjunction over N options
    if isinstance(clue, AllDifferent):
        return 1.2 + 0.4 * len(clue.terms)
    if isinstance(clue, ExactlyKLinks):
        return 2.2 + 0.5 * len(clue.links)
    if isinstance(clue, GroupMatch):
        return 2.8 + 0.4 * len(clue.left)
    if isinstance(clue, Conditional):
        base = 3.0 if clue.biconditional else 2.5  # the case analysis itself
        return base + statement_cost(clue.ante) + statement_cost(clue.cons)
    if isinstance(clue, Compound):  # a bare asserted statement (e.g. a disjunction)
        return 1.8 + statement_cost(clue.stmt)
    if isinstance(clue, InGroup):
        return 1.6
    if isinstance(clue, NotInGroup):
        return 1.9
    if isinstance(clue, (SameGroup, DiffGroup)):
        return 2.2
    if isinstance(clue, GroupCount):
        return 2.6 + 0.3 * len(clue.anchors)
    if isinstance(clue, SetCount):  # cardinality over a union of set instances
        return 3.0 + 0.4 * len(clue.subjects) + (0.0 if clue.target_is_group else 0.4)
    if isinstance(clue, GroupOrder):
        return 3.0
    if isinstance(clue, (GroupGroupCount, GroupGroupCompare)):
        return 3.4
    return 1.5  # unknown clue type — a neutral middle weight


def clueset_metrics(clues: list) -> dict:
    """Aggregate cognitive load of a whole clue set: ``mean`` (typical
    sophistication), ``max`` (the single gnarliest clue), and ``total`` (overall
    reading burden)."""
    costs = [clue_cost(c) for c in clues] or [0.0]
    return {"mean": sum(costs) / len(costs), "max": max(costs), "total": sum(costs)}
