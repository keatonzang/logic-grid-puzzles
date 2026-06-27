"""Web/serverless layer: a registry of themes whose members vary per puzzle,
plus a JSON-serialisable puzzle payload.

Kept dependency-free (no file IO, no PyYAML) so it runs cleanly in a serverless
function. Each puzzle samples `items` members from each category's pool and
sorts them alphabetically, so categories always render A→Z. A theme is just a
*spec* (a subject pool, several attribute pools, and an optional ordered numeric
category); `build_theme` turns a spec into a concrete sampled Theme.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .generate import DIFFICULTIES, generate_rated
from .hint import next_hint
from .model import Category, Theme

MIN_ITEMS = 3
MAX_ITEMS = 5
DEFAULT_ITEMS = 4
MIN_CATEGORIES = 3
MAX_CATEGORIES = 5
DEFAULT_CATEGORIES = 3
DEFAULT_DIFFICULTY = "medium"
DEFAULT_THEME = "cafe"

_MAX_SEED = 1_000_000


# --- Theme specs ------------------------------------------------------------
@dataclass(frozen=True)
class NumericSpec:
    """An ordered, numeric category (unlocks comparison / difference clues).

    Values are *evenly spaced* (a random start + step) so "exactly N more" stays
    a relative hint — the gap repeats — rather than pinning exact values. The
    unit wraps amounts in clue text: a prefix (``"$"`` → ``"$2"``) and/or suffix
    (``" gp"`` → ``"20 gp"``).
    """

    name: str
    unit_prefix: str = ""
    unit_suffix: str = ""
    min_start: int = 2
    start_max: int = 12
    steps: tuple = (1, 2)
    prob: float = 0.5  # chance an eligible (medium/hard) puzzle includes it

    def label(self, v: int) -> str:
        return f"{self.unit_prefix}{v}{self.unit_suffix}"


@dataclass(frozen=True)
class ThemeSpec:
    """A puzzle theme: a subject pool (category 0) + attribute pools + optional
    numeric category. Each pool holds enough members to support the largest grid;
    a puzzle samples `items` from each and which attributes appear varies."""

    key: str
    name: str
    description: str
    entity_noun: str
    subject_name: str
    subject_items: tuple
    attributes: tuple  # ((name, (item, ...)), ...)
    numeric: NumericSpec | None = None


THEME_SPECS: tuple = (
    ThemeSpec(
        key="cafe",
        name="The Morning Rush",
        description=(
            "Regulars at the corner café each ordered a different drink and a "
            "different pastry one busy morning. Work out who had what."
        ),
        entity_noun="order",
        subject_name="Customer",
        subject_items=("Ava", "Ben", "Cara", "Dane", "Edith", "Felix", "Greta", "Hugo"),
        attributes=(
            ("Drink", ("Americano", "Chai", "Cortado", "Espresso", "Latte", "Macchiato", "Mocha", "Ristretto")),
            ("Pastry", ("Bagel", "Brioche", "Croissant", "Danish", "Donut", "Muffin", "Scone", "Tart")),
            ("Syrup", ("Almond", "Caramel", "Cinnamon", "Hazelnut", "Maple", "Pumpkin", "Toffee", "Vanilla")),
            ("Mug", ("Amber", "Cobalt", "Crimson", "Ivory", "Jade", "Onyx", "Rose", "Slate")),
        ),
        numeric=NumericSpec("Price", unit_prefix="$", min_start=2, start_max=12, steps=(1, 2)),
    ),
    ThemeSpec(
        key="kings_guild",
        name="The King's Guild",
        description=(
            "Master artisans of the King's Guild each ply a different trade in a "
            "different quarter of the city. Work out who's who."
        ),
        entity_noun="artisan",
        subject_name="Artisan",
        subject_items=("Aldric", "Beatrix", "Cedric", "Edmund", "Godfrey", "Matilda", "Rowan", "Wulfric"),
        attributes=(
            ("Trade", ("Blacksmith", "Carpenter", "Cooper", "Fletcher", "Mason", "Potter", "Tanner", "Weaver")),
            ("Tool", ("Anvil", "Awl", "Chisel", "Hammer", "Loom", "Mallet", "Needle", "Saw")),
            ("Wares", ("Barrels", "Boots", "Candles", "Horseshoes", "Pottery", "Rope", "Saddles", "Tapestries")),
            ("Quarter", ("Bridgegate", "Eastcheap", "Highrow", "Kingsford", "Millpond", "Oldwall", "Riverside", "Southgate")),
            ("Patron", ("Baron", "Bishop", "Countess", "Duke", "Earl", "Knight", "Prince", "Sheriff")),
        ),
        numeric=NumericSpec("Dues", unit_suffix=" coins", min_start=2, start_max=12, steps=(1, 2)),
    ),
    ThemeSpec(
        key="dnd",
        name="The Adventuring Party",
        description=(
            "A band of adventurers gathers at the tavern — each a different race, "
            "wielding a different weapon. Work out who's who."
        ),
        entity_noun="adventurer",
        subject_name="Adventurer",
        subject_items=("Fenwick", "Kael", "Lyra", "Mara", "Orin", "Sable", "Thorne", "Wrenna"),
        attributes=(
            ("Race", ("Dragonborn", "Dwarf", "Elf", "Gnome", "Half-Orc", "Halfling", "Human", "Tiefling")),
            ("Class", ("Barbarian", "Bard", "Cleric", "Druid", "Paladin", "Ranger", "Rogue", "Wizard")),
            ("Weapon", ("Crossbow", "Dagger", "Greataxe", "Longbow", "Longsword", "Quarterstaff", "Rapier", "Warhammer")),
            ("School", ("Abjuration", "Conjuration", "Divination", "Enchantment", "Evocation", "Illusion", "Necromancy", "Transmutation")),
            ("Familiar", ("Cat", "Hawk", "Owl", "Rat", "Raven", "Toad", "Viper", "Wolf")),
        ),
        numeric=NumericSpec("Gold", unit_suffix=" gp", min_start=10, start_max=60, steps=(5, 10)),
    ),
    ThemeSpec(
        key="mystery",
        name="Murder at the Manor",
        description=(
            "A guest lies dead at the manor. Each suspect was in a different room "
            "with a different motive. Work out whodunit."
        ),
        entity_noun="suspect",
        subject_name="Suspect",
        subject_items=("Ashford", "Blackwood", "Crane", "Fairfax", "Grimsby", "Holloway", "Pierce", "Ravenscroft"),
        attributes=(
            ("Room", ("Ballroom", "Cellar", "Conservatory", "Kitchen", "Library", "Lounge", "Study", "Veranda")),
            ("Weapon", ("Candlestick", "Cleaver", "Crowbar", "Dagger", "Pistol", "Poison", "Rope", "Spanner")),
            ("Motive", ("Blackmail", "Envy", "Greed", "Inheritance", "Jealousy", "Revenge", "Secrecy", "Spite")),
            ("Occupation", ("Butler", "Chef", "Doctor", "Gardener", "Governess", "Heir", "Maid", "Valet")),
            ("Alibi", ("Bathing", "Cooking", "Gardening", "Painting", "Reading", "Sleeping", "Walking", "Writing")),
        ),
        numeric=None,
    ),
    ThemeSpec(
        key="space",
        name="The Mars Colony",
        description=(
            "The first colonists of a new Mars settlement each took a different "
            "role and hail from a different world. Work out who's who."
        ),
        entity_noun="colonist",
        subject_name="Colonist",
        subject_items=("Anders", "Bauer", "Cho", "Dasari", "Eklund", "Fontaine", "Okafor", "Rios"),
        attributes=(
            ("Role", ("Botanist", "Captain", "Engineer", "Geologist", "Medic", "Navigator", "Pilot", "Technician")),
            ("Module", ("Aurora", "Beacon", "Cortex", "Drift", "Echo", "Forge", "Helix", "Lumen")),
            ("Homeworld", ("Callisto", "Ceres", "Earth", "Europa", "Ganymede", "Luna", "Titan", "Venus")),
            ("Specimen", ("Algae", "Basalt", "Diatoms", "Fungus", "Geode", "Lichen", "Plankton", "Regolith")),
        ),
        numeric=NumericSpec("Distance", unit_suffix=" ly", min_start=4, start_max=16, steps=(1, 2)),
    ),
    ThemeSpec(
        key="engineer",
        name="The Engineering Firm",
        description=(
            "Each engineer at the firm leads a different project in a different "
            "discipline. Work out who's building what."
        ),
        entity_noun="engineer",
        subject_name="Engineer",
        subject_items=("Bell", "Diesel", "Edison", "Ford", "Hertz", "Otis", "Tesla", "Watt"),
        attributes=(
            ("Discipline", ("Aerospace", "Chemical", "Civil", "Electrical", "Mechanical", "Robotics", "Software", "Structural")),
            ("Project", ("Bridge", "Dam", "Pipeline", "Reactor", "Rover", "Satellite", "Skyscraper", "Turbine")),
            ("Material", ("Aluminum", "Carbon", "Concrete", "Copper", "Graphene", "Steel", "Titanium", "Tungsten")),
            ("Tool", ("Blowtorch", "Caliper", "Drill", "Laser", "Multimeter", "Oscilloscope", "Welder", "Wrench")),
        ),
        numeric=NumericSpec("Budget", unit_prefix="$", unit_suffix="k", min_start=10, start_max=40, steps=(5, 10)),
    ),
    ThemeSpec(
        key="school",
        name="The Schoolhouse",
        description=(
            "Each teacher at the schoolhouse leads a different class in a "
            "different room. Work out who teaches what, and where."
        ),
        entity_noun="class",
        subject_name="Teacher",
        subject_items=("Ames", "Boyd", "Carver", "Dunn", "Ellis", "Frost", "Hale", "Nash"),
        attributes=(
            ("Subject", ("Art", "Biology", "Chemistry", "English", "French", "Geography", "History", "Music")),
            ("Room", ("Annex", "Bungalow", "Cloister", "Greenhouse", "Library", "Pavilion", "Studio", "Workshop")),
            ("Student", ("Iris", "Jonah", "Kira", "Liam", "Mona", "Noah", "Piper", "Quinn")),
            ("Club", ("Chess", "Choir", "Debate", "Drama", "Robotics", "Rowing", "Scouts", "Yearbook")),
        ),
        numeric=NumericSpec("Grade", unit_suffix="%", min_start=70, start_max=80, steps=(2, 5)),
    ),
)

THEMES: dict = {spec.key: spec for spec in THEME_SPECS}


def list_themes() -> list[dict]:
    """Catalogue of available themes (key, name, description) for the UI picker."""
    return [
        {"key": s.key, "name": s.name, "description": s.description}
        for s in THEME_SPECS
    ]


def clamp_items(items: int) -> int:
    return max(MIN_ITEMS, min(MAX_ITEMS, int(items)))


def clamp_categories(categories: int) -> int:
    return max(MIN_CATEGORIES, min(MAX_CATEGORIES, int(categories)))


# More categories => fewer items, so the uniqueness search (n!^(k-1)) and the
# generate-and-grade loop stay fast. (A 5x6 logic grid is impractical anyway.)
_MAX_ITEMS_BY_K = {3: 5, 4: 4, 5: 4}


def max_items_for(categories: int) -> int:
    return _MAX_ITEMS_BY_K.get(clamp_categories(categories), MAX_ITEMS)


def build_theme(
    spec: ThemeSpec,
    rng: random.Random,
    items: int,
    categories: int = DEFAULT_CATEGORIES,
    use_numeric: bool = False,
) -> Theme:
    """Sample a concrete theme from a spec: the subject + (K-1) attribute
    categories, optionally one of which is the ordered numeric category. Members
    are alphabetised (numeric by value). Which attributes appear varies per draw.
    """
    k = clamp_categories(categories)
    items = min(clamp_items(items), max_items_for(k))  # fewer items as k grows
    cats = [Category(spec.subject_name, sorted(rng.sample(spec.subject_items, items)))]

    has_numeric = use_numeric and spec.numeric is not None
    n_attr = k - 1 - (1 if has_numeric else 0)
    names = [name for name, _ in spec.attributes]
    pools = dict(spec.attributes)
    chosen = sorted(rng.sample(names, n_attr), key=names.index)  # canonical order
    for name in chosen:
        cats.append(Category(name, sorted(rng.sample(pools[name], items))))

    if has_numeric:
        ns = spec.numeric
        step = rng.choice(ns.steps)
        start = rng.randint(ns.min_start, ns.start_max)
        values = [start + i * step for i in range(items)]  # evenly spaced = rank order
        cats.append(
            Category(
                ns.name,
                [ns.label(v) for v in values],
                ordered=True,
                values=values,
                unit=ns.unit_prefix,
                unit_suffix=ns.unit_suffix,
            )
        )

    theme = Theme(
        name=spec.name,
        description=spec.description,
        categories=cats,
        entity_noun=spec.entity_noun,
    )
    theme.validate()
    return theme


# Backwards-compatible café helpers (used by the test suite and older callers).
SUBJECT = (THEMES["cafe"].subject_name, list(THEMES["cafe"].subject_items))
ATTRIBUTE_POOLS = {name: list(items) for name, items in THEMES["cafe"].attributes}


def build_cafe_theme(
    rng: random.Random,
    items: int,
    categories: int = DEFAULT_CATEGORIES,
    use_price: bool = False,
) -> Theme:
    """The café theme (kept for callers/tests); see ``build_theme``."""
    return build_theme(THEMES["cafe"], rng, items, categories, use_price)


def _solution_rows(theme: Theme, X: list[list[int]]) -> list[list[str]]:
    """Solution as rows of item labels — row e lists each category's item for entity e."""
    return [
        [theme.categories[c].items[X[e][c]] for c in range(theme.k)]
        for e in range(theme.n)
    ]


