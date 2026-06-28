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
    """An ordered category (unlocks comparison clues).

    When ``valued`` (the default) it is *numeric*: items carry evenly-spaced
    values (a random start + step) so "exactly N more" stays a relative hint — the
    gap repeats — rather than pinning exact values, and the unit wraps amounts in
    clue text: a prefix (``"$"`` → ``"$2"``) and/or suffix (``" gp"`` → ``"20 gp"``).

    When ``valued`` is False it is a plain *ordinal* (e.g. a class Period): items
    are 1..N rendered through the unit ("Period 1"), the category has rank order
    but no values, so it gets higher/lower / next-to / between clues but never the
    exact-difference ones ("2 more" makes no sense for an ordinal).
    """

    name: str
    unit_prefix: str = ""
    unit_suffix: str = ""
    min_start: int = 2
    start_max: int = 12
    steps: tuple = (1, 2)
    prob: float = 0.5  # chance an eligible (medium/hard) puzzle includes it
    valued: bool = True  # False => ordinal only (no exact-difference clues)

    def label(self, v: int) -> str:
        return f"{self.unit_prefix}{v}{self.unit_suffix}"


@dataclass(frozen=True)
class ThemeSpec:
    """A puzzle theme: a subject pool (category 0) + attribute pools + optional
    ordered/numeric categories. Each pool holds enough members to support the
    largest grid; a puzzle samples `items` from each and which attributes appear
    varies.

    ``numeric`` is the primary ordered category (rolled in on medium/hard).
    ``extra_numerics`` are additional ordered categories — only ever rolled in on
    hard puzzles with enough categories (see ``build_puzzle``), so a theme can
    offer two sequential dials (e.g. a class's Grade *and* its Period)."""

    key: str
    name: str
    description: str
    entity_noun: str
    subject_name: str
    subject_items: tuple
    attributes: tuple  # ((name, (item, ...)), ...)
    numeric: NumericSpec | None = None
    extra_numerics: tuple = ()  # further ordered categories, hard-only
    # ((category_name, "the person studying {}"), ...) — how a non-subject
    # category names an entity by its item in cross-category clue text. Anything
    # unlisted falls back to "the {entity_noun} with {item}".
    referents: tuple = ()
    # Optional two-level hierarchies. Each entry is
    #   (category_name, group_noun, ((label, (item, ...)), ...))
    # partitioning that category's *full pool* into named groups (e.g. Trade ->
    # guilds, Quarter -> wards). Rolled in only sometimes (see build_puzzle) and
    # only surfaces via group clues, so a puzzle can have no hierarchy at all. Two
    # partitions on one theme additionally unlock cross-group clues.
    group_defs: tuple = ()

    @property
    def numerics(self) -> tuple:
        """All ordered categories, primary first."""
        primary = (self.numeric,) if self.numeric is not None else ()
        return primary + self.extra_numerics


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
        # Two two-level hierarchies. Each Trade belongs to a guild, and each
        # Quarter sits in a ward of the city. Surface only via group clues
        # ("Aldric belongs to the Ironmongers' Guild", "Aldric and Beatrix are in
        # the same guild") and only when rolled in. With both present, cross-group
        # clues become possible ("exactly two Ironmongers live in the Hill Ward").
        group_defs=(
            (
                "Trade",
                "guild",
                (
                    ("Ironmongers' Guild", ("Blacksmith", "Fletcher", "Mason")),
                    ("Joiners' Guild", ("Carpenter", "Cooper", "Potter")),
                    ("Clothiers' Guild", ("Tanner", "Weaver")),
                ),
            ),
            (
                "Quarter",
                "ward",
                (
                    ("Hill Ward", ("Highrow", "Kingsford", "Oldwall")),
                    ("River Ward", ("Bridgegate", "Millpond", "Riverside")),
                    ("Market Ward", ("Eastcheap", "Southgate")),
                ),
            ),
        ),
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
        # A second ordered dial (hard, K>=4 only): which class period it meets —
        # an ordinal ("Period 1".."Period N"), so higher/next-to but no "2 more".
        extra_numerics=(NumericSpec("Period", unit_prefix="Period ", valued=False),),
        referents=(
            ("Subject", "the {} class"),          # the Biology class
            ("Room", "the class in the {}"),       # the class in the Annex
            ("Club", "the person studying {}"),    # the person studying Debate
            ("Period", "the class in {}"),         # the class in Period 3
        ),
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


def _restrict_groups(full_groups: tuple, items: list) -> tuple:
    """Keep only sampled items in each group and drop groups left empty."""
    iset = set(items)
    out = []
    for label, members in full_groups:
        keep = tuple(m for m in members if m in iset)
        if keep:
            out.append((label, keep))
    return tuple(out)


