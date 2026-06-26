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
CAFE_POOLS: dict[str, list[str]] = {
    "Customer": ["Ava", "Ben", "Cara", "Dane", "Edith", "Felix", "Greta", "Hugo"],
    "Drink": ["Americano", "Chai", "Cortado", "Espresso", "Latte", "Macchiato", "Mocha", "Ristretto"],
    "Pastry": ["Bagel", "Brioche", "Croissant", "Danish", "Donut", "Muffin", "Scone", "Tart"],
}
# Optional ordered/numeric 4th category. Sampled prices are sorted by value
# (ascending = rank), enabling the sequential clues (more/less, exact-diff,
# between, immediately-before/after).
PRICE_POOL = [3, 4, 5, 6, 7, 8, 9, 10]

MIN_ITEMS = 3
MAX_ITEMS = 6
DEFAULT_ITEMS = 4
DEFAULT_DIFFICULTY = "medium"

_MAX_SEED = 1_000_000


def clamp_items(items: int) -> int:
    return max(MIN_ITEMS, min(MAX_ITEMS, int(items)))


def build_cafe_theme(rng: random.Random, items: int, with_price: bool = False) -> Theme:
    """Sample `items` members for each café category (sorted alphabetically). With
    `with_price`, append an ordered numeric Price category (sorted by value)."""
    categories = [
        Category(name, sorted(rng.sample(pool, items)))
        for name, pool in CAFE_POOLS.items()
    ]
    if with_price:
        values = sorted(rng.sample(PRICE_POOL, items))  # ascending = rank order
        categories.append(
            Category("Price", [f"${v}" for v in values], ordered=True, values=values)
        )
    theme = Theme(
        name=CAFE_NAME,
        description=CAFE_DESCRIPTION,
        categories=categories,
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
    with_price: bool = False,
) -> dict:
    """Generate a puzzle and return a JSON-serialisable description.

    A concrete ``seed`` is always resolved and echoed back so any puzzle can be
    reproduced from the response alone.
    """
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"unknown difficulty: {difficulty!r}")
    items = clamp_items(items)
    if seed is None:
        seed = random.randrange(_MAX_SEED)

    rng = random.Random(seed)
    theme, puzzle, report = generate_rated(
        lambda r: build_cafe_theme(r, items, with_price), rng, difficulty
    )

    return {
        "name": theme.name,
        "description": theme.description,
        "entity_noun": theme.entity_noun,
        "seed": seed,
        "requested": difficulty,
        "difficulty": report["band"],  # the *measured* difficulty (no guessing)
        "items": items,
        "with_price": with_price,
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
