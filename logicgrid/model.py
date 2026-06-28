"""Data model for a logic-grid puzzle theme and its solution.

A puzzle has K *categories*, each with the same number N of *items*. A full
solution assigns, to each of N entities, exactly one item from every category
(a bijection per category). We anchor entities to category 0: entity `i` is the
i-th item of category 0. The solution is stored as a grid:

    X[entity][category] = item index (0..N-1)

with X[i][0] == i always (the anchor). For every category c, the column
X[*][c] is a permutation of range(N).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass


def _looks_plural(name: str) -> bool:
    """Heuristic: does this category name read as a plural noun? Naive but enough
    to flag 'Earnings'/'Dues'/'Winnings' while sparing singular '-s' words like
    'Status', 'Bonus', 'Class', 'Axis'."""
    low = name.lower()
    return low.endswith("s") and not low.endswith(("ss", "us", "is"))


@dataclass
class Category:
    name: str
    items: list[str]
    # `ordered` marks a category whose items have a meaningful low->high order
    # (positions, ages, prices...). Items MUST be listed ascending. Enables
    # "higher/lower than" comparison clues. `values` optionally gives numeric
    # values aligned to items, enabling exact-difference clues.
    ordered: bool = False
    values: list[int] | None = None
    # `unit`/`unit_suffix` wrap numeric *amounts* in clue text: a prefix (e.g. "$"
    # -> "$2") and/or a suffix (e.g. " gp" -> "20 gp"). Both empty for plain
    # numbers.
    unit: str = ""
    unit_suffix: str = ""
    # `referent` is a template for naming an entity *by this category's item* in
    # cross-category clue text, e.g. "the person studying {}" -> "the person
    # studying Debate". Empty falls back to "the {entity_noun} with {item}". The
    # subject category (index 0) is the entity's identity and always reads as the
    # bare item (a name), so its referent is ignored.
    referent: str = ""
    # `plural` marks a category whose *name* is a plural or mass noun ("Dues",
    # "Earnings", "Winnings"). Comparison clue text agrees with it: the verb
    # becomes "are" not "is" ("the order's dues are exactly $3 more") and the
    # comparative drops its article ("higher dues" not "a higher dues"). Default
    # False keeps the usual singular agreement ("a higher price", "price is").
    plural: bool = False
    # A two-level *hierarchy*: this category's items are partitioned into named
    # groups (e.g. Trades -> Guilds). `group_noun` is the collective noun
    # ("guild"); `groups` is ((label, (item, ...)), ...). Groups are a clue layer
    # only — the category stays an ordinary bijective column, and the grouping
    # surfaces purely in group-clue text. Empty = no hierarchy.
    group_noun: str = ""
    groups: tuple = ()

    def amount(self, n: int) -> str:
        """Format a numeric amount with this category's unit, e.g. '$3' or '20 gp'."""
        return f"{self.unit}{n}{self.unit_suffix}"

    @property
    def verb(self) -> str:
        """Present-tense 'to be' agreeing with the category name in clue text."""
        return "are" if self.plural else "is"

    @property
    def article(self) -> str:
        """Indefinite article before a comparative adjective ('a higher price');
        empty for a plural/mass name ('higher dues')."""
        return "" if self.plural else "a "

    def value(self, item_index: int) -> int:
        """Rank (or numeric value) used by comparison clues."""
        if self.values is not None:
            return self.values[item_index]
        return item_index  # items are listed ascending, so the index is the rank

    @property
    def has_groups(self) -> bool:
        return bool(self.group_noun and self.groups)

    def group_of(self, item: str) -> str | None:
        """The group label containing `item`, or None if it isn't grouped."""
        for label, members in self.groups:
            if item in members:
                return label
        return None


@dataclass
class Theme:
    name: str
    description: str
    categories: list[Category]
    entity_noun: str = "entry"  # how to refer to a single row, e.g. "suspect"

    @property
    def n(self) -> int:
        """Items per category."""
        return len(self.categories[0].items)

    @property
    def k(self) -> int:
        """Number of categories."""
        return len(self.categories)

    def validate(self) -> None:
        if self.k < 2:
            raise ValueError("a puzzle needs at least 2 categories")
        n = self.n
        if n < 2:
            raise ValueError("each category needs at least 2 items")
        for c in self.categories:
            if len(c.items) != n:
                raise ValueError(
                    f"category '{c.name}' has {len(c.items)} items, expected {n} "
                    "(all categories must have the same number of items)"
                )
            if len(set(c.items)) != n:
                raise ValueError(f"category '{c.name}' has duplicate items")
            if c.values is not None and len(c.values) != n:
                raise ValueError(f"category '{c.name}': `values` length must equal item count")
            if c.groups:
                seen: set[str] = set()
                for label, members in c.groups:
                    for m in members:
                        if m not in c.items:
                            raise ValueError(
                                f"category '{c.name}': group '{label}' references "
                                f"unknown item '{m}'"
                            )
                        if m in seen:
                            raise ValueError(
                                f"category '{c.name}': item '{m}' is in more than one group"
                            )
                        seen.add(m)
        # item labels should be globally unique so clue text is unambiguous
        all_items = [it for c in self.categories for it in c.items]
        if len(set(all_items)) != len(all_items):
            raise ValueError(
                "item labels must be unique across ALL categories so clues read unambiguously"
            )
        # Comparison clues read an ordered category's name as a SINGULAR common
        # noun ("a higher price", "the order's price is..."). A plural name
        # ("Earnings", "Dues") then disagrees ("a higher earnings", "earnings
        # is") — UNLESS the author sets `plural=True`, which switches the
        # templates to plural agreement. So warn only when the name looks plural
        # but the flag wasn't set, rather than emit broken prose.
        for c in self.categories:
            if c.ordered and not c.plural and _looks_plural(c.name):
                warnings.warn(
                    f"ordered category '{c.name}' looks like a plural noun; comparison "
                    f"clues assume a singular name and will read with disagreement "
                    f"(e.g. 'a higher {c.name.lower()}', '{c.name.lower()} is') — "
                    "set plural=True or use a singular name.",
                    stacklevel=2,
                )
