"""Web/serverless layer: a single café theme whose members vary per puzzle,
plus a JSON-serialisable puzzle payload.

Kept dependency-free (no file IO, no PyYAML) so it runs cleanly in a serverless
function. Each puzzle samples `items` members from each category's pool and
sorts them alphabetically, so categories always render A→Z.
"""

from __future__ import annotations

import random

from .generate import DIFFICULTIES, generate_rated
from .model import Category, Theme

# The single theme. Categories are fixed (3); their members are sampled from
# these pools so every puzzle is a fresh draw. Pools are large enough to support
# the maximum grid size, and labels are globally unique across categories.
CAFE_NAME = "The Morning Rush"
CAFE_DESCRIPTION = (
    "Regulars at the corner café each ordered a different drink and a different "
    "pastry one busy morning. Work out who had what."
)
CAFE_ENTITY_NOUN = "order"
# The subject category (always category 0, the people) plus a pool of
# non-ordered attribute categories. A puzzle uses Customer + a sample of these.
SUBJECT = ("Customer", ["Ava", "Ben", "Cara", "Dane", "Edith", "Felix", "Greta", "Hugo"])
ATTRIBUTE_POOLS: dict[str, list[str]] = {
    "Drink": ["Americano", "Chai", "Cortado", "Espresso", "Latte", "Macchiato", "Mocha", "Ristretto"],
    "Pastry": ["Bagel", "Brioche", "Croissant", "Danish", "Donut", "Muffin", "Scone", "Tart"],
    "Syrup": ["Almond", "Caramel", "Cinnamon", "Hazelnut", "Maple", "Pumpkin", "Toffee", "Vanilla"],
    "Mug": ["Amber", "Cobalt", "Crimson", "Ivory", "Jade", "Onyx", "Rose", "Slate"],
}
# Ordered/numeric Price category, sampled in (probabilistically) instead of a
# toggle. Sorted by value (ascending = rank), enabling the sequential clues.
PRICE_POOL = [3, 4, 5, 6, 7, 8, 9, 10]
PRICE_PROB = 0.5  # chance an eligible (medium/hard) puzzle includes Price

MIN_ITEMS = 3
MAX_ITEMS = 5
DEFAULT_ITEMS = 4
MIN_CATEGORIES = 3
MAX_CATEGORIES = 5
DEFAULT_CATEGORIES = 3
DEFAULT_DIFFICULTY = "medium"

_MAX_SEED = 1_000_000


def clamp_items(items: int) -> int:
    return max(MIN_ITEMS, min(MAX_ITEMS, int(items)))


def clamp_categories(categories: int) -> int:
    return max(MIN_CATEGORIES, min(MAX_CATEGORIES, int(categories)))


# More categories => fewer items, so the uniqueness search (n!^(k-1)) and the
# generate-and-grade loop stay fast. (A 5x6 logic grid is impractical anyway.)
_MAX_ITEMS_BY_K = {3: 5, 4: 4, 5: 4}


def max_items_for(categories: int) -> int:
    return _MAX_ITEMS_BY_K.get(clamp_categories(categories), MAX_ITEMS)


def build_cafe_theme(
    rng: random.Random,
    items: int,
    categories: int = DEFAULT_CATEGORIES,
    use_price: bool = False,
) -> Theme:
    """Sample a café theme: Customer + (K-1) attribute categories, optionally one
    of which is the ordered numeric Price. Members are alphabetised (Price by
    value). Which attributes appear varies per draw."""
    k = clamp_categories(categories)
    items = min(clamp_items(items), max_items_for(k))  # fewer items as k grows
    cats = [Category(SUBJECT[0], sorted(rng.sample(SUBJECT[1], items)))]

    n_attr = k - 1 - (1 if use_price else 0)
    order = list(ATTRIBUTE_POOLS)
    chosen = sorted(rng.sample(order, n_attr), key=order.index)  # canonical order
    for name in chosen:
        cats.append(Category(name, sorted(rng.sample(ATTRIBUTE_POOLS[name], items))))

    if use_price:
        values = sorted(rng.sample(PRICE_POOL, items))  # ascending = rank order
        cats.append(Category("Price", [f"${v}" for v in values], ordered=True, values=values))

    theme = Theme(
        name=CAFE_NAME,
        description=CAFE_DESCRIPTION,
        categories=cats,
        entity_noun=CAFE_ENTITY_NOUN,
    )
    theme.validate()
    return theme


def _solution_rows(theme: Theme, X: list[list[int]]) -> list[list[str]]:
    """Solution as rows of item labels — row e lists each category's item for entity e."""
    return [
        [theme.categories[c].items[X[e][c]] for c in range(theme.k)]
        for e in range(theme.n)
    ]


def build_payload(
    seed: int | None = None,
    difficulty: str = DEFAULT_DIFFICULTY,
    items: int = DEFAULT_ITEMS,
    categories: int = DEFAULT_CATEGORIES,
) -> dict:
    """Generate a puzzle and return a JSON-serialisable description.

    A concrete ``seed`` is always resolved and echoed back so any puzzle can be
    reproduced from the response alone. Whether the ordered Price category is
    included is rolled once up front (only for medium/hard, where its sequential
    clues are enabled).
    """
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"unknown difficulty: {difficulty!r}")
    items = clamp_items(items)
    categories = clamp_categories(categories)
    if seed is None:
        seed = random.randrange(_MAX_SEED)

    rng = random.Random(seed)
    allow_price = difficulty in ("medium", "hard")
    use_price = allow_price and rng.random() < PRICE_PROB  # rolled once, up front

    theme, puzzle, report = generate_rated(
        lambda r: build_cafe_theme(r, items, categories, use_price), rng, difficulty
    )

    return {
        "name": theme.name,
        "description": theme.description,
        "entity_noun": theme.entity_noun,
        "seed": seed,
        "requested": difficulty,
        "difficulty": report["band"],  # the *measured* difficulty (no guessing)
        "items": len(theme.categories[0].items),  # actual (capped) items per category
        "n_categories": len(theme.categories),
        "has_price": any(c.ordered for c in theme.categories),
        "rating": {  # how the deductive solver graded it
            "ceiling": report["ceiling"],
            "steps": report["steps"],
            "total_steps": report["total_steps"],
        },
        "categories": [
            {"name": c.name, "items": list(c.items)} for c in theme.categories
        ],
        "clues": [clue.text(theme) for clue in puzzle.clues],
        "solution": _solution_rows(theme, puzzle.solution),
    }
