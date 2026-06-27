# Logic Grid Puzzle Generator

Dynamically generate logic grid puzzles from editable theme
files. Each generated puzzle is guaranteed to have **exactly one** solution.

```
python generate.py themes/detectives.yaml --seed 3
python generate.py themes/space_colony.yaml --show-solution
python generate.py themes/morning_rush.yaml --seed 1 --no-grid
```

## What it produces

For a theme of K categories × N items, the generator emits a clue list, a set
of blank pairwise grids to solve on, and (optionally) the answer key. Clues come
in many flavours:

- **is** — `Marple goes with Study.`
- **is not** — `Spade does not go with Library.`
- **higher / lower than** (`Greater`) — `The order with Latte has a higher price than the one with Mocha.`
- **exact difference** (`Diff`) — `Latte's price is exactly $2 more than Mocha's.` (numeric)
- **between** (`Between`) — `Cara's price is between Ava's and Ben's.`
- **immediately before/after** (`Adjacent`) — `Ava's price is immediately below Ben's.` (directional)
- **immediately next to** (`NextTo`) — `Cara's price is immediately next to Latte's.` (undirected)
- **at least apart** (`AtLeastApart`) — `Ristretto's price is at least $3 more than Jade's.` (directional, ranged)
- **away from** (`AbsApart`) — `Ben's price is at least $3 away from Ivory's.` / `Mocha's price is at most $2 away from Ava's.` (symmetric distance; `at most` bounds two items *close*)
- **less/more than both** (`MultiCompare`) — `Croissant's price was more than both Hugo's and Donut's.`
- **at most K of N** (`AtMost`) — `Vanilla goes with at most one of Ben, Rose, and $8.` (complement of Among)

These **sequential** clues need an *ordered* category. The café rolls in a
numeric **Price** category (~50% of medium/hard puzzles), sorted by value (= rank);
the web app also supports **3–5 categories** (Customer + a sample of Drink / Pastry /
Syrup / Mug, plus maybe Price), with items per category capped as categories grow so
generation stays fast. The two sides of a comparison are drawn from *distinct*
categories where possible, so clues mix categories freely (e.g. the Ben order vs the
Ivory-mug order). Each sequential clue has a sound deductive propagator
(bounds/arc-consistency on ranks) so price puzzles stay logic-solvable.
- **at least K of N** (`Among`, inclusive) — `Ava goes with at least one of Bagel or Latte.`
  / `Holmes goes with at least two of Butler, Attic, and Painting.` Options may span
  categories; being inclusive it does **not** imply they differ. A threshold K ≥ 2 needs
  options in **distinct categories** (one match max per category), which the generator
  enforces. K is always kept **below N** (no strong K = N case), so a threshold clue
  never collapses to N direct links. Disable the K ≥ 2 variants with
  `build_clue_pool(multi_match=False)`. Option lists are sampled freely across
  categories (no same-category weighting).
- **either/or** (`EitherOr`, exclusive) — `Ava goes with either Bagel or Latte.`
  Exactly one holds, so the two options must sit on **different** entities. Takes any N
  (`exactly one of A, B, or C`).
- **neither/nor** (`Neither`) — `Ava goes with neither Bagel nor Latte.` / `none of A, B, or C.`
- **all different** (`AllDifferent`) — `Ava, Ben, Chai, and Latte belong to different orders.`
  N terms on distinct entities, spanning ≥ 2 categories (categories may repeat). Equivalent
  to the conjunction of the pairwise "is not" facts; generated for N in 3..items
  (`alldiff_sizes`).
- **exclusive pairing** (`ExactlyKLinks`) — `Either Ben goes with Latte, or Cara goes with Chai — but not both.`
  Exactly K of N independent links hold (K=1, N=2 is the XOR; `pairing_k` / `pairing_sizes`).
- **group match** (`GroupMatch`) — `Between Ava and Ben, one goes with Latte and the other with Bagel.`
  Two equal-size groups cover the same entities, paired in unknown order; N in 2..items
  (`match_sizes`). For N ≥ 3: `… go with …, in some order.`
- **exactly K of N** (`Exactly`) — `Ava goes with exactly two of Bagel, Latte, and the Jade mug.`
  Precisely K options match — `Among` (≥ K) and `AtMost` (≤ K) at once (`enable_exactly`).
