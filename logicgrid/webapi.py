"""Web/serverless layer: a registry of built-in themes plus a JSON-serialisable
puzzle payload.

Kept deliberately dependency-free (no file IO, no PyYAML) so it runs cleanly
inside a serverless function with a cold start. The theme dicts below mirror the
canonical YAML files in ``themes/`` — keep them in sync if the YAML changes.
"""

from __future__ import annotations

import random

from .generate import generate_puzzle
from .model import Theme
from .themes import theme_from_dict

# Mirror of themes/*.yaml, embedded so the function needs no file access.
THEME_DICTS: dict[str, dict] = {
    "morning_rush": {
        "name": "The Morning Rush",
        "description": (
            "Four regulars each ordered a different drink and a different pastry "
            "one busy morning at the corner cafe. Work out who had what."
        ),
        "entity_noun": "order",
        "categories": [
            {"name": "Customer", "items": ["Ava", "Ben", "Cara", "Dane"]},
            {"name": "Drink", "items": ["Latte", "Mocha", "Cortado", "Chai"]},
            {"name": "Pastry", "items": ["Scone", "Bagel", "Muffin", "Donut"]},
        ],
    },
    "detectives": {
        "name": "The Vanished Heirloom",
        "description": (
            "A priceless heirloom has gone missing from the manor. Four "
            "detectives each questioned a different suspect, in a different "
            "room, about a different object. Use the clues to work out who did "
            "what."
        ),
        "entity_noun": "case",
        "categories": [
            {"name": "Detective", "items": ["Holmes", "Marple", "Poirot", "Spade"]},
            {"name": "Suspect", "items": ["Butler", "Cousin", "Gardener", "Maid"]},
            {"name": "Room", "items": ["Library", "Study", "Cellar", "Attic"]},
            {"name": "Object", "items": ["Locket", "Painting", "Ledger", "Brooch"]},
        ],
    },
    "space_colony": {
        "name": "Frontier Landings",
        "description": (
            "Five colony ships touched down on the new world in different "
            "years, each captained by a different officer and carrying a "
            "different cargo. Work out the full manifest."
        ),
        "entity_noun": "ship",
        "categories": [
            {"name": "Ship", "items": ["Aurora", "Borealis", "Cygnus", "Dragon", "Equinox"]},
            {"name": "Captain", "items": ["Reyes", "Okafor", "Sato", "Nazari", "Lindqvist"]},
            {"name": "Cargo", "items": ["Seedstock", "Reactors", "Medicine", "Livestock", "Textiles"]},
            {
                "name": "Landing",
                "items": ["2161", "2164", "2167", "2170", "2173"],
                "ordered": True,
                "values": [2161, 2164, 2167, 2170, 2173],
            },
        ],
    },
}

DEFAULT_THEME = "morning_rush"
_MAX_SEED = 1_000_000


def list_themes() -> list[dict]:
    """Lightweight catalogue for populating a theme picker."""
    out = []
    for key, data in THEME_DICTS.items():
        out.append(
            {
                "key": key,
                "name": data["name"],
                "description": data["description"],
                "size": len(data["categories"][0]["items"]),
                "categories": len(data["categories"]),
            }
        )
    return out


def get_theme(theme_key: str) -> Theme:
    if theme_key not in THEME_DICTS:
        raise KeyError(theme_key)
    return theme_from_dict(THEME_DICTS[theme_key])


def _solution_rows(theme: Theme, X: list[list[int]]) -> list[list[str]]:
    """Solution as rows of item labels — row e lists each category's item for entity e."""
    return [
        [theme.categories[c].items[X[e][c]] for c in range(theme.k)]
        for e in range(theme.n)
    ]


def build_payload(theme_key: str = DEFAULT_THEME, seed: int | None = None) -> dict:
    """Generate a puzzle and return a JSON-serialisable description.

    A concrete ``seed`` is always resolved and echoed back so any puzzle can be
    reproduced from the response alone.
    """
    if theme_key not in THEME_DICTS:
        raise KeyError(theme_key)
    if seed is None:
        seed = random.randrange(_MAX_SEED)

    theme = theme_from_dict(THEME_DICTS[theme_key])
    rng = random.Random(seed)
    puzzle = generate_puzzle(theme, rng)

    return {
        "theme": theme_key,
        "name": theme.name,
        "description": theme.description,
        "entity_noun": theme.entity_noun,
        "seed": seed,
        "categories": [
            {"name": c.name, "items": list(c.items), "ordered": c.ordered}
            for c in theme.categories
        ],
        "clues": [clue.text(theme) for clue in puzzle.clues],
        "solution": _solution_rows(theme, puzzle.solution),
    }
