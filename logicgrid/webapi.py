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

from .deduce import difficulty_index
from .generate import DIFFICULTIES, generate_rated
from .hint import next_hint
from .model import Category, Theme

def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 3 -> '3rd', 4 -> '4th', … (used for placing labels)."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


MIN_ITEMS = 3
MAX_ITEMS = 5
DEFAULT_ITEMS = 4
MIN_CATEGORIES = 3
MAX_CATEGORIES = 5
DEFAULT_CATEGORIES = 3
DEFAULT_DIFFICULTY = "normal"
# Tiers above `normal` that unlock the extra flavour dials (numerics/hierarchies).
_NONTRIVIAL = ("hard", "mega", "giga", "tera")
_RICH = ("mega", "giga", "tera")  # the conditional/pairing/match tiers
DEFAULT_THEME = "cafe"
# Payloads built from a user-supplied theme document echo this instead of a
# registry key; the client must re-send the document itself to /api/hint.
CUSTOM_THEME_KEY = "custom"
# User themes are concrete (no sampling), so they may be a touch smaller or
# larger than the registry clamps — bounded to keep serverless generation fast.
MIN_CUSTOM_ITEMS, MAX_CUSTOM_ITEMS = 2, 6
MIN_CUSTOM_CATEGORIES, MAX_CUSTOM_CATEGORIES = 2, 6

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

    ``ordinal`` (implies not valued) renders *placing* words — "1st", "2nd", … —
    with the BEST place at the top of the rank order, so the engine's "higher"
    reads as "placed better" (1st outranks 5th). Use for finishing positions.
    """

    name: str
    unit_prefix: str = ""
    unit_suffix: str = ""
    min_start: int = 2
    start_max: int = 12
    steps: tuple = (1, 2)
    prob: float = 0.5  # chance an eligible (medium/hard) puzzle includes it
    valued: bool = True  # False => ordinal only (no exact-difference clues)
    ordinal: bool = False  # render placing words (1st, 2nd, …); 1st = highest rank

    def label(self, v: int) -> str:
        return f"{self.unit_prefix}{v}{self.unit_suffix}"


@dataclass(frozen=True)
class ThemeSpec:
    """A puzzle theme: a subject pool (category 0) + attribute pools + optional
    ordered/numeric categories. Each pool holds enough members to support the
    largest grid; a puzzle samples `items` from each and which attributes appear
    varies.

    ``numeric`` is the primary ordered category (rolled in on hard and up).
    ``extra_numerics`` are additional ordered categories — only ever rolled in on
    the rich tiers (mega and up) with enough categories (see ``build_puzzle``),
    so a theme can offer two sequential dials (e.g. a class's Grade *and* its
    Period)."""

    key: str
    name: str
    description: str
    entity_noun: str
    subject_name: str
    subject_items: tuple
    attributes: tuple  # ((name, (item, ...)), ...)
    numeric: NumericSpec | None = None
    extra_numerics: tuple = ()  # further ordered categories, rich tiers (mega+) only
    # ((category_name, "the person studying {}"), ...) — how a non-subject
    # category names an entity by its item in cross-category clue text. Anything
    # unlisted falls back to "the {entity_noun} with {item}".
    referents: tuple = ()
    # Optional two-level hierarchies. Each entry is
    #   (category_name, group_noun, ((label, (item, ...)), ...)[, fixed])
    # partitioning that category's *full pool* into named groups (e.g. Trade ->
    # guilds, Quarter -> wards). Rolled in only sometimes (see build_puzzle) and
    # only surfaces via group clues, so a puzzle can have no hierarchy at all. Two
    # partitions on one theme additionally unlock cross-group clues.
    # The optional 4th element ``fixed`` (default False) keeps the *declared*
    # membership instead of randomising it — use it when the groups are factual
    # (e.g. King's-Pawn vs Queen's-Pawn openings) and shuffling would print lies.
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
        referents=(
            ("Drink", "the {} order"),               # the Latte order
            ("Pastry", "the order with the {}"),     # the order with the Croissant
            ("Syrup", "the order with {} syrup"),    # the order with Vanilla syrup
            ("Mug", "the order in the {} mug"),      # the order in the Onyx mug
        ),
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
        numeric=NumericSpec("Levy", unit_suffix=" coins", min_start=2, start_max=12, steps=(1, 2)),
        referents=(
            ("Trade", "the {}"),                     # the Tanner (a trade names the artisan)
            ("Tool", "the artisan with the {}"),     # the artisan with the Anvil
            ("Wares", "the artisan who makes {}"),   # the artisan who makes Barrels
            ("Quarter", "the artisan in {}"),        # the artisan in Eastcheap
            ("Patron", "the artisan serving the {}"),# the artisan serving the Baron
        ),
        # Two two-level hierarchies: Trades group into guilds, Quarters into wards.
        # Only the labels (and group_noun) are fixed — membership is randomised per
        # puzzle by _random_groups (>=2 groups, >=2 members each), so the listed
        # members below just seed the label pool. Surface only via group clues
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
        referents=(
            ("Race", "the {}"),                          # the Elf
            ("Class", "the {}"),                         # the Wizard
            ("Weapon", "the adventurer with the {}"),    # the adventurer with the Longbow
            ("School", "the {} mage"),                   # the Evocation mage
            ("Familiar", "the adventurer with the {} familiar"),  # …with the Owl familiar
        ),
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
        referents=(
            ("Room", "the suspect in the {}"),       # the suspect in the Library
            ("Weapon", "the suspect with the {}"),   # the suspect with the Candlestick
            ("Motive", "the suspect driven by {}"),  # the suspect driven by Greed
            ("Occupation", "the {}"),                # the Butler
            ("Alibi", "the suspect who was {}"),     # the suspect who was Reading
        ),
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
        referents=(
            ("Role", "the {}"),                          # the Captain
            ("Module", "the colonist in the {} module"), # the colonist in the Aurora module
            ("Homeworld", "the colonist from {}"),       # the colonist from Europa
            ("Specimen", "the colonist studying {}"),    # the colonist studying Algae
        ),
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
        referents=(
            ("Discipline", "the {} engineer"),       # the Civil engineer
            ("Project", "the engineer on the {}"),   # the engineer on the Bridge
            ("Material", "the engineer using {}"),   # the engineer using Steel
            ("Tool", "the engineer with the {}"),    # the engineer with the Wrench
        ),
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
        # A second ordered dial (mega and up, K>=4 only): which class period it meets —
        # an ordinal ("Period 1".."Period N"), so higher/next-to but no "2 more".
        extra_numerics=(NumericSpec("Period", unit_prefix="Period ", valued=False),),
        referents=(
            ("Subject", "the {} class"),               # the Biology class
            ("Room", "the class in the {}"),           # the class in the Annex
            ("Student", "the class with {}"),          # the class with Iris
            ("Club", "the member of the {} club"),     # the member of the Debate club
            ("Period", "the class in {}"),             # the class in Period 3
        ),
    ),
    ThemeSpec(
        key="fishing",
        name="The Fishing Derby",
        description=(
            "Anglers at the lake-country derby each landed a different fish from a "
            "different pond on a different lure. Work out who caught what, and where."
        ),
        entity_noun="catch",
        subject_name="Angler",
        subject_items=("Boone", "Cody", "Dale", "Esther", "Gus", "Mabel", "Royce", "Wade"),
        attributes=(
            ("Species", ("Bass", "Bluegill", "Carp", "Catfish", "Crappie", "Perch", "Pike", "Trout")),
            ("Pond", ("Birchpool", "Cedarmere", "Foxglen", "Grayreach", "Mossbank", "Pinehollow", "Stillwater", "Willowmere")),
            ("Lure", ("Buzzbait", "Crankbait", "Jig", "Popper", "Spinnerbait", "Spoon", "Swimbait", "Wobbler")),
            ("Bait", ("Corn", "Cricket", "Dough", "Leech", "Maggot", "Minnow", "Nightcrawler", "Shrimp")),
        ),
        numeric=NumericSpec("Weight", unit_suffix=" lb", min_start=2, start_max=12, steps=(1, 2)),
        referents=(
            ("Species", "the angler who landed the {}"),  # the angler who landed the Pike
            ("Pond", "the angler at {}"),                 # the angler at Stillwater
            ("Lure", "the angler using the {}"),          # the angler using the Popper
            ("Bait", "the angler fishing with {}"),       # the angler fishing with Minnow
        ),
        # Two two-level hierarchies: Species group into families, Ponds into
        # watersheds. As with the other themes, membership is randomised per puzzle
        # by _random_groups (>=2 groups, >=2 members each) — the listed members just
        # seed the label pool — and these only surface via group clues ("Cody's
        # catch is a Sunfish", "Cody and Dale fished the same watershed"). With both
        # present, cross-group clues unlock ("exactly two Sunfish came from the
        # North Watershed").
        group_defs=(
            (
                "Species",
                "family",
                (
                    ("Sunfish Family", ("Bass", "Bluegill", "Crappie", "Perch")),
                    ("Pike Family", ("Pike", "Trout")),
                    ("Catfish Family", ("Carp", "Catfish")),
                ),
            ),
            (
                "Pond",
                "watershed",
                (
                    ("North Watershed", ("Birchpool", "Cedarmere", "Foxglen")),
                    ("South Watershed", ("Grayreach", "Mossbank", "Pinehollow")),
                    ("East Watershed", ("Stillwater", "Willowmere")),
                ),
            ),
        ),
    ),
    ThemeSpec(
        key="chess",
        name="The Chess Club",
        description=(
            "Regulars at the chess club each swear by a different opening, a "
            "favourite tactic, and a prized set. Work out who plays what."
        ),
        entity_noun="player",
        subject_name="Player",
        subject_items=("Anatoly", "Boris", "Garry", "Judit", "Magnus", "Mikhail", "Nadia", "Vera"),
        attributes=(
            ("Opening", ("Benoni", "Caro-Kann", "French", "Italian", "London", "Pirc", "Sicilian", "Slav")),
            ("Tactic", ("Discovery", "Fork", "Gambit", "Pin", "Sacrifice", "Skewer", "Zugzwang", "Zwischenzug")),
            ("Set", ("Boxwood", "Ebony", "Glass", "Maple", "Marble", "Pewter", "Rosewood", "Walnut")),
            ("Checkmate", ("Anastasia's", "Arabian", "Back-rank", "Boden's", "Damiano's", "Hook", "Scholar's", "Smothered")),
        ),
        # Rating (Elo) is the ordered category — unlocks higher/lower, between,
        # next-to and exact-difference ("100 more") clues. Evenly-spaced values.
        numeric=NumericSpec("Rating", min_start=1200, start_max=2000, steps=(50, 100)),
        # A second ordered dial (rich tiers, K>=4 only): the tournament Placing —
        # an ordinal in placing words (1st = best = highest rank), so "higher
        # placing" reads as "finished better". No values, so no "2 more" clues.
        # When it appears alongside Rating, clue text names which scale each side
        # is on ("…'s rating" vs "…'s placing").
        extra_numerics=(NumericSpec("Placing", valued=False, ordinal=True),),
        referents=(
            ("Opening", "the {} player"),                       # the Sicilian player
            ("Tactic", "the player who loves the {}"),          # the player who loves the Fork
            ("Set", "the player with the {} set"),              # the player with the Ebony set
            ("Checkmate", "the player known for the {} mate"),  # ... the Smothered mate
            ("Rating", "the {}-rated player"),                  # the 1500-rated player
            ("Placing", "the player who placed {}"),            # the player who placed 2nd
        ),
        # FIXED hierarchy: the eight openings split by their first move into the
        # King's-Pawn camp (1.e4) and the Queen's-Pawn camp (1.d4) — a real,
        # textbook classification, so membership is declared (fixed=True) rather
        # than reshuffled. Restricted to whatever openings a puzzle samples; if a
        # draw lands entirely in one camp, no hierarchy that puzzle.
        group_defs=(
            (
                "Opening",
                "camp",
                (
                    ("King's-Pawn Camp", ("Caro-Kann", "French", "Italian", "Pirc", "Sicilian")),
                    ("Queen's-Pawn Camp", ("Benoni", "London", "Slav")),
                ),
                True,
            ),
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


def _random_groups(partition: tuple, items: list, rng: random.Random,
                   min_size: int = 2, min_groups: int = 2) -> tuple:
    """Randomly partition the sampled ``items`` into the *labels* drawn from
    ``partition`` (the theme's named guilds/wards), for per-puzzle variety.

    Every formed group gets at least ``min_size`` members, and we form at least
    ``min_groups`` groups when the item count allows. If there are too few items
    to do that (n < min_size * min_groups), no hierarchy is formed (``()``), so
    the category carries no groups and no group clues are generated. Randomised
    membership, but fully deterministic in ``rng``; groups come back in the
    theme's canonical label order so the display stays stable."""
    labels = [label for label, _members in partition]
    n = len(items)
    max_groups = min(len(labels), n // min_size)
    if max_groups < min_groups:
        return ()
    g = rng.randint(min_groups, max_groups)
    sizes = [min_size] * g
    for _ in range(n - g * min_size):  # scatter the leftovers across the groups
        sizes[rng.randrange(g)] += 1
    pool = list(items)
    rng.shuffle(pool)
    chosen = rng.sample(labels, g)
    out, pos = [], 0
    for label, size in zip(chosen, sizes):
        out.append((label, tuple(sorted(pool[pos:pos + size]))))
        pos += size
    out.sort(key=lambda lm: lm[0])  # alphabetical by group label (stable display)
    return tuple(out)


def _fixed_groups(partition: tuple, items: list, min_groups: int = 2) -> tuple:
    """Restrict a DECLARED partition to the per-puzzle sampled ``items``, keeping
    the real, factual membership (unlike _random_groups, which reshuffles for
    flavour). Each group keeps only the items present in this draw; empty groups
    drop out. Returns ``()`` if fewer than ``min_groups`` non-empty groups
    survive, so a puzzle that happened to sample within a single group simply
    carries no hierarchy (and no group clues) rather than a degenerate one."""
    iset = set(items)
    out = []
    for label, members in partition:
        present = tuple(sorted(m for m in members if m in iset))
        if present:
            out.append((label, present))
    if len(out) < min_groups:
        return ()
    out.sort(key=lambda lm: lm[0])  # alphabetical by group label (stable display)
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
            gd = gdefs[name]
            fixed = len(gd) > 3 and gd[3]
            grps = (_fixed_groups(gd[2], pool_items) if fixed
                    else _random_groups(gd[2], pool_items, rng))
            if grps:  # empty when too few items to form a real hierarchy
                kwargs["group_noun"] = gd[1]
                kwargs["groups"] = grps
        cats.append(Category(name, pool_items, **kwargs))

    for ns in numerics:
        if ns.valued:
            step = rng.choice(ns.steps)
            start = rng.randint(ns.min_start, ns.start_max)
            values = [start + i * step for i in range(items)]  # evenly spaced = rank order
            labels = [ns.label(v) for v in values]
        elif ns.ordinal:  # placing words; rank order puts 1st last (= highest rank),
            values = None  # so the engine's "higher" reads as "placed better"
            labels = [_ordinal(items - i) for i in range(items)]
        else:  # plain ordinal: 1..N in rank order, no values (no difference clues)
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

    The primary ordered category appears above `normal` at its ``prob``. A second
    ordered dial is gated: the rich tiers (mega/giga/tera), K >= 4, and its own
    ``prob`` roll — so it stays an occasional flavour, never the default.
    """
    avail = spec.numerics
    if not avail or difficulty not in _NONTRIVIAL:
        return 0
    n = 1 if rng.random() < avail[0].prob else 0
    if (
        n == 1
        and len(avail) >= 2
        and difficulty in _RICH
        and clamp_categories(categories) >= 4
        and rng.random() < avail[1].prob
    ):
        n = 2
    return n


GROUP_PROB = 0.7  # chance an eligible (above-normal) puzzle rolls in its hierarchy


def _roll_use_groups(spec: ThemeSpec, difficulty: str, rng: random.Random) -> bool:
    """Whether to include the theme's group hierarchy (consumes ``rng`` only when
    the theme actually has one, so other themes' sequences are unaffected)."""
    if not spec.group_defs or difficulty not in _NONTRIVIAL:
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
    # deterministic puzzle). The primary numeric appears on hard and up; a second
    # ordered dial is gated to the rich tiers (mega+) with enough categories to spare.
    rng = random.Random(seed)
    n_numeric = _roll_n_numeric(spec, difficulty, categories, rng)
    use_groups = _roll_use_groups(spec, difficulty, rng)  # only consumes rng if theme has a group_def

    theme_obj, puzzle, report = generate_rated(
        lambda r: build_theme(spec, r, items, categories, n_numeric, use_groups), rng, difficulty
    )
    return theme_obj, puzzle, report, seed


def build_custom_puzzle(seed: int | None, difficulty: str, theme_doc: dict):
    """Generate a puzzle from a user-supplied *concrete* theme document — the
    single-file dict format that ``logicgrid.themes`` round-trips (see README
    "Single-file representation").

    Unlike registry themes there is no attribute sampling and no numeric/group
    rolls: the document IS the theme, categories and items fixed, so the same
    (document, difficulty, seed) always rebuilds the identical puzzle — the
    determinism contract the hint endpoint relies on. Returns
    ``(theme, puzzle, report, seed)`` like ``build_puzzle``.

    Raises ``ValueError`` with a human-readable message on a malformed,
    inconsistent, or out-of-bounds document.
    """
    from .themes import theme_from_dict

    if difficulty not in DIFFICULTIES:
        raise ValueError(f"unknown difficulty: {difficulty!r}")
    if not isinstance(theme_doc, dict):
        raise ValueError("theme_doc must be a JSON object (the exported theme file)")
    try:
        theme_obj = theme_from_dict(theme_doc)  # validates shape + consistency
    except ValueError:
        raise
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"malformed theme document: {exc}") from exc
    if not MIN_CUSTOM_ITEMS <= theme_obj.n <= MAX_CUSTOM_ITEMS:
        raise ValueError(
            f"custom themes need {MIN_CUSTOM_ITEMS}-{MAX_CUSTOM_ITEMS} items per "
            f"category, got {theme_obj.n}"
        )
    if not MIN_CUSTOM_CATEGORIES <= theme_obj.k <= MAX_CUSTOM_CATEGORIES:
        raise ValueError(
            f"custom themes need {MIN_CUSTOM_CATEGORIES}-{MAX_CUSTOM_CATEGORIES} "
            f"categories, got {theme_obj.k}"
        )
    if seed is None:
        seed = random.randrange(_MAX_SEED)
    rng = random.Random(seed)
    theme_obj, puzzle, report = generate_rated(lambda r: theme_obj, rng, difficulty)
    return theme_obj, puzzle, report, seed


def build_hint(
    seed: int,
    difficulty: str,
    items: int,
    categories: int,
    known: dict | None,
    theme: str = DEFAULT_THEME,
    theme_doc: dict | None = None,
) -> dict:
    """Next single explained deduction for the puzzle the inputs identify.

    Regenerates the exact puzzle and asks the hint engine for the first step the
    player (``known`` board) hasn't already made. ``known`` maps ``"i-j"`` to an
    n×n matrix of 0 blank / 1 link / 2 no-link, matching a hint's ``value``.
    With ``theme_doc`` (a custom theme document) the puzzle regenerates from the
    document instead of a registry key — the client re-sends the same file it
    generated with, and seed-determinism does the rest.
    """
    if theme_doc is not None:
        theme_obj, puzzle, _report, _seed = build_custom_puzzle(seed, difficulty, theme_doc)
    else:
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
    theme_doc: dict | None = None,
) -> dict:
    """Generate a puzzle and return a JSON-serialisable description.

    A concrete ``seed`` (and the ``theme`` key) are echoed back so any puzzle can
    be reproduced from the response alone. Whether the ordered numeric category is
    included is rolled once up front (only for medium/hard themes that have one).
    With ``theme_doc`` the puzzle is built from that custom theme document
    instead (see build_custom_puzzle) and ``theme`` echoes ``"custom"`` — the
    client keeps the document and re-sends it for hints.
    """
    if theme_doc is not None:
        theme_obj, puzzle, report, seed = build_custom_puzzle(seed, difficulty, theme_doc)
        theme = CUSTOM_THEME_KEY
    else:
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
            # proof-by-contradiction volume: single (tier 5) + nested (tier 6)
            # what-ifs (tier 4 is advanced forward logic, not a what-if), plus how
            # long the longest refutation ran — the band's mega/giga/tera signal.
            "whatif": report["steps"][5] + report["steps"][6],
            "whatif_max_proof": max(report.get("whatif_sizes") or [0]),
            # supplemental fine-grained signals (they do not decide the band)
            "search_nodes": report.get("nodes"),
            "clue_load": round(report.get("clue_cost", {}).get("mean", 0.0), 2),
            "difficulty_index": round(difficulty_index(report), 2),
        },
        "categories": [_category_payload(c) for c in theme_obj.categories],
        "clues": [clue.text(theme_obj) for clue in puzzle.clues],
        "solution": _solution_rows(theme_obj, puzzle.solution),
    }
