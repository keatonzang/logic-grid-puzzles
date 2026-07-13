# Logic Grid Puzzles — Technical Report

This document describes how the system works end to end: the data model, the
clue algebra, the generation pipeline, the two solvers (a backtracking
uniqueness counter and a human-style deductive grader), the hint engine, the
web/serverless layer, and the front end — along with the guarantees each layer
provides and the known limits of what is measured rather than proved.

The companion [README](../README.md) covers usage; this report covers
internals. Real class, function, and constant names from the code are used
throughout so the document doubles as a map of the source.

## 1. System overview

A logic grid puzzle is a set of K categories, each with N items, where every
entity (one row of the answer) takes exactly one item from each category — a
perfect one-to-one matching between every pair of categories. The player
recovers the matching from a list of clues. The system's core promise: every
shipped puzzle has **exactly one solution** and is **solvable by logic alone**.

Generation is *generate-and-grade*: sample a random solution, enumerate true
clues, screen and minimize them, then measure the difficulty with a reference
deductive solver, and ship a candidate only when its *measured* band matches
the request.

```
ThemeSpec / YAML theme
        │
        ▼
random_solution()            one random bijection between all categories
        │
        ▼
build_clue_pool()            enumerate clues TRUE under that solution, per tier
        │
        ▼
_semantic_screen()           reject tautologies, dedupe semantically, reject
        │                    intra-clue redundancy (128-solution sample)
        ▼
minimize()                   greedy drop while uniqueness holds (node-budgeted),
        │                    with a per-tier diversity reserve
        ▼
grade()                      human-style deductive solve → technique ceiling →
        │                    difficulty band; regenerate until band matches
        ▼
Puzzle ──► render (CLI) / build_payload (web JSON) / next_hint (web hints)
```

Two independent solvers keep each other honest:

- `logicgrid/solver.py` — a backtracking **counter** used only to verify
  uniqueness (it counts solutions and stops at 2).
- `logicgrid/deduce.py` — a **deductive solver** that uses only human-style
  techniques, cheapest first, and reports which techniques the solve forced.
  Its trace decides the difficulty band, and its ability to finish the puzzle
  is itself the logic-solvability guarantee.

### Source layout

| Path | Role |
|---|---|
| `generate.py` | CLI entry point (YAML themes, `normal` pool) |
| `logicgrid/model.py` | `Theme` / `Category` data model, validation, `Contradiction` |
| `logicgrid/clues.py` | Clue classes, the `Count` engine, the `Statement` algebra, cognitive cost model |
| `logicgrid/generate.py` | Pool building, semantic screen, minimization, generate-and-grade |
| `logicgrid/solver.py` | Backtracking solution counter (uniqueness) |
| `logicgrid/deduce.py` | Deductive solver, technique tiers, difficulty grading |
| `logicgrid/hint.py` | Explained single-step hint engine (replays the solver) |
| `logicgrid/census.py` | Shipped-clue diversity / calibration census |
| `logicgrid/themes.py` | YAML/JSON theme load + round-trip import/export |
| `logicgrid/render.py` | Console rendering (clues, grids, solution table) |
| `logicgrid/webapi.py` | Web theme registry (`ThemeSpec`), puzzle/payload/hint builders |
| `api/puzzle.py`, `api/hint.py` | Vercel serverless handlers |
| `public/` | Static front end; `logic.js` is the pure, DOM-free interaction core |

## 2. Data model (`logicgrid/model.py`)

A solution is a grid `X[entity][category] = item_index`. Each per-category
column is a permutation of `range(N)`. The grid is **anchored**: column 0 is
the identity (`X[i][0] == i`), so entity *i* *is* the i-th item of category 0
(the "subject" category), and only columns 1..K-1 are ever searched or
assigned. Because ordered categories list items ascending, an item's index is
also its rank; `Category.value(i)` returns `values[i]` when explicit numeric
values are attached, else the index.