- **if–then** (`Implies`) — `If Ava goes with Latte, then Ben goes with the Bagel.`
  A one-way conditional: when the antecedent link holds the consequent must too. Fires
  forward (modus ponens) and backward (contrapositive). Hard puzzles only (`enable_conditional`).
- **if and only if** (`Iff`) — `Ava goes with Latte if and only if Ben goes with the Bagel.`
  Both links are true together or false together (degenerate 2-entity cases are deduped
  against `GroupMatch`, which subsumes them). Hard only.

These **group / hierarchy** clues need a theme whose grouped category defines `groups`
(e.g. King's Guild files each *trade* into a *guild*). They compile down to facts on that
existing category — no extra grid — and only appear when a puzzle keeps one (`enable_groups`,
medium/hard); a puzzle can always roll with no hierarchy at all.

- **belongs to a group** (`InGroup`) — `The artisan with the Millpond workshop belongs to the Ironmongers' Guild.`
  The entity's trade is one of that guild's members.
- **same group** (`SameGroup`) — `… and … are in the same guild.` Both entities' trades share a guild.
- **different groups** (`DiffGroup`) — `… and … are in different guilds.` Their trades lie in separate guilds.

The "one of N" disjunctions default to N ∈ {2, 3} via `build_clue_pool(among_sizes=…)`.

## How it works

1. **Random solution.** Pick a random bijection between every category (a grid
   `X[entity][category] = item`, anchored so entity *i* is the *i*-th item of
   category 0).
2. **Clue pool.** Enumerate clues that are *true* under that solution — all
   positive links, a sample of negatives, and comparisons/differences for any
   ordered category.
3. **Minimize.** Greedily drop clues in random order as long as the puzzle still
   has a unique solution (verified by a backtracking solution-counter that stops
   at 2). The result is a compact, locally-minimal clue set with a natural mix of
   clue types. The one deliberate skew: group/hierarchy clues are considered for
   removal last, so they survive into ~half of hard grouped puzzles instead of
   ~5% — they carry real deductive weight, so keeping them doesn't soften the
   measured difficulty band.

The solver assigns one category column at a time (most-constrained first) and
prunes against every clue whose columns are fully assigned, so the small sizes
typical of these puzzles (≤ 6×6) solve instantly.

## Difficulty: measured, not guessed (`logicgrid/deduce.py`)

Difficulty is *measured* by a second, human-style solver that uses only
deduction techniques, cheapest first, and reports what the solve required:

| Tier | Technique |
|---|---|
| 0 | givens — direct is / is-not / neither / all-different |
| 1 | line completion — each item links exactly one other in a block |
| 2 | transitivity — combine blocks through a shared entity (the core move) |
| 3 | clue propagation — among / either-or / exactly-K / conditional / group-match / hierarchy narrowing |
| 4 | proof by contradiction — assume a cell, propagate, eliminate on conflict |

The **band** is the hardest technique needed: ceiling ≤ 2 → **easy**, 3 →
**medium**, 4 → **hard**. This is rigorous logic, not guessing — tiers 1–3 are
forward propagation, tier 4 is a contradiction proof. Generation is
**generate-and-grade**: sample candidates, grade each, keep one whose *measured*
band matches the request — so every puzzle is **solvable by logic alone, no
guessing**, and "hard" genuinely requires a contradiction step. (A rare puzzle
needing nested hypotheticals — "tier 5+" — is skipped for now.)

## Writing a theme

Themes are plain YAML (or JSON — same shape, no PyYAML needed). All categories
must have the same number of items, and item labels must be unique across the
whole puzzle so clues read unambiguously.

```yaml
name: "The Vanished Heirloom"
description: "Four detectives, four suspects..."
entity_noun: case          # how a single row is referred to in clue text

categories:
  - name: Detective
    items: [Holmes, Marple, Poirot, Spade]
  - name: Suspect
    items: [Butler, Cousin, Gardener, Maid]
```

### Ordered / numeric categories

Mark a category `ordered: true` to unlock "higher/lower than" clues. **List its
items in ascending order.** Add aligned `values` to also unlock exact-difference
clues:

```yaml
  - name: Landing
    items: ["2161", "2164", "2167", "2170", "2173"]
    ordered: true
    values: [2161, 2164, 2167, 2170, 2173]
```

Add an optional `unit` (a prefix) and/or `unit_suffix` to format the *amounts* in
numeric clue text — `unit: "$"` makes a difference clue read "exactly **$2**
more", while `unit_suffix: " gp"` reads "exactly **20 gp** more". The café's Price
uses a prefix, the D&D theme's Gold a suffix; both default to empty (plain
numbers).

