"""Big puzzles: offline generation of grids beyond the live API's size caps,
re-themable across every compatible registry theme.

The live generator clamps shapes (``n!^(k-1)`` uniqueness search) because it
runs inside a serverless request. Here generation happens offline (the
big-puzzles workflow / scripts/generate_big.py), so a 4-category × 6-item
grid is just a slower build, not a timeout.

Re-theming leans on the engine's clean split: a puzzle's logic is the
solution grid ``X`` plus abstract ``Clue`` objects holding *(category, item)
indices*; English appears only at ``clue.text(theme)``. Rendering the same
logical puzzle under another theme of the same shape is therefore a pure,
deterministic re-render, with two kinds of donor data to translate:

- Numeric-difference clues (``Diff``/``AtLeastApart``/``AbsApart``) bake the
  donor's value scale. Ordered categories are always evenly spaced, so a
  delta is a rank gap times the step; clones get theme B's step and values —
  logically identical, worded in B's units.
- Group clues (and the ``GroupLink``/``GroupSubset`` statement leaves inside
  conditionals) bake partition *labels* and *nouns*. Membership is item
  indices, so the target theme is dressed with the SAME index partitions —
  wearing its own vocabulary — and every label/noun is looked up fresh.
  Fixed (factual) hierarchies are never imposed on: only themes whose
  groups are declared flavor (random membership) can host a grouped puzzle.

Every bundle ships, per compatible theme: the payload the player UI needs
(categories, clues, solution) plus the full ordered hint path from
``hint.trace`` — the page works from static JSON with zero backend.
"""

from __future__ import annotations

import copy
import random

from .clues import (
    AbsApart,
    Adjacent,
    AtLeastApart,
    Between,
    Diff,
    DiffGroup,
    Greater,
    GroupCount,
    GroupGroupCompare,
    GroupGroupCount,
    GroupLink,
    GroupOrder,
    GroupSubset,
    InGroup,
    MultiCompare,
    Negative,
    NextTo,
    NotInGroup,
    OrderAgree,
    Positive,
    RanksApart,
    SameGroup,
    SetCount,
)
from .deduce import grade
from .generate import generate_rated
from .hint import _whatif_chain, trace
from .solver import count_solutions
from .model import Category, Theme
from .webapi import (
    _MAX_SEED,
    NESTED_MIN_ITEMS,
    THEME_SPECS,
    THEMES,
    _category_payload,
    _ordinal,
    _solution_rows,
    build_theme,
)

# Donor themes big puzzles are generated under. Groupless bundles use dnd —
# a valued primary numeric and the deepest attribute pool (5), no hierarchy
# rolls to consume randomness. Grouped bundles use kings_guild: two flavor
# hierarchies plus a nested (ward -> side of town) vocabulary for grids of
# NESTED_MIN_ITEMS and up.
DONOR = "dnd"
GROUP_DONOR = "kings_guild"
# Double-sequential bundles need a spec with two ordered categories; school
# (Grade + Period) donates, chess (Rating + Placing) is the re-theme partner.
SEQ2_DONOR = "school"

_VALUE_CLUES = (Diff, AtLeastApart, AbsApart)

# The clue families whose logic runs through an ordered (sequential) category
# — the "sequential clues" count surfaced as a catalog tag.
_ORDERED_CLUES = (
    Greater, Diff, Between, Adjacent, NextTo, AtLeastApart, AbsApart,
    MultiCompare, GroupOrder, OrderAgree, RanksApart,
)

_BANDS = ("normal", "hard", "mega", "giga", "tera")


# --- Compatibility ----------------------------------------------------------

def _flavor_group_defs(spec) -> list:
    """The spec's imposable (non-fixed) flat hierarchies. Factual partitions
    (fixed=True) state real-world membership and can't be reshuffled to
    mirror another puzzle's blocks."""
    return [gd for gd in spec.group_defs if not (len(gd) > 3 and gd[3])]