`Category` carries the clue-text machinery besides the items: `ordered`,
`values`, `unit` / `unit_suffix` (amount formatting), `referent` (a template
like `"the person studying {}"` for naming an entity by this category's item),
`plural`, and the optional hierarchy fields `group_noun` + `groups` (a
partition of the items into labelled groups).

`Theme.validate()` enforces: at least 2 categories and 2 items, equal item
counts across categories, no duplicate items within a category, `values`
aligned with items, groups covering only real items with each item in at most
one group, and — so clue text is never ambiguous — **item labels globally
unique across the whole puzzle**.

`Contradiction` (the exception the deductive solver raises and the what-if
machinery catches) lives here rather than in the solver so the clue/statement
algebra can raise it without a circular import. It optionally carries a
`conflict` tuple `(ci, a, cj, b, existing, attempted)` that the hint engine
uses to narrate the clash.

## 3. The clue system (`logicgrid/clues.py`)

Every clue implements two methods and one attribute:

- `holds(X) -> bool` — is the clue true under a fully-assigned solution?
  (Used by the pool builder and the uniqueness counter.)
- `text(theme) -> str` — the English rendering.
- `involved: frozenset[int]` — which category columns the clue reads; the
  uniqueness solver uses this to check each clue as soon as its columns are
  assigned.

A class-level `removal_class` (0 positive, 1 comparison, 2 negative) biases
the minimizer to drop plain positives first. Clues that participate in
deductive propagation on *partial* boards either have a dedicated propagator
registered in `deduce._PROPAGATORS` or implement `propagate(board)` themselves
(the statement-carrying clues do).

### Direct and sequential clues

`Positive(a, b)` and `Negative(a, b)` assert a link / non-link between two
`(category, item)` terms. The sequential clues need an `ordered` category and
operate on ranks (with `values` for the numeric ones): `Greater`, `Diff`
(exact difference), `Between`, `Adjacent` (directional neighbour), `NextTo`
(undirected neighbour), `AtLeastApart` (directional minimum gap), `AbsApart`
(symmetric distance, `at least` or `at most` — the only clue that bounds two
items *close*), and `MultiCompare` (above/below all of several others). Every
stated delta — exact or ranged — sits on the category's value lattice (the set
of realizable pairwise gaps), so a $2-stepped dial never reads "at least $5
more than", a bound no pair of its values can sit exactly on. When a
theme carries two ordered categories, clue text restates the dimension
possessively ("Dasari's distance") so multiple dials stay unambiguous.

### The Count engine

Most cardinality clues are phrasings of a single primitive:

> `Count(pairs, lo, hi)` — "between `lo` and `hi` of these term pairs share an
> entity."

Its constructor canonicalizes the pairs and **rejects a duplicate atom
outright** (`ValueError: intra-clue redundancy`), which is how "A goes with X
or A goes with X" is structurally impossible. One generic propagator
(`deduce._prop_count`) serves every subclass: if the confirmed-true count
exceeds `hi` or the confirmed-plus-unknown count cannot reach `lo`, the board
contradicts; if the window pins the remaining unknowns, they are forced.

| Family | Window over its pairs |
|---|---|
| `Among(anchor, options, at_least=k)` | `[k, len(options)]` (inclusive "at least k of N") |
| `EitherOr(anchor, options)` | `[1, 1]` (exclusive) |
| `Neither(anchor, options)` | `[0, 0]` |
| `AtMost(anchor, options, k)` | `[0, k]` |
| `Exactly(anchor, options, k)` | `[k, k]` |
| `AllDifferent(terms)` | `[0, 0]` over all cross-category pairs of the terms |
| `ExactlyKLinks(links, k)` | `[k, k]` over free-form links (k=1, N=2 is the XOR) |

`GroupMatch` (two equal-size term groups covering the same entities in unknown
order) is the one counting-flavoured clue that is *not* a Count window; it
implements its own bijection-style `holds` and propagator.

### The Statement algebra and conditionals

Compound clues embed a small three-valued (Kleene) logic over link atoms.
A `Statement` implements:

- `value(X) -> bool` — truth under a full solution;
- `eval(board) -> {unknown, yes, no}` — state on a partial board;
- `constrain(board, target)` — force the statement toward yes/no, pushing
  consequences down to atoms and raising `Contradiction` when impossible.

