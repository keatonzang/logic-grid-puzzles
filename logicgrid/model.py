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

from dataclasses import dataclass


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

    def amount(self, n: int) -> str:
        """Format a numeric amount with this category's unit, e.g. '$3' or '20 gp'."""
        return f"{self.unit}{n}{self.unit_suffix}"

    def value(self, item_index: int) -> int:
        """Rank (or numeric value) used by comparison clues."""
        if self.values is not None:
            return self.values[item_index]
        return item_index  # items are listed ascending, so the index is the rank


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
        # item labels should be globally unique so clue text is unambiguous
        all_items = [it for c in self.categories for it in c.items]
        if len(set(all_items)) != len(all_items):
            raise ValueError(
                "item labels must be unique across ALL categories so clues read unambiguously"
            )