def build_puzzle(
    seed: int | None = None,
    difficulty: str = DEFAULT_DIFFICULTY,
    items: int = DEFAULT_ITEMS,
    categories: int = DEFAULT_CATEGORIES,
    theme: str = DEFAULT_THEME,
):
    """Generate a puzzle, returning the live objects ``(theme, puzzle, report,
    seed)``.

    Deterministic in ``(seed, theme, difficulty, items, categories)``: the same
    inputs always rebuild the identical puzzle (including the up-front numeric
    roll), so the hint endpoint can regenerate exactly what the player sees. A
    concrete ``seed`` is always resolved and returned.
    """
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"unknown difficulty: {difficulty!r}")
    spec = THEMES.get(theme)
    if spec is None:
        raise ValueError(f"unknown theme: {theme!r}")
    items = clamp_items(items)
    categories = clamp_categories(categories)
    if seed is None:
        seed = random.randrange(_MAX_SEED)

    rng = random.Random(seed)
    use_numeric = False
    if spec.numeric is not None and difficulty in ("medium", "hard"):
        use_numeric = rng.random() < spec.numeric.prob  # rolled once, up front

    theme_obj, puzzle, report = generate_rated(
        lambda r: build_theme(spec, r, items, categories, use_numeric), rng, difficulty
    )
    return theme_obj, puzzle, report, seed