The node types are `Link` (the atom), `Not`, `And`, `Or`, `Xor`, plus the
hierarchy atoms `GroupLink` (entity ∈ group) and `GroupSubset`. `And`/`Or` do
unit propagation (force the last undecided operand once the rest are settled);
`Xor` pins one side off the other by parity.

Two clue types carry statements: `Conditional(ante, cons, biconditional)`
propagates modus ponens forward and the contrapositive backward (both
directions for a biconditional), and `Compound(stmt)` asserts one statement
top-level. Because propagation is delegated to the statement tree, the two
sides of a conditional can be arbitrarily nested and the implication still
fires correctly on partial boards.

### Hierarchy and set-counting clues

A grouped category unlocks clues that compile down to facts on that ordinary
column — there is no extra grid: `InGroup`, `NotInGroup`, `SameGroup`,
`DiffGroup`, `GroupCount` (of the named entities, `==`/`>=`/`<=` k are in the
group), and the rare `GroupOrder` (every member of one group outranks every
member of another on an ordered category). Two partitions on one theme unlock
the cross-tabulation clues `GroupGroupCount` and `GroupGroupCompare`.
`SetCount` generalizes further: exactly/at-least/at-most K of a *union* of
subjects (entities and whole groups) are associated with a target, counted
over distinct entities.

### Cognitive cost model

`clue_cost(clue)` assigns each clue a human reading/holding weight (e.g.
`Positive` 1.0, `Between` 2.8, disjunctions 1.6 + 0.6 per option, cross-group
comparisons 3.4; statement trees are scored recursively by
`statement_cost`). These costs never drive the solver — they feed the
supplemental `difficulty_index`, break ties in the semantic screen (cheapest
reading wins a dedupe), and order the minimizer's diversity reserve.

## 4. Generation pipeline (`logicgrid/generate.py`)

### 4.1 Pool building

`build_clue_pool(theme, X, rng, **flags)` enumerates clues *true under the
sampled solution*, family by family, then shuffles and slices each family to a
cap (e.g. `max_negatives=80`, `max_comparisons=40`, `max_conditional=14`,
`max_set_count=14`). Which families are enabled comes from the tier's pool
preset:

| Preset | Tiers | Adds |
|---|---|---|
| `_NORMAL_POOL` | normal | is / is-not only |
| `_HARD_POOL` | hard | either-or, neither, all-different, groups, sequential |
| `_RICH_POOL` | mega | multi-match thresholds, exclusive pairings, group matches, atom⇒atom conditionals, group instances, set counts |
| `_EXTREME_POOL` | giga, tera | compound conditional sides (`conditional_compound_prob=0.28`), two-of-N pairings |

All positive links always enter the pool (they pin the solution, so the full
pool is guaranteed unique before minimization even starts — asserted with the
counting solver, `RuntimeError` otherwise).

### 4.2 Semantic screen

`_semantic_screen` evaluates every candidate against a shared sample of
`_SCREEN_SAMPLES = 128` random solutions and computes a 128-bit truth
**signature** (which sample solutions the clue holds on). One mechanism
replaces per-family triviality guards:

- **Tautology rejection** — signature all-ones (true on the whole sample:
  zero information) → dropped.
- **Intra-clue redundancy** — for `Compound`/`Conditional`, each boolean
  operand gets its own signature; if one operand's signature is a subset of a
  sibling's (operand i implies operand j on the sample), the connective is
  degenerate and the clue is dropped (`_has_subsumed_branch`).
- **Cross-family dedupe** — two candidates with identical signatures are
  semantically the same constraint in different clothes; only the lower
  `clue_cost` reading is kept.
- **Sparse-signature guard** — a signature with fewer than
  `_SCREEN_DEDUPE_MIN_BITS = 4` set bits is too selective for the sample to
  attest equivalence, so such clues are kept unconditionally.

Positives skip the screen (they must survive for the uniqueness invariant).
Informativeness is *sampled*, so an astronomically weak clue could in
principle slip through — anything the sample can see is gone.

### 4.3 Minimization and the diversity reserve

`minimize` greedily walks the clues in random order and drops each one whose
removal keeps the puzzle unique. Each trial re-check runs the counting solver
under `_MINIMIZE_NODE_BUDGET = 20_000` nodes; a check that cannot finish
keeps the clue, so the shipped set stays unique and solvable but may be
slightly non-minimal.