def shape_supported(spec, categories: int, items: int, needs_ordered,
                    n_grouped: int = 0, n_nested: int = 0) -> bool:
    """Can this theme spec dress a puzzle of the given shape?

    Needs: enough attribute pools for the non-subject, non-ordered slots,
    every pool deep enough for ``items``; a *valued* primary numeric when the
    puzzle carries an ordered category (evenly spaced values, so difference
    clues remap exactly) — ``needs_ordered`` counts the sequential dials, so
    2 additionally requires a second declared numeric (rank-only is fine
    there: extra dials never carry difference clues); and enough imposable
    hierarchy vocabularies — ``n_nested`` categories with a nested vocabulary
    plus ``n_grouped`` more with at least a flat flavor one."""
    n_ordered = int(needs_ordered)
    n_attr = categories - 1 - n_ordered
    if n_attr < 0 or len(spec.attributes) < n_attr:
        return False
    pools = [spec.subject_items] + [pool for _name, pool in spec.attributes]
    if any(len(pool) < items for pool in pools):
        return False
    if n_ordered and not (spec.numerics and spec.numerics[0].valued):
        return False
    if n_ordered > len(spec.numerics):
        return False
    if n_nested > len(spec.nested_group_defs):
        return False
    flat_only = {gd[0] for gd in _flavor_group_defs(spec)}
    nested_names = {nd[0] for nd in spec.nested_group_defs}
    if n_grouped > len(flat_only | nested_names) - n_nested:
        return False
    return True


def puzzle_group_shape(theme: Theme) -> tuple[int, int]:
    """(flat-grouped, nested) category counts of a built theme."""
    n_grouped = sum(
        1 for c in theme.categories if c.has_groups and not c.has_supergroups
    )
    n_nested = sum(1 for c in theme.categories if c.has_supergroups)
    return n_grouped, n_nested


def compatible_themes(categories: int, items: int, needs_ordered,
                      n_grouped: int = 0, n_nested: int = 0) -> list[str]:
    return [
        spec.key for spec in THEME_SPECS
        if shape_supported(spec, categories, items, needs_ordered,
                           n_grouped, n_nested)
    ]


# --- Donor generation --------------------------------------------------------

def pick_donor(groups: bool, n_ordered: int) -> str:
    if n_ordered >= 2:
        if groups:  # no registry theme carries flavor groups AND two dials
            raise ValueError("grouped double-sequential has no donor theme")
        return SEQ2_DONOR
    return GROUP_DONOR if groups else DONOR


def generate_big(seed: int, difficulty: str, categories: int, items: int,
                 ordered=True, groups: bool = False,
                 donor: str | None = None, collect=None):
    """Generate the canonical (donor-themed) big puzzle. Returns
    ``(theme, puzzle, report)`` — deterministic in all arguments. ``ordered``
    counts the sequential dials (bool means one). With ``collect``, every
    logic-solvable candidate the walk grades is passed to it (see
    ``generate_rated``)."""
    n_ordered = int(ordered)
    donor = donor or pick_donor(groups, n_ordered)
    spec = THEMES[donor]
    if not shape_supported(spec, categories, items, n_ordered):
        raise ValueError(f"donor {donor!r} can't dress {categories}x{items}")
    rng = random.Random(seed)
    return generate_rated(
        lambda r: build_theme(spec, r, items, categories, n_ordered,
                              use_groups=groups, clamp=False),
        rng, difficulty, collect=collect,
    )


def generate_big_all(seed: int, difficulty: str, categories: int, items: int,
                     ordered=True, groups: bool = False,
                     donor: str | None = None) -> list:
    """Every logic-solvable candidate one walk produces, as
    ``(theme, puzzle, report)`` tuples — the target-band winner AND the
    off-band byproducts. At big shapes each attempt costs minutes-to-hours,
    so a mega that rolled while hunting a tera is a shippable puzzle, not
    waste; callers bundle each under its *measured* band."""
    collected: list = []
    generate_big(seed, difficulty, categories, items, ordered, groups, donor,
                 collect=lambda t, p, r: collected.append((t, p, r)))
    return collected


