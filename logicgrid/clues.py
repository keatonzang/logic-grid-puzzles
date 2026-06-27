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

from .model import Theme

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
        cn = theme.categories[self.cat].name
        return (
            f"The {theme.entity_noun} with {_label(theme, self.a)} has a higher "
            f"{cn} than the one with {_label(theme, self.b)}."
        )


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
            f"{_label(theme, self.a)}'s {cat.name} is exactly {cat.amount(self.delta)} more "
            f"than {_label(theme, self.b)}'s."
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
        cn = theme.categories[self.cat].name
        return (
            f"{_label(theme, self.c)}'s {cn} is between {_label(theme, self.a)}'s "
            f"and {_label(theme, self.b)}'s."
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
        cn = theme.categories[self.cat].name
        return f"{_label(theme, self.a)}'s {cn} is immediately below {_label(theme, self.b)}'s."


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
        cn = theme.categories[self.cat].name
        return f"{_label(theme, self.a)}'s {cn} is immediately next to {_label(theme, self.b)}'s."


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
            f"{_label(theme, self.a)}'s {cat.name} is at least {cat.amount(self.delta)} more "
            f"than {_label(theme, self.b)}'s."
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
            f"{_label(theme, self.a)}'s {cat.name} is {rel} {cat.amount(self.delta)} away "
            f"from {_label(theme, self.b)}'s."
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
        cn = theme.categories[self.cat].name
        labels = [f"{_label(theme, o)}'s" for o in self.others]
        rel = "more" if self.greater else "less"
        joiner = "both " if len(labels) == 2 else "all of "
        return f"{_label(theme, self.c)}'s {cn} was {rel} than {joiner}{_join(labels, 'and')}."


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
    """Naive English pluralisation good enough for entity nouns (case, ship,
    order, entry -> cases, ships, orders, entries)."""
    if noun.endswith("y") and (len(noun) < 2 or noun[-2] not in "aeiou"):
        return noun[:-1] + "ies"
    if noun.endswith(("s", "x", "z", "ch", "sh")):
        return noun + "es"
    return noun + "s"


class _Disjunction(Clue):
    """Shared machinery for "one of N" clues over option *terms*.

    `options` is a list of terms (category_index, item_index), each in a category
    other than the anchor's. The terms may span several categories — e.g. a
    Pastry and a Drink — so a clue can read "Ava goes with ... Bagel or Latte".
    Subclasses differ only in how many options must match the anchor's entity.

    `_matches(X)` counts how many option items belong to the anchor's entity.
    """

    def __init__(self, anchor: Term, options):
        self.anchor = anchor
        self.options = tuple(sorted(options))  # stable order; item labels unique
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
        super().__init__(anchor, options)
        self.at_least = at_least

    def holds(self, X) -> bool:
        return self._matches(X) >= self.at_least

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

    def holds(self, X) -> bool:
        return self._matches(X) == 1

    def text(self, theme: Theme) -> str:
        labels = self._labels(theme)
        if len(labels) == 2:
            phrase = f"either {labels[0]} or {labels[1]}"
        else:
            phrase = f"exactly one of {_join_or(labels)}"
        return f"{_label(theme, self.anchor)} goes with {phrase}."


class Neither(_Disjunction):
    """No option item belongs to the anchor's entity (the negative "one of N").

    Note: at N == 1 this is equivalent to a plain Negative ("X does not go with
    Y"). The two are kept as separate rules for now — see the future-merge note.
    """

    removal_class = 2

    def holds(self, X) -> bool:
        return self._matches(X) == 0

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
        super().__init__(anchor, options)
        self.k = k

    def holds(self, X) -> bool:
        return self._matches(X) <= self.k

    def text(self, theme: Theme) -> str:
        return (
            f"{_label(theme, self.anchor)} goes with at most "
            f"{_count_word(self.k)} of {_join(self._labels(theme), 'and')}."
        )


class AllDifferent(Clue):
    """The listed terms all belong to distinct entities — "A, B, and C are all
    different".

    The terms span >= 2 categories (within one category items are always on
    different entities, so a single-category list would be trivial), and
    categories may repeat — "Ava, Ben, Chai, and Latte are all different" mixes
    two Customers and two Drinks. Logically it is the conjunction of the pairwise
    "is not" facts among its terms; at N == 2 that is just a Negative, so it is
    generated only for N >= 3.
    """

    removal_class = 2

    def __init__(self, terms):
        self.terms = tuple(sorted(terms))
        self.involved = frozenset(t[0] for t in self.terms)

    def holds(self, X) -> bool:
        ents = [entity_of(X, t) for t in self.terms]
        return len(set(ents)) == len(ents)

    def text(self, theme: Theme) -> str:
        labels = [_label(theme, t) for t in self.terms]
        return f"{_join(labels, 'and')} are all different {_plural(theme.entity_noun)}."


class ExactlyKLinks(Clue):
    """Exactly `k` of the given positive links hold.

    Each link is a pair of terms asserting they share an entity. K == 1, N == 2
    is the classic exclusive pairing — "either A goes with X, or B goes with Y,
    but not both" — and both K and N are free for richer variants.
    """

    removal_class = 1

    def __init__(self, links, k: int):
        self.links = tuple(sorted(tuple(sorted(link)) for link in links))
        self.k = k
        self.involved = frozenset(t[0] for link in self.links for t in link)

    def holds(self, X) -> bool:
        return sum(entity_of(X, a) == entity_of(X, b) for a, b in self.links) == self.k

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