See `themes/detectives.yaml` (plain) and `themes/space_colony.yaml` (ordered).

### Referent phrasing

Cross-category clues name an entity by one of its attributes. The first category
(the subject) is the entity's identity and reads as the bare item — a name
("Ava"). Any other category reads as a noun phrase: by default "the
{entity_noun} with {item}" ("the order with Latte"), or a custom `referent`
template you supply:

```yaml
  - name: Club
    items: [Chess, Choir, Debate, Drama]
    referent: "the person studying {}"   # -> "the person studying Debate"
```

So a clue reads "Ellis' Grade is at least 4% away from the person studying
Debate" rather than the bare "…away from Debate's". (In a web `ThemeSpec`, the
same is given as a `referents=(("Club", "the person studying {}"), …)` tuple.)

### Grouped / hierarchy categories

A category can bundle its items into named **groups** to unlock the hierarchy
clues (*belongs to a group* / *same group* / *different groups*). Give the
category a `group_noun` (how one group is named in clue text) and a `groups`
list partitioning its items — every item must appear in exactly one group:

```yaml
  - name: Trade
    items: [Blacksmith, Carpenter, Cooper, Fletcher, Mason, Potter, Tanner, Weaver]
    group_noun: guild
    groups:
      - { label: "Ironmongers' Guild", items: [Blacksmith, Fletcher, Mason] }
      - { label: "Joiners' Guild",     items: [Carpenter, Cooper, Potter] }
      - { label: "Clothiers' Guild",   items: [Tanner, Weaver] }
```

Groups compile to facts on the `Trade` column — there is no extra grid — so a
puzzle can always roll with no hierarchy clues at all, and the guilds are only
ever mentioned when one survives into the clue set. See `themes/` for the King's
Guild theme; in a web `ThemeSpec` the same is a `group_def=(category, group_noun,
((label, (items…)), …))` tuple, restricted to the sampled items at build time.

### Single-file representation (import / export)

A concrete theme is **fully described by one self-contained file**. The dict
above *is* the format; `logicgrid.themes` round-trips it:

```python
from logicgrid.themes import theme_to_json, theme_from_json
text  = theme_to_json(theme)      # export — the whole theme as one JSON string
theme = theme_from_json(text)     # import — parses + validates (raises ValueError on bad input)
```

The generation and hint engines accept any concrete `Theme`, so an imported
user-authored theme generates unique puzzles and step-by-step hints with no
other changes — the foundation for a future in-browser theme editor with
file import/export. (A serverless endpoint would accept the theme *definition*
rather than a registry *key*, sending the same definition to `/api/hint` so the
puzzle regenerates identically — same seed-determinism contract.)

### Built-in web themes