# --- Dressing a target theme with the donor's structure ----------------------

def _index_parts(catobj, blocks) -> list[tuple]:
    return [
        tuple(sorted(catobj.items.index(m) for m in members))
        for _label, members in blocks
    ]


def _blocks_from_parts(labels, parts, items) -> tuple:
    blocks = [
        (label, tuple(sorted(items[i] for i in part)))
        for label, part in zip(labels, parts)
    ]
    blocks.sort(key=lambda lm: lm[0])
    return tuple(blocks)


def dress(spec_key: str, seed: int, donor_theme: Theme):
    """A concrete theme for re-rendering: the donor's exact shape — category
    for category — wearing this spec's labels, values, and hierarchy
    vocabulary. Grouped donor categories are mirrored with the SAME item-index
    partitions (both levels for a nest), so every group clue's index blocks
    stay meaningful; the labels come from the target's own vocabulary.
    Deterministic in ``seed``."""
    spec = THEMES[spec_key]
    rng = random.Random(seed)
    n = donor_theme.n
    refs = dict(spec.referents)
    ndefs = {nd[0]: nd for nd in spec.nested_group_defs}
    gdefs = {gd[0]: gd for gd in _flavor_group_defs(spec)}
    pools = dict(spec.attributes)
    donor_cats = donor_theme.categories[1:]

    # Assign this spec's attributes to the donor's category slots: nested
    # slots claim nested-capable attributes first, flat-grouped slots any
    # remaining hierarchy vocabulary, plain slots prefer plain attributes.
    assigned: dict[int, str] = {}
    avail = [name for name, _ in spec.attributes]

    def claim(idx: int, wanted) -> None:
        for nm in list(avail):
            if wanted(nm):
                avail.remove(nm)
                assigned[idx] = nm
                return
        raise ValueError(f"{spec_key} lacks vocabulary for donor slot {idx}")

    for i, dc in enumerate(donor_cats):
        if not dc.ordered and dc.has_supergroups:
            claim(i, lambda nm: nm in ndefs)
    for i, dc in enumerate(donor_cats):
        if not dc.ordered and i not in assigned and dc.has_groups:
            claim(i, lambda nm: nm in gdefs or nm in ndefs)
    for i, dc in enumerate(donor_cats):
        if not dc.ordered and i not in assigned:
            plain = [nm for nm in avail if nm not in gdefs and nm not in ndefs]
            claim(i, (lambda nm, p=set(plain): nm in p) if plain else (lambda nm: True))

    cats: list[Category] = [
        Category(spec.subject_name, sorted(rng.sample(spec.subject_items, n)))
    ]
    dial = 0  # which of the spec's numerics dresses the next ordered slot
    for i, dc in enumerate(donor_cats):
        if dc.ordered:
            ns = spec.numerics[dial]
            dial += 1
            # mirror build_theme's three numeric flavors exactly
            if ns.valued:
                step = rng.choice(ns.steps)
                start = rng.randint(ns.min_start, ns.start_max)
                values = [start + j * step for j in range(n)]
                labels = [ns.label(v) for v in values]
            elif ns.ordinal:  # placing words: rank order puts 1st last
                values = None
                labels = [_ordinal(n - j) for j in range(n)]
            else:  # plain ordinal 1..N, no values
                values = None
                labels = [ns.label(j + 1) for j in range(n)]
            cats.append(Category(
                ns.name, labels, ordered=True,
                values=values, unit=ns.unit_prefix, unit_suffix=ns.unit_suffix,
                referent=refs.get(ns.name, ""),
            ))
            continue

        name = assigned[i]
        items = sorted(rng.sample(pools[name], n))
        kwargs = {"referent": refs.get(name, "")}
        if dc.has_supergroups:
            nd = ndefs[name]
            parts = _index_parts(dc, dc.groups)
            kwargs["group_noun"] = nd[1]
            kwargs["groups"] = _blocks_from_parts(
                rng.sample(list(nd[2]), len(parts)), parts, items
            )
            sparts = _index_parts(dc, dc.supergroups)
            kwargs["supergroup_noun"] = nd[3]
            kwargs["supergroups"] = _blocks_from_parts(
                rng.sample(list(nd[4]), len(sparts)), sparts, items
            )
        elif dc.has_groups:
            parts = _index_parts(dc, dc.groups)
            if name in gdefs:
                noun, label_pool = gdefs[name][1], [lab for lab, _ in gdefs[name][2]]
            else:  # a nested-capable attribute hosting a flat hierarchy
                noun, label_pool = ndefs[name][1], list(ndefs[name][2])
            kwargs["group_noun"] = noun
            kwargs["groups"] = _blocks_from_parts(
                rng.sample(label_pool, len(parts)), parts, items
            )
        cats.append(Category(name, items, **kwargs))

    theme = Theme(
        name=spec.name, description=spec.description,
        categories=cats, entity_noun=spec.entity_noun,
    )
    theme.validate()
    return theme