def build_theme(
    spec: ThemeSpec,
    rng: random.Random,
    items: int,
    categories: int = DEFAULT_CATEGORIES,
    n_numeric: int = 0,
    use_groups: bool = False,
) -> Theme:
    """Sample a concrete theme from a spec: the subject + (K-1) attribute
    categories, ``n_numeric`` of which are this theme's ordered categories (primary
    first). Members are alphabetised (numeric by value); which attributes appear
    varies per draw. ``n_numeric`` accepts a bool too (False/True -> 0/1).

    When ``use_groups`` and the spec declares one or more ``group_defs``, those
    grouped categories are force-included (as many as fit) and get their
    (sampled-restricted) partitions, so the theme can carry one or two hierarchies.
    """
    k = clamp_categories(categories)
    items = min(clamp_items(items), max_items_for(k))  # fewer items as k grows
    cats = [Category(spec.subject_name, sorted(rng.sample(spec.subject_items, items)))]

    refs = dict(spec.referents)  # category name -> referent template
    numerics = spec.numerics[: int(n_numeric)]
    numerics = numerics[: k - 1]  # never more ordered categories than non-subject slots
    n_attr = k - 1 - len(numerics)
    names = [name for name, _ in spec.attributes]
    pools = dict(spec.attributes)

    # Force-include the grouped categories when rolling a hierarchy (as many as the
    # attribute slots allow); each keeps its name -> (group_noun, partition) here.
    gdefs = {gd[0]: gd for gd in spec.group_defs} if use_groups else {}
    forced = [nm for nm in names if nm in gdefs][: max(0, n_attr)]
    rest = [nm for nm in names if nm not in forced]
    chosen = forced + rng.sample(rest, n_attr - len(forced))
    chosen = sorted(chosen, key=names.index)  # canonical order
    for name in chosen:
        pool_items = sorted(rng.sample(pools[name], items))
        kwargs = {"referent": refs.get(name, "")}
        if name in forced and name in gdefs:
            kwargs["group_noun"] = gdefs[name][1]
            kwargs["groups"] = _restrict_groups(gdefs[name][2], pool_items)
        cats.append(Category(name, pool_items, **kwargs))

    for ns in numerics:
        if ns.valued:
            step = rng.choice(ns.steps)
            start = rng.randint(ns.min_start, ns.start_max)
            values = [start + i * step for i in range(items)]  # evenly spaced = rank order
            labels = [ns.label(v) for v in values]
        else:  # ordinal: 1..N in rank order, no values (no difference clues)
            values = None
            labels = [ns.label(i + 1) for i in range(items)]
        cats.append(
            Category(
                ns.name,
                labels,
                ordered=True,
                values=values,
                unit=ns.unit_prefix,
                unit_suffix=ns.unit_suffix,
                referent=refs.get(ns.name, ""),
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
    return build_theme(THEMES["cafe"], rng, items, categories, int(use_price))


def _solution_rows(theme: Theme, X: list[list[int]]) -> list[list[str]]:
    """Solution as rows of item labels — row e lists each category's item for entity e."""
    return [
        [theme.categories[c].items[X[e][c]] for c in range(theme.k)]
        for e in range(theme.n)
    ]


def _roll_n_numeric(spec: ThemeSpec, difficulty: str, categories: int, rng: random.Random) -> int:
    """How many ordered categories this puzzle includes (consumes ``rng``).

    The primary ordered category appears on medium/hard at its ``prob``. A second
    ordered dial is gated: hard difficulty, K >= 4, and its own ``prob`` roll —
    so it stays an occasional flavour, never the default.
    """
    avail = spec.numerics
    if not avail or difficulty not in ("medium", "hard"):
        return 0
    n = 1 if rng.random() < avail[0].prob else 0
    if (
        n == 1
        and len(avail) >= 2
        and difficulty == "hard"
        and clamp_categories(categories) >= 4
        and rng.random() < avail[1].prob
    ):
        n = 2
    return n


GROUP_PROB = 0.5  # chance an eligible (medium/hard) puzzle rolls in its hierarchy


def _roll_use_groups(spec: ThemeSpec, difficulty: str, rng: random.Random) -> bool:
    """Whether to include the theme's group hierarchy (consumes ``rng`` only when
    the theme actually has one, so other themes' sequences are unaffected)."""
    if not spec.group_defs or difficulty not in ("medium", "hard"):
        return False
    return rng.random() < GROUP_PROB


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
    rolls), so the hint endpoint can regenerate exactly what the player sees. A
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

    # How many ordered categories to roll in (decided up front so it's part of the
    # deterministic puzzle). The primary numeric appears on medium/hard; a second
    # ordered dial is gated to hard puzzles with enough categories to spare.
    rng = random.Random(seed)
    n_numeric = _roll_n_numeric(spec, difficulty, categories, rng)
    use_groups = _roll_use_groups(spec, difficulty, rng)  # only consumes rng if theme has a group_def

    theme_obj, puzzle, report = generate_rated(
        lambda r: build_theme(spec, r, items, categories, n_numeric, use_groups), rng, difficulty
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


def _category_payload(c) -> dict:
    """Serialise a category for the client, including its group partition (the
    guild/ward each item belongs to) so the UI can show and solve the groups."""
    out = {"name": c.name, "items": list(c.items)}
    if c.has_groups:
        out["group_noun"] = c.group_noun
        out["groups"] = [{"label": label, "items": list(members)} for label, members in c.groups]
    return out


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
        "categories": [_category_payload(c) for c in theme_obj.categories],
        "clues": [clue.text(theme_obj) for clue in puzzle.clues],
        "solution": _solution_rows(theme_obj, puzzle.solution),
    }