def build_hint(
    seed: int,
    difficulty: str,
    items: int,
    categories: int,
    known: dict | None,
    theme: str = DEFAULT_THEME,
) -> dict:
    """Next single explained deduction for the puzzle the inputs identify.

    Regenerates the exact puzzle and asks the hint engine for the first step the
    player (``known`` board) hasn't already made. ``known`` maps ``"i-j"`` to an
    n×n matrix of 0 blank / 1 link / 2 no-link, matching a hint's ``value``.
    """
    theme_obj, puzzle, _report, _seed = build_puzzle(seed, difficulty, items, categories, theme)
    return next_hint(theme_obj, puzzle.clues, known)


def build_payload(
    seed: int | None = None,
    difficulty: str = DEFAULT_DIFFICULTY,
    items: int = DEFAULT_ITEMS,
    categories: int = DEFAULT_CATEGORIES,
    theme: str = DEFAULT_THEME,
) -> dict:
    """Generate a puzzle and return a JSON-serialisable description.

    A concrete ``seed`` (and the ``theme`` key) are echoed back so any puzzle can
    be reproduced from the response alone. Whether the ordered numeric category is
    included is rolled once up front (only for medium/hard themes that have one).
    """
    theme_obj, puzzle, report, seed = build_puzzle(seed, difficulty, items, categories, theme)

    return {
        "theme": theme,
        "name": theme_obj.name,
        "description": theme_obj.description,
        "entity_noun": theme_obj.entity_noun,
        "seed": seed,
        "requested": difficulty,
        "difficulty": report["band"],  # the *measured* difficulty (no guessing)
        "items": len(theme_obj.categories[0].items),  # actual (capped) items per category
        "n_categories": len(theme_obj.categories),
        "has_price": any(c.ordered for c in theme_obj.categories),  # has an ordered category
        "rating": {  # how the deductive solver graded it
            "ceiling": report["ceiling"],
            "steps": report["steps"],
            "total_steps": report["total_steps"],
        },
        "categories": [
            {"name": c.name, "items": list(c.items)} for c in theme_obj.categories
        ],
        "clues": [clue.text(theme_obj) for clue in puzzle.clues],
        "solution": _solution_rows(theme_obj, puzzle.solution),
    }