# --- Re-rendering clues under the dressed theme -------------------------------

def _part_label(theme: Theme, cat: int, members) -> str:
    """The target theme's label for the index block ``members`` of category
    ``cat`` — at whichever hierarchy level it lives."""
    catobj = theme.categories[cat]
    want = tuple(sorted(members))
    for blocks in (catobj.groups, catobj.supergroups):
        for label, mem in blocks:
            if tuple(sorted(catobj.items.index(m) for m in mem)) == want:
                return label
    raise KeyError(f"no block {want} in category {cat} of {theme.name}")


def _part_noun(theme: Theme, cat: int, partition) -> str:
    """group_noun vs supergroup_noun, decided by which level the partition is."""
    catobj = theme.categories[cat]
    want = {tuple(sorted(p)) for p in partition}
    fine = {
        tuple(sorted(catobj.items.index(m) for m in mem))
        for _l, mem in catobj.groups
    }
    return catobj.group_noun if want <= fine else catobj.supergroup_noun


def _patch_statements(node, theme: Theme, seen: set) -> None:
    """Walk a clue/statement object graph, re-labelling embedded group leaves."""
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, GroupLink):
        node.label = _part_label(theme, node.cat, node.members)
    elif isinstance(node, GroupSubset):
        node.label_a = _part_label(theme, node.cat_a, node.members_a)
        node.label_b = _part_label(theme, node.cat_b, node.members_b)
    values = (
        vars(node).values() if hasattr(node, "__dict__")
        else node if isinstance(node, (list, tuple)) else ()
    )
    for v in values:
        if hasattr(v, "__dict__") or isinstance(v, (list, tuple)):
            _patch_statements(v, theme, seen)