Pure greedy minimization structurally starves the intricate families (in
measurement, exclusive pairings survived ~4/30 puzzles and conditionals ~3/30
without countermeasures). The fix is a **diversity reserve**: after the
shuffle, the first `reserve` clues of each substantive clue type (cost ≥
`_RESERVE_MIN_COST = 1.5`, so plain positives/negatives never qualify) are
moved to the *end* of the removal order — considered for removal last, so they
survive best. At the rich tiers the reserved block is additionally sorted so
the cheapest reading is attacked first and the most intricate survives
(`complexity_last`). Per tier: normal reserves nothing, hard reserves 2 per
type, mega 1 (complexity-last), giga and tera 2 (complexity-last). Reserved
clues still carry real deductive weight, so the reserve doesn't soften the
measured band.

Every tier ships the minimized set as-is: no clue can be dropped without
losing uniqueness, so even entry-level boards carry no redundant clues.
(Earlier versions padded `normal` with a fraction of the dropped clues to
shorten deduction chains; that padding has been removed.)

### 4.4 Generate-and-grade

`generate_rated(make_theme, rng, target)` loops up to a per-tier attempt
budget (`_RATED_ATTEMPTS`: normal 8, hard 9, mega 16, giga 14, tera 14),
building and grading a fresh candidate each time:

- **Exact band match** → ship immediately — with one exception: a `hard`
  candidate whose trace touches tier 4 (an advanced forward move) is held as a
  *soft* result while the hunt continues for a tier-4-free board, because
  `hard` should feel like everyday clue logic (~40% of hard-band boards would
  otherwise force one advanced move). The soft candidate ships only if no
  purer one appears.
- **Tera recovery** — a `tera` request that grades `ambiguous` (stalls) at
  what-if depth 1 is re-graded allowing a nested what-if
  (`max_hyp_depth=2`) in early-exit mode under a wall-clock budget of
  `_TERA_RECOVERY_BUDGET_S = 3.0` seconds. If the deep solve finishes, the
  candidate is tera; if the budget blows (`SolveBudgetExceeded`), the
  candidate is skipped — load can make generation more conservative, never
  unsound.
- **Graceful degradation** — otherwise the closest band seen is kept as a
  fallback and returned when the budget runs out, so a request the grid is too
  small to reach (e.g. `tera` on 3×3) degrades to the hardest band actually
  achievable. The payload reports both `requested` and the measured band.

## 5. Uniqueness solver (`logicgrid/solver.py`)