The web app ships a registry of themes (the CLI reads YAML files; the serverless
functions can't, so the web themes live as specs in `logicgrid/webapi.py`). Each
spec is a subject pool, several attribute pools (each with enough members for the
largest grid), and an optional numeric category; every puzzle samples `items`
members per category and which attributes appear varies per seed. The picker is a
drop-down, served from `GET /api/puzzle?themes=1`:

| Key | Name | Numeric category |
|-----|------|------------------|
| `cafe` | The Morning Rush | Price (`$`) |
| `kings_guild` | The King's Guild | Dues (` coins`) |
| `dnd` | The Adventuring Party | Gold (` gp`) |
| `mystery` | Murder at the Manor | — |
| `space` | The Mars Colony | Distance (` ly`) |
| `engineer` | The Engineering Firm | Budget (`$…k`) |
| `school` | The Schoolhouse | Grade (`…%`) |

Add a theme by appending a `ThemeSpec` to `THEME_SPECS` in `logicgrid/webapi.py`.
A theme can also declare `extra_numerics` — additional ordered categories beyond
the primary one. These are gated: a second ordered dial is rolled in only on
**hard** puzzles with **≥4 categories** (so small grids don't get over-constrained).
The Schoolhouse uses this for a class's *Grade* (numeric, `%`) plus its *Period*
(an ordinal — `NumericSpec(..., valued=False)` → "Period 1", higher/next-to clues
but no "2 more"). Every ordered clue names its own dimension, so multiple dials
stay unambiguous.

## Web app

An interactive browser solver is deployed on Vercel:

**https://logic-grid-puzzles-beta.vercel.app**

Pick a difficulty, size, and seed, then solve in clickable pairwise grids (click
a cell to cycle blank → ✓ → ✗) with **Check** / **Reveal** / **Clear**. Puzzles
are generated server-side by the same Python package via a serverless function,
so the uniqueness guarantee is identical to the CLI. Three solving aids:

- **Step-by-step hints** — **Hint** asks the server for the *next single
  deduction* from your current marks and explains it: the technique (Given,
  Elimination, Cross-reference, Clue logic, What-if) and the reasoning, e.g.
  *“Ava is Latte, and $5 is Latte, so Ava is $5.”* It highlights the target
  cell; a second click fills it in. The hint engine replays the very same tiers
  the grader uses (`logicgrid/hint.py`), so a hint is always a sound, guess-free
  next move — and it skips anything you've already worked out.
- **Cross off clues** — click a clue to strike it through once you've used it.
- **Print** — a print stylesheet renders a clean black-on-white puzzle (title,
  clues, blank grids) with the **answer key on its own tear-off page**. Print or
  save-as-PDF straight from the browser.

- `api/puzzle.py` — Vercel serverless function. `GET /api/puzzle?theme=…&
  difficulty=…&items=…&categories=…&seed=…` returns a puzzle as JSON (categories,
  clue text, and the solution; the `theme` key and a concrete `seed` are always
  echoed back so any puzzle is reproducible). `GET /api/puzzle?themes=1` returns
  the theme catalogue for the picker.
- `api/hint.py` — Vercel serverless function. `POST /api/hint` with
  `{seed, theme, difficulty, items, categories, known}` regenerates the exact puzzle
  (generation is deterministic in the seed) and returns the next explained
  deduction, or `{"done": true}` once nothing new can be deduced.
- `logicgrid/webapi.py` — dependency-free puzzle/payload/hint builders shared by
  the functions and the tests.
- `logicgrid/hint.py` — the step-by-step hint engine: an explained replay of the
  deductive solver's tiers.
- `public/` — static front end (`index.html` / `style.css` / `app.js`), no build step.
- `vercel.json` — `@vercel/python` functions (bundling `logicgrid/`) + static `public/`.

Deploy with `vercel --prod` from this directory.

## Tests

```
pip install -r requirements-dev.txt
pytest                 # Python: model, clues, solver, generate, themes, render, webapi, api
python test_smoke.py   # legacy uniqueness/consistency sweep across themes & seeds
node --test            # JS: front-end grid-interaction logic (public/logic.js)
```

The browser solver's interaction rules (mark cycling, the one-`=`-per-line
constraint, dim auto-× vs. bright manual-×, auto-revert) live in the pure,
DOM-free module `public/logic.js`, unit-tested by `tests/logic.test.js`.

## Layout

```
generate.py            CLI entry point
test_smoke.py          legacy uniqueness/consistency sweep across themes & seeds
themes/                theme data files (.yaml / .json)
vercel.json            Vercel build/route config (Python function + static site)
api/
  puzzle.py            serverless function: puzzle JSON
  hint.py              serverless function: next explained deduction JSON
public/                interactive browser solver (static)
tests/                 pytest suite (one file per module)
logicgrid/
  model.py             Theme / Category data model + validation
  clues.py             clue types (Positive/Negative/Greater/Diff)
  solver.py            backtracking solution counter (uniqueness check)
  generate.py          solution → clue pool → minimal unique set
  deduce.py            human-style deductive solver + difficulty grader
  hint.py              step-by-step hint engine (explained deductive trace)
  render.py            console rendering: clues, grids, solution table
  themes.py            YAML/JSON theme loader
  webapi.py            puzzle / payload / hint builders + web theme registry
```

## Possible next steps

- **Interlocked "staircase" grid (CLI)** — the web app renders the single
  L-shaped grid on desktop; bring the same to `render.py`.
- **Natural-language phrasing templates** per theme for richer clue prose.
- **More themes** — add YAML files (CLI) or a `ThemeSpec` to `THEME_SPECS` in
  `logicgrid/webapi.py` (web). The web app currently ships six (see above).
- **Hints in the CLI** — surface `logicgrid/hint.py`'s explained trace as an
  interactive `--hint`/walkthrough mode for the terminal solver.

## License

[PolyForm Noncommercial License 1.0.0](LICENSE.md) — free to use, modify, and
share for **noncommercial** purposes; commercial use requires a separate license.

© 2026 Keaton Zang