def retheme_clues(clues: list, target: Theme) -> list:
    """Deep clones of ``clues`` that render — and still hold — under
    ``target``. Indices carry over untouched; donor-baked value scales,
    group labels, and group nouns are translated."""
    out = []
    for clue in clues:
        c = copy.deepcopy(clue)
        if isinstance(c, _VALUE_CLUES):
            # Translate the delta through RANK space: registry values are
            # evenly spaced, so "gap >= delta" is really "rank gap >=
            # ceil(delta/step)" (Diff's exact delta is always a whole number
            # of ranks; the inequality clues draw theirs anywhere inside the
            # true gap). The clone takes the same rank bound times the
            # target's step — identical logic, clean numbers in B's units.
            tvals = target.categories[c.cat].values
            dvals = c._values
            dstep, tstep = dvals[1] - dvals[0], tvals[1] - tvals[0]
            if isinstance(c, Diff):
                if c.delta % dstep:
                    raise ValueError("exact-difference delta is not a whole rank gap")
                ranks = c.delta // dstep
            elif isinstance(c, AbsApart) and not c.at_least:
                ranks = c.delta // dstep          # "at most": floor keeps the bound
            else:
                ranks = -(-c.delta // dstep)      # "at least": ceil keeps the bound
            c.delta = ranks * tstep
            c._values = tvals
        elif isinstance(c, (InGroup, NotInGroup)):
            c.label = _part_label(target, c.cat, c.members)
        elif isinstance(c, GroupCount):
            c.label = _part_label(target, c.cat, c.members)
        elif isinstance(c, (SameGroup, DiffGroup)):
            c.group_noun = _part_noun(target, c.cat, c.partition)
        elif isinstance(c, GroupOrder):
            c.higher_label = _part_label(target, c.gcat, c.higher)
            c.lower_label = _part_label(target, c.gcat, c.lower)
        elif isinstance(c, GroupGroupCount):
            c.labelA = _part_label(target, c.cat1, c.membersA)
            c.labelB = _part_label(target, c.cat2, c.membersB)
        elif isinstance(c, GroupGroupCompare):
            c.labelA = _part_label(target, c.cat1, c.membersA)
            c.labelB = _part_label(target, c.cat1, c.membersB)
            c.labelC = _part_label(target, c.cat2, c.membersC)
        elif isinstance(c, SetCount):
            c.subjects = tuple(
                sub if sub[0] == "entity"
                else ("group", sub[1], sub[2], _part_label(target, sub[1], sub[2]))
                for sub in c.subjects
            )
            tcat = c.target_cells[0][0]
            if c.target_is_group:
                c.target_label = _part_label(
                    target, tcat, [i for _c, i in c.target_cells]
                )
            else:
                names = [target.categories[cc].items[i] for cc, i in c.target_cells]
                c.target_label = " or ".join(names)
        _patch_statements(c, target, set())
        out.append(c)
    return out


# --- Bundles ------------------------------------------------------------------

def _hint_steps(theme: Theme, clues: list) -> list[dict]:
    """The full solve path, JSON-safe. The server builds a what-if step's
    contradiction chain lazily from the step's board context; a static
    bundle has no later chance, so the chain is baked in here — otherwise a
    what-if hint states its conclusion with no refutation line to follow."""
    steps = []
    for step in trace(theme, clues):
        ctx = step.pop("_ctx", None)
        if ctx is not None:
            before, i, a, j, b, v = ctx
            step["chain"] = _whatif_chain(theme, clues, before, i, a, j, b, v)
        steps.append(step)
    return steps


def _theme_payload(theme: Theme, clues: list, X) -> dict:
    return {
        "name": theme.name,
        "description": theme.description,
        "entity_noun": theme.entity_noun,
        "categories": [_category_payload(c) for c in theme.categories],
        "clues": [c.text(theme) for c in clues],
        "solution": _solution_rows(theme, X),
        "hints": _hint_steps(theme, clues),
    }


def bundle_candidate(puzzle_id: str, seed: int, requested: str,
                     theme_obj, puzzle, report,
                     donor: str | None = None,
                     family: str | None = None,
                     derived_from: str | None = None) -> dict:
    """The complete static bundle for one generated candidate: shape +
    rating, plus a ready-to-play rendering (categories, clues, solution,
    hint path) under every compatible theme. Every re-render is verified
    against the solution before it ships.

    ``derived_from`` marks an adjusted (downgraded) variant; ``family`` ties
    every variant sharing one solution to its root puzzle id, so the catalog
    can cross-link them."""
    categories, items = theme_obj.k, theme_obj.n
    donor = donor or DONOR
    X = puzzle.solution
    n_ordered = sum(1 for c in theme_obj.categories if c.ordered)
    needs_ordered = n_ordered > 0
    n_grouped, n_nested = puzzle_group_shape(theme_obj)

    themes: dict[str, dict] = {}
    for key in compatible_themes(categories, items, n_ordered,
                                 n_grouped, n_nested):
        if key == donor:
            dressed, clues = theme_obj, puzzle.clues
        else:
            try:
                dressed = dress(key, seed, theme_obj)
                clues = retheme_clues(puzzle.clues, dressed)
            except (ValueError, KeyError):
                continue  # this spec can't host the structure — skip, don't ship
        if not all(c.holds(X) for c in clues):  # a re-render must stay true
            continue
        themes[key] = _theme_payload(dressed, clues, X)

    return {
        "id": puzzle_id,
        "hints_v": 2,  # 2 = what-if steps carry their contradiction chains
        "seed": seed,
        "categories": categories,
        "items": items,
        "requested": requested,
        "difficulty": report["band"],
        "has_ordered": needs_ordered,
        "grouped": n_grouped + n_nested > 0,
        "nested": n_nested > 0,
        # catalog tags: counts by CATEGORY (what the player sees on the board)
        # plus the finer-grained data (blocks, ordered-clue volume) for later
        "group_categories": sum(1 for c in theme_obj.categories if c.has_groups),
        "sequential_categories": sum(1 for c in theme_obj.categories if c.ordered),
        "group_blocks": sum(
            len(c.groups) + len(c.supergroups) for c in theme_obj.categories
        ),
        "sequential_clues": sum(
            1 for c in puzzle.clues if isinstance(c, _ORDERED_CLUES)
        ),
        "cross_dial_clues": sum(
            1 for c in puzzle.clues if isinstance(c, OrderAgree)
        ),
        "family": family or puzzle_id,
        "derived_from": derived_from,
        "adjusted": bool(derived_from),
        "rating": {
            "ceiling": report["ceiling"],
            "steps": report["steps"],
            "total_steps": report["total_steps"],
        },
        "default_theme": donor,
        "themes": themes,
    }


def downgrade(theme_obj: Theme, puzzle, target: str, max_additions: int = 24):
    """A same-solution variant of ``puzzle`` measured exactly at ``target``,
    or None when the exact band can't be hit.

    Works backwards from the solve path: a puzzle sits above ``target``
    because somewhere in its trace the solver must open a what-if. Each round
    finds the deepest such step and hands the player that step's fact
    directly (a Positive/Negative on the very cell the hypothetical would
    have derived), which defuses the contradiction — adding a true clue can
    only ever make a puzzle easier, so the walk down is monotone. A candidate
    addition that overshoots below ``target`` is discarded and the next deep
    cell is tried instead. Once the band lands, a band-pinned cleanup drops
    every clue that became redundant (uniqueness and the exact band are both
    re-verified per drop), so the variant carries no dead weight.

    Returns ``(puzzle_variant, report)``.
    """
    if target not in _BANDS:
        raise ValueError(f"unknown band: {target!r}")
    want = _BANDS.index(target)

    def idx(rep):
        return _BANDS.index(rep["band"]) if rep["band"] in _BANDS else len(_BANDS)

    X = puzzle.solution
    n = theme_obj.n
    clues = list(puzzle.clues)
    report = grade(theme_obj, clues)
    tried: set = set()
    for _ in range(max_additions):
        if idx(report) <= want:
            break
        steps = trace(theme_obj, clues)
        deep = [s for s in steps if s.get("tier", 0) >= 5]
        pick = next(
            (s for s in deep if (s["key"], s["a"], s["b"]) not in tried), None
        )
        if pick is None:
            break
        tried.add((pick["key"], pick["a"], pick["b"]))
        i, j = (int(x) for x in pick["key"].split("-"))
        a, b = pick["a"], pick["b"]
        # Candidate interventions, strongest first: the traced fact itself,
        # then — because pinning a whole cell can collapse the cascade and
        # overshoot the target — strictly weaker single eliminations along
        # the same line (each rules out ONE alternative the what-if had to
        # test, easing the puzzle by a smaller step).
        cands = [Positive((i, a), (j, b)) if pick["value"] == 1
                 else Negative((i, a), (j, b))]
        if pick["value"] == 1:
            cands.extend(Negative((i, a), (j, bb)) for bb in range(n) if bb != b)
        for clue in cands:
            assert clue.holds(X)  # every candidate is a fact of the solution
            rep2 = grade(theme_obj, clues + [clue])
            if idx(rep2) < want:
                continue  # this one overshoots — try a weaker intervention
            clues, report = clues + [clue], rep2
            break
    if report["band"] != target:
        return None

    for c in list(clues):  # band-pinned cleanup (see docstring)
        if len(clues) <= 2:
            break
        trial = [x for x in clues if x is not c]
        if count_solutions(theme_obj, trial, cap=2, max_nodes=20000) != 1:
            continue
        rep2 = grade(theme_obj, trial)
        if rep2["band"] != target:
            continue
        clues, report = trial, rep2

    variant = copy.copy(puzzle)
    variant.clues = clues
    return variant, report


def build_big_bundle(puzzle_id: str, seed: int, difficulty: str,
                     categories: int, items: int, ordered=True,
                     groups: bool = False, donor: str | None = None) -> dict:
    """One walk, one bundle: the target-band winner (or closest fallback)
    only. The batch script prefers ``generate_big_all`` + ``bundle_candidate``
    so a walk's off-band byproducts ship too."""
    donor = donor or pick_donor(groups, int(ordered))
    theme_obj, puzzle, report = generate_big(
        seed, difficulty, categories, items, ordered, groups, donor
    )
    return bundle_candidate(puzzle_id, seed, difficulty, theme_obj, puzzle,
                            report, donor)


def find_candidate(bundle: dict):
    """Replay a shipped bundle's walk and return its exact live
    ``(theme, puzzle, report)``. Generation is deterministic in the walk
    inputs, and byproducts are identified among the candidates by matching
    the donor rendering's solution rows."""
    donor = bundle["default_theme"]
    n_ordered = bundle.get(
        "sequential_categories", 1 if bundle.get("has_ordered", True) else 0
    )
    cands = generate_big_all(
        bundle["seed"], bundle["requested"], bundle["categories"],
        bundle["items"], ordered=n_ordered,
        groups=donor == GROUP_DONOR, donor=donor,
    )
    want = bundle["themes"][donor]["solution"]
    for theme_obj, puzzle, report in cands:
        if _solution_rows(theme_obj, puzzle.solution) == want:
            return theme_obj, puzzle, report
    raise ValueError(f"replaying {bundle['id']} did not reproduce its solution")


def derive_variants(bundle: dict, targets: list) -> list:
    """Downgraded variants of a shipped bundle: one replay, then one
    ``downgrade`` per target band. Returns ``(target, theme, variant,
    report)`` tuples for every band that was exactly reachable."""
    theme_obj, puzzle, _report = find_candidate(bundle)
    out = []
    for target in targets:
        got = downgrade(theme_obj, puzzle, target)
        if got is not None:
            out.append((target, theme_obj, got[0], got[1]))
    return out


def theme_capabilities() -> dict:
    """Per registry theme, what it can wear — the catalog's at-a-glance
    dressing-room card: nested vocabulary or not, how many hierarchy-capable
    categories (imposable flavor only; fixed factual partitions don't count),
    and how many sequential dials."""
    out = {}
    for spec in THEME_SPECS:
        groupable = {gd[0] for gd in _flavor_group_defs(spec)}
        groupable |= {nd[0] for nd in spec.nested_group_defs}
        out[spec.key] = {
            "name": spec.name,
            "nested": len(spec.nested_group_defs) > 0,
            "group_categories": len(groupable),
            "sequential_categories": len(spec.numerics),
        }
    return out


def random_seed() -> int:
    return random.randrange(_MAX_SEED)