`count_solutions(theme, clues, cap=2)` assigns one whole category column at a
time, trying full permutations of `range(N)` per column (column 0 is the fixed
anchor). Columns are ordered most-referenced-first (`involve_count` over each
clue's `involved` set) so pruning bites earliest, and each clue is checked at
the first step where all of its columns are assigned. The search stops as soon
as the count reaches `cap` — counting to 2 is exactly enough to distinguish
"unique" from "not unique", making the uniqueness guarantee exact rather than
sampled. An optional `max_nodes` cap saturates the count at `cap` (conserves
towards "not proven unique"), which is what lets `minimize` budget its
re-checks safely. `search_effort` exposes the node count (capped at 60,000 in
grading) as a purely informational statistic.

At the shipped sizes (≤ 5 items, ≤ 5 categories, `n!^(k-1)` column
assignments upper-bounds the tree) this solves in milliseconds.

## 6. Difficulty measurement (`logicgrid/deduce.py`)

Difficulty is *measured, not guessed*: a second solver solves the puzzle the
way a person would — cheapest technique first — and the trace of what it was
*forced* to use decides the band.

### 6.1 The board and the technique ladder

`Board` stores the pairwise ✓/✗ state (`unknown / yes / no`) for every
category pair; `Board.set` raises `Contradiction` on conflict. The solver
(`solve`) escalates through a fixed ladder, always restarting from the
cheapest tier after any progress:

| Tier | Name | Mechanism |
|---|---|---|
| 0 | givens | apply `Positive`/`Negative`/`Neither`/`AllDifferent` directly |
| 1 | line completion | a ✓ excludes its row+column; n−1 ✗s force the survivor; a dead line contradicts |
| 2 | transitivity | two links through a shared entity combine (the core cross-referencing move) |
| 3 | clue propagation | the everyday propagators: counting windows, either-or, conditionals, group narrowing, simple rank bounds |
| 4 | advanced logic | expert propagators (`SetCount`, `GroupCount`, `GroupOrder`, cross-group counts/compares, `Between`, `AbsApart`) plus grid set logic: cross-elimination, naked subsets (size 2–3), difference-chain components |
| 5 | what-if | assume a cell, propagate tiers 1–4 to fixpoint, eliminate on contradiction |
| 6 | nested what-if | a what-if whose inner reasoning itself needs a what-if |

Inside a what-if the full forward set (tiers 1–4) is available and every
propagator reports when its clue can no longer be satisfied — so a refutation
is found exactly when a sharp solver would find one.

### 6.2 What-if policy

At each stall, `_sweep_hypothetical` exhaustively scans every open cell and
both truth values, and applies the assumption whose refutation forced the
*fewest* cells (minimum-closure). This makes the measured what-if count a
deterministic, comparable policy — but a *policy*, not a theoretical minimum:
a cleverer assumption order might need fewer what-ifs, and a human's failed
scans cost nothing in the grade. An `first=True` early-exit mode takes the
first refutation found instead (~100× cheaper at depth 2); it is used only for
tera-recovery solvability checks and nested-hint cell picking, never for the
canonical depth-1 grade. The refutation lengths are collected as
`whatif_sizes` — the mega/giga separator.

The solver never uses "assume it and everything works out" (which would
exploit uniqueness as an oracle); only contradictions count. Propagation is
sound but not complete (bound checks, quota forcing, unit propagation — not
full arc-consistency), so where a smarter forward inference exists the solver
escalates to a what-if instead: measured difficulty can *overstate*, never
understate, and solvability is unaffected.

### 6.3 Banding

`band_of(report)` reads the trace's technique **ceiling** first, with the ease
of the contradiction work as the secondary separator inside the what-if
bracket (constants: `_MEGA_MAX_WHATIFS = 2`, `_MEGA_MAX_PROOF = 10`,
`_TERA_MIN_WHATIFS = 8`):

| Band | Rule |
|---|---|
| normal | ceiling ≤ 2 — lines and cross-referencing only |
| hard | ceiling 3–4 — forward clue logic, never a contradiction |
| mega | ceiling 5, ≤ 2 what-ifs, longest refutation ≤ 10 forced cells |
| giga | ceiling 5, everything between mega and tera |
| tera | ≥ 8 what-ifs, or any nested what-if (ceiling 6) |

The ladder is monotone in reasoning depth: no forward-only puzzle outranks a
contradiction puzzle, and a what-if is never labelled normal or hard. The cut
points were fitted against a 360-candidate census (3 themes × 3 grid shapes).

Supplemental, never band-deciding numbers: `difficulty_index` (a z-scored
blend of log tier-weighted step effort — weights `_TIER_EFFORT = {2:1, 3:4,
4:12, 5:40, 6:120}`; tiers 0–1 cost nothing — and mean clue reading cost),
`clue_load` (mean `clue_cost`), and `search_nodes` (the capped backtracking
statistic). They order puzzles within a band.

## 7. Hint engine (`logicgrid/hint.py`)

The hint engine produces the *next single explained deduction* from the
player's current marks. It does not re-implement any reasoning: it imports the
solver's actual sweep functions, runs one at a time (cheapest tier first),
diffs the board, and attaches prose. Tier labels surface in the UI as `Given,
Elimination, Cross-reference, Clue logic, Advanced logic, What-if, Nested
what-if` (`TIER_NAMES`, indexed by the deduce tier number) — so a hint is
always a sound, guess-free move at the lowest available tier.

`next_hint(theme, clues, known)` replays the full trace and returns the first
step whose cell the player hasn't already set correctly (`known` is the
client's board as `{"i-j": n×n matrix}` of 0 blank / 1 link / 2 no-link), or
`{"done": true}` when nothing new can be deduced.

For what-if hints the engine reconstructs a *readable proof*, not just the
conclusion: it re-runs the refutation with a journaling wrapper on
`Board.set` to capture every forced cell in order, explains each forced cell
against the state the solver actually saw (antecedents discovered by
*ablation* — clear a premise cell, re-run the propagator, see if the deduction
survives), then backward-slices from the contradiction so the narrated chain
contains only steps on an actual path to the clash.

## 8. Web and serverless layer

### 8.1 Theme registry and puzzle building (`logicgrid/webapi.py`)

The serverless functions can't read YAML files, so web themes live as frozen
`ThemeSpec` dataclasses in `THEME_SPECS`: a subject pool (category 0), several
attribute pools (each large enough for the biggest grid), an optional primary
`NumericSpec`, optional `extra_numerics`, `referents` (clue-text templates),
and `group_defs` (hierarchy partitions; membership randomized per puzzle
unless declared `fixed`). A `NumericSpec` has three modes: valued (evenly
spaced numbers → difference clues), plain ordinal (rank only), and placing
("1st, 2nd, …" where 1st is the top rank).

Nine themes ship: `cafe` (Price), `kings_guild` (Levy; two partitions —
guilds and wards), `dnd` (Gold), `mystery` (no numeric), `space` (Distance),
`engineer` (Budget), `school` (Grade + an ordinal Period as a second dial),
`fishing` (Weight; two partitions), and `chess` (Rating + a Placing ordinal;
fixed opening→camp hierarchy).

Sizing is clamped to 3–5 items and 3–5 categories, with items further capped
as categories grow (`_MAX_ITEMS_BY_K = {3: 5, 4: 4, 5: 4}`) so the
uniqueness search stays fast; the front end mirrors the same cap when
enabling menu options.

**Seed determinism contract.** `build_puzzle(seed, difficulty, items,
categories, theme)` is fully deterministic in its five inputs. A missing seed
is resolved to a concrete one up front and always echoed back in the payload.
The stochastic feature rolls — whether the numeric category joins (hard and
up), whether a second ordered dial joins (mega and up, ≥ 4 categories), and
whether a hierarchy is used (`GROUP_PROB = 0.7`, above normal) — consume the
RNG in a fixed order before generation, so `/api/hint` can regenerate the
byte-identical puzzle from the same parameters.

`build_payload` wraps the result as JSON: categories (with group metadata),
rendered clue text, the solution, the echoed `seed`, the `requested` tier and
the *measured* `difficulty` band, plus a `rating` object (ceiling, per-tier
steps, what-if count and longest proof, `search_nodes`, `clue_load`,
`difficulty_index`).

### 8.2 Serverless functions (`api/`)

Both handlers are dependency-free `BaseHTTPRequestHandler` classes bundled
with the `logicgrid` package by `vercel.json` (`@vercel/python`,
`includeFiles: logicgrid/**`; `public/` ships as static files).

- `GET /api/puzzle?theme=…&difficulty=…&items=…&categories=…&seed=…` →
  puzzle payload; `GET /api/puzzle?themes=1` → the theme catalogue for the
  picker. Malformed numbers and unknown keys return `400 {"error": …}`.
- `POST /api/hint` with `{seed, theme, difficulty, items, categories, known}`
  → regenerates the exact puzzle from the seed and returns the next explained
  deduction, or `{"done": true}`. The body is capped at 256 KiB.

### 8.3 Front end (`public/`)

No build step: `index.html` + `style.css` + two scripts. All interaction
*rules* live in `logic.js`, a pure, DOM-free module unit-tested by
`tests/logic.test.js`:

- `nextState` — mark cycling: a free cell cycles blank → ✗ → ✓ → blank; a
  cell whose row or column already holds a ✓ can only toggle blank ↔ manual ✗
  (never a second ✓ in a line).
- `derive` — display derivation: every blank cell sharing a line with a ✓
  displays a dim *auto*-✗ (bright ✗ means hand-placed). Auto-marks are never
  stored, so removing the ✓ auto-reverts them.
- `makeHistory` — a DOM-free undo/redo stack that coalesces rapid same-cell
  clicks and drops net-no-op gestures.

`app.js` keeps the player's intent (`manual`) separate from derived display
state, renders the pairwise grids as a single interlocked "staircase" on
desktop (category blocks with the notch at the lower right, group bands drawn
as tinted, labelled segments), and re-derives on every edit. **Check** flags
each derived mark against the solution and judges completion from the
transitive closure of placed links (a union-find over ✓ chains fills the live
solution table, so the player needn't hand-place every implied ✓). The hint
flow is two-click: the first click fetches and explains the next deduction
(with the contradiction chain in a collapsible section for what-if hints) and
glows the target cell; the second click fills it in. A print stylesheet
renders a clean black-on-white puzzle with all marks hidden and the answer key
on its own tear-off page.

When no seed is pinned, the client re-rolls up to 6 fresh seeds looking for a
measured band equal to the request, keeping the closest candidate as a
fallback — a second chance on top of the server's own attempt budget.

## 9. Guarantees and their limits

Hard, per-puzzle guarantees (verified for every shipped puzzle):

- **Uniqueness** — the backtracking counter proves exactly one solution
  exists (it counts to 2, so this is exact, not sampled).
- **Logic-solvability** — the deductive solver itself finishes the puzzle
  with the shipped clue list before shipping; a guess-free path always exists.
- **No intra-clue redundancy** — a clue never repeats an atom (structurally,
  via `Count`), and no branch of a compound implies a sibling (semantically,
  via the screen). Cross-clue redundancy exists only where intended: the
  normal band's deliberate padding.
- **No zero-information clues** — candidates true on the whole 128-solution
  sample never ship.

Everything else is measurement, and measurement has edges:

- **Difficulty is structural, not human-anchored.** Bands are decided by which
  techniques the reference solver is forced to use; no real-player solve-time
  data backs the cuts. Grid size is an independent dial the band ignores — a
  5-category hard takes longer than a 3-category one at the same tier of
  required thinking.
- **The what-if count measures a policy** (minimum-closure refutation at each
  stall), not a theoretical minimum.
- **Refutation-only reasoning** — a solver comfortable using uniqueness as an
  oracle ("assume it and see if everything works out") may finish top-band
  puzzles faster than the grade implies.
- **Propagation is sound but not complete**, so measured difficulty can
  overstate, never understate.
- **Tera recovery is graded cheaply** — the deep re-grade is early-exit and
  wall-clock-budgeted; the tera label is correct but that path's step counts
  are path-dependent. Nesting deeper than two levels is never verified and
  never shipped.
- **Minimization is budgeted** — an unconfirmable drop keeps its clue, so a
  shipped set may be slightly non-minimal (a touch easier than the board's
  true minimum).
- **The supplemental numbers are heuristics** — `difficulty_index`,
  `clue_load`, and `search_nodes` order puzzles within a band but never decide
  it.

One known gap between payload and UI: the payload describes group grids richly
enough to solve on, and `logic.js` exports a tested group-grid rule set
(`nextStateGroup` / `deriveGroup`), but `app.js` currently renders hierarchy
groups as display-only color bands — the group-grid interaction is not wired
up.

## 10. Testing and calibration

- `pytest` — one test file per module (`tests/test_model.py` …
  `tests/test_webapi.py`), covering the model, every clue family's
  `holds`/text/propagation, both solvers, generation invariants, hints, themes,
  rendering, and the API handlers.
- `node --test` — the pure front-end interaction rules in `public/logic.js`
  (mark cycling, one-✓-per-line, dim auto-✗ semantics, undo coalescing).
- `python test_smoke.py` — a legacy uniqueness/consistency sweep across all
  YAML themes and many seeds.
- `python -m logicgrid.census` — the diversity/calibration harness. Clue
  diversity has no self-verifying invariant (a family can silently die in
  minimization), so the census builds real puzzles through the shipping path
  (`webapi.build_puzzle`) and reports, per tier: average clues, average
  distinct clue *shapes* (structural signatures — e.g. a 1-of-2 exclusive
  pairing counts separately from a 2-of-3), per-shape presence, and hierarchy
  presence. `--calibration` reports the exact-band hit rate per requested
  tier. The regression floors that pin these numbers (diversity must scale
  with tier; showcase clue types must actually ship at the extreme tiers) live
  in `tests/test_census.py`.
