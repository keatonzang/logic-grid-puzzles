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
- **higher / lower than** (`Greater`) — `The order with Latte has a higher Price than the one with Mocha.`
- **exact difference** (`Diff`) — `Latte's Price is exactly 2 more than Mocha's.` (numeric)
- **between** (`Between`) — `Cara's Price is between Ava's and Ben's.`
- **immediately before/after** (`Adjacent`) — `Ava's Price is immediately below Ben's.` (directional)
- **immediately next to** (`NextTo`) — `Cara's Price is immediately next to Latte's.` (undirected)
- **at least apart** (`AtLeastApart`) — `Ristretto's Price is at least 3 more than Jade's.` (directional, ranged)
- **away from** (`AbsApart`) — `Ben's Price is at least 3 away from Ivory's.` / `Mocha's Price is at most 2 away from Ava's.` (symmetric distance; `at most` bounds two items *close*)
- **less/more than both** (`MultiCompare`) — `Croissant's Price was more than both Hugo's and Donut's.`
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
  `build_clue_pool(multi_match=False)`; `same_category_prob` (a future difficulty knob)
  biases threshold-1 disjunctions toward all-one-category option lists.
- **either/or** (`EitherOr`, exclusive) — `Ava goes with either Bagel or Latte.`
  Exactly one holds, so the two options must sit on **different** entities. Takes any N
  (`exactly one of A, B, or C`).
- **neither/nor** (`Neither`) — `Ava goes with neither Bagel nor Latte.` / `none of A, B, or C.`
- **all different** (`AllDifferent`) — `Ava, Ben, Chai, and Latte are all different orders.`
  N terms on distinct entities, spanning ≥ 2 categories (categories may repeat). Equivalent
  to the conjunction of the pairwise "is not" facts; generated for N in 3..items
  (`alldiff_sizes`).
- **exclusive pairing** (`ExactlyKLinks`) — `Either Ben goes with Latte, or Cara goes with Chai — but not both.`
  Exactly K of N independent links hold (K=1, N=2 is the XOR; `pairing_k` / `pairing_sizes`).
- **group match** (`GroupMatch`) — `Between Ava and Ben, one goes with Latte and the other with Bagel.`
  Two equal-size groups cover the same entities, paired in unknown order; N in 2..items
  (`match_sizes`). For N ≥ 3: `… go with …, in some order.`

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
   clue types.

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
| 3 | clue propagation — among / either-or / exactly-K / group-match narrowing |
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

See `themes/detectives.yaml` (plain) and `themes/space_colony.yaml` (ordered).

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

- `api/puzzle.py` — Vercel serverless function. `GET /api/puzzle?difficulty=…&
  items=…&categories=…&seed=…` returns a puzzle as JSON (categories, clue text,
  and the solution; a concrete `seed` is always echoed back so any puzzle is
  reproducible).
- `api/hint.py` — Vercel serverless function. `POST /api/hint` with
  `{seed, difficulty, items, categories, known}` regenerates the exact puzzle
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
  webapi.py            puzzle / payload / hint builders (web/serverless layer)
```

## Possible next steps

- **Interlocked "staircase" grid (CLI)** — the web app renders the single
  L-shaped grid on desktop; bring the same to `render.py`.
- **Natural-language phrasing templates** per theme for richer clue prose.
- **More themes** — add YAML files and mirror them into `logicgrid/webapi.py`.
- **Hints in the CLI** — surface `logicgrid/hint.py`'s explained trace as an
  interactive `--hint`/walkthrough mode for the terminal solver.

## License

[PolyForm Noncommercial License 1.0.0](LICENSE.md) — free to use, modify, and
share for **noncommercial** purposes; commercial use requires a separate license.

© 2026 Keaton Zang
