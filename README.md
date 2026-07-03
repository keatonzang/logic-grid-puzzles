# Logic Grid Puzzle Generator

Dynamically generate logic grid puzzles from editable theme files. Every
generated puzzle is guaranteed to have **exactly one** solution and to be
solvable by logic alone — no guessing.

**Play it in the browser:** https://logic-grid-puzzles-beta.vercel.app

```
python generate.py themes/detectives.yaml --seed 3
python generate.py themes/space_colony.yaml --show-solution
python generate.py themes/morning_rush.yaml --seed 1 --no-grid
```

The CLI reads a YAML/JSON theme and prints the clue list, blank pairwise grids
to solve on, and (optionally) the answer key. The full difficulty system —
graded tiers, richer clue families, hints — is a feature of the web app and
its API; CLI puzzles use the entry-level clue pool.

For a deep dive into how everything works (the clue algebra, the generation
pipeline, the two solvers, the difficulty grader, the hint engine), see the
[technical report](docs/ARCHITECTURE.md). For what each clue means and how to
solve, see the in-app [solver's guide](https://logic-grid-puzzles-beta.vercel.app/guide).

## Clue variety

Clues range from direct facts to compound logic, unlocked by what the theme
provides and the requested difficulty:

- **Direct** — is / is not.
- **Sequential** (needs an ordered category) — higher/lower, exact difference,
  between, immediately before/after, next to, at-least-apart, within/beyond a
  distance, higher/lower than several others.
- **Counting** — at least / at most / exactly K of N options, either/or,
  neither/nor, all-different, exclusive pairings ("either A–X or B–Y, but not
  both"), group matches ("one goes with X and the other with Y").
- **Conditionals** — if/then and if-and-only-if, whose sides can be nested
  and/or/xor statements at the extreme tiers.
- **Hierarchy** (needs a grouped category) — belongs to / same group /
  different groups, group cardinalities, group orderings, and — with two
  partitions — cross-group counts and comparisons.

Every clue is screened before it can ship: tautologies and near-tautologies
are rejected, semantic duplicates keep only the simplest phrasing, and no clue
ever contains internal redundancy (a repeated atom, or a branch that implies a
sibling branch).

## Difficulty: measured, not guessed

Difficulty is graded by a reference solver that solves each candidate puzzle
using only human-style deduction techniques, cheapest first. The five bands
separate by **which techniques the solve forces**, not by volume:

| Band | What the solve requires |
|---|---|
| **normal** | line elimination and cross-referencing only |
| **hard** | forward clue logic (counting windows, conditionals, rank bounds, set logic); never a contradiction |
| **mega** | proof by contradiction appears: at most 2 what-ifs, each refuted within a few forced cells |
| **giga** | sustained contradiction work — more, or longer, what-ifs |
| **tera** | heavy what-if volume or a nested what-if (a what-if inside a what-if) |

Generation is *generate-and-grade*: candidates are sampled and graded until
one's measured band matches the request, so the label reflects the reasoning
the puzzle actually needs. Difficulty and grid size are independent controls;
if a small grid can't reach the requested band, the request degrades
gracefully to the hardest band it can (the payload reports both). The bands,
guarantees, and known measurement limits are detailed in the
[technical report](docs/ARCHITECTURE.md).

## Web app

Pick a theme, difficulty, size, and seed, then solve in clickable pairwise
grids (a cell cycles blank → ✗ → ✓) with **Check** / **Reveal** / **Clear**,
undo/redo, and a live solution table. Puzzles are generated server-side by the
same Python package, so the uniqueness guarantee is identical to the CLI.
Solving aids:

- **Step-by-step hints** — **Hint** asks the server for the next single
  deduction from your current marks and explains it: the technique (Given,
  Elimination, Cross-reference, Clue logic, Advanced logic, What-if, Nested
  what-if) and the reasoning, e.g. *"Ava is Latte, and $5 is Latte, so Ava is
  $5."* It highlights the target cell; a second click fills it in. Hints
  replay the same solver the grader uses, so every hint is a sound, guess-free
  next move — and it skips anything you've already worked out.
- **Cross off clues** — click a clue to strike it through once you've used it.
- **Print** — a print stylesheet renders a clean black-on-white puzzle with
  the answer key on its own tear-off page.

### API

- `GET /api/puzzle?theme=…&difficulty=…&items=…&categories=…&seed=…` —
  returns a puzzle as JSON (categories, clue text, solution). The `theme` key
  and a concrete `seed` are always echoed back, so any puzzle is reproducible.
- `GET /api/puzzle?themes=1` — the theme catalogue for the picker.
- `POST /api/hint` with `{seed, theme, difficulty, items, categories, known}`
  — regenerates the exact puzzle (generation is deterministic in the seed) and
  returns the next explained deduction, or `{"done": true}`.

Deploy with `vercel --prod` from this directory.

### Built-in web themes

The CLI reads YAML files; the serverless functions can't, so web themes live
as `ThemeSpec` entries in `logicgrid/webapi.py`. Each is a subject pool plus
attribute pools; every puzzle samples a subset per category, so boards vary by
seed. Nine ship today:

| Key | Name | Numeric category | Hierarchies |
|-----|------|------------------|-------------|
| `cafe` | The Morning Rush | Price (`$`) | — |
| `kings_guild` | The King's Guild | Levy (` coins`) | guilds + wards |
| `dnd` | The Adventuring Party | Gold (` gp`) | — |
| `mystery` | Murder at the Manor | — | — |
| `space` | The Mars Colony | Distance (` ly`) | — |
| `engineer` | The Engineering Firm | Budget (`$…k`) | — |
| `school` | The Schoolhouse | Grade (`…%`) + Period (ordinal) | — |
| `fishing` | The Fishing Derby | Weight (` lb`) | families + watersheds |
| `chess` | The Chess Club | Rating + Placing (ordinal) | openings → camps |

Add a theme by appending a `ThemeSpec` to `THEME_SPECS`. A theme may declare
`extra_numerics` — additional ordered categories beyond the primary one,
rolled in only on the rich tiers (mega and up) with ≥ 4 categories. Every
ordered clue names its own dimension, so multiple dials stay unambiguous.

### Daily challenge

`/daily` serves one shared puzzle per UTC day (a 4×4 at the hard band, theme
rotating through the registry) with a per-day leaderboard. Competitive
integrity is server-side:

- The day's seed is an HMAC of a server secret, and the daily payload ships
  **no solution and no seed**, so the answer key can't be read out of the
  network tab or reproduced through `/api/puzzle`.
- Timing is server-authoritative: `GET /api/daily` issues a signed session
  token; on submit the server verifies the solution against the regenerated
  puzzle and measures elapsed time itself. Submission is all-or-nothing — a
  yes/no with no cell-level feedback (that would leak the key one probe at a
  time) — and a wrong submission leaves the clock running. A verified solve
  returns a signed single-use result token, which the player then exchanges —
  together with a display name — for a board entry, so typing a name (or
  signing in) costs no time.
- Anyone can play; **posting a time requires an account** (Supabase Auth,
  email + password, auto-confirmed — no emails sent). The API resolves the
  access token server-side and a unique `(day, user_id)` index enforces one
  score per account per day. No profiles beyond that; display names are
  still chosen per solve and filtered server-side (leet-normalized
  profanity check).
- Simple anti-cheat floors: implausibly fast times and too-few board
  interactions are rejected, sessions expire, result tokens are single-use
  (unique constraint), and entries per network per day are capped. Hint,
  Reveal, and per-cell Check don't exist on the daily.

Scores live in Supabase (`supabase/migrations/`), reached only through
`api/daily.py` with the service-role key — both tables have RLS enabled with
no policies, so the browser can never talk to the database directly (the
anon key it receives is only good for the auth endpoints). Configure with
env vars: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`,
`DAILY_SECRET` (any long random string; rotating it re-rolls upcoming
puzzles and invalidates in-flight sessions).

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

Mark a category `ordered: true` to unlock "higher/lower than" clues. **List
its items in ascending order.** Add aligned `values` to also unlock
exact-difference clues, and an optional `unit` (prefix) and/or `unit_suffix`
to format amounts in clue text — `unit: "$"` reads "exactly **$2** more",
`unit_suffix: " gp"` reads "exactly **20 gp** more":

```yaml
  - name: Landing
    items: ["2161", "2164", "2167", "2170", "2173"]
    ordered: true
    values: [2161, 2164, 2167, 2170, 2173]
```

See `themes/detectives.yaml` (plain) and `themes/space_colony.yaml` (ordered).

### Referent phrasing

Cross-category clues name an entity by one of its attributes. The first
category (the subject) reads as the bare item — a name ("Ava"). Any other
category reads as a noun phrase: by default "the {entity_noun} with {item}",
or a custom `referent` template:

```yaml
  - name: Club
    items: [Chess, Choir, Debate, Drama]
    referent: "the person studying {}"   # -> "the person studying Debate"
```

### Grouped / hierarchy categories

A category can bundle its items into named **groups** to unlock the hierarchy
clues. Give it a `group_noun` (how one group is named in clue text) and a
`groups` list partitioning its items — every item in exactly one group:

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
puzzle can always roll with no hierarchy clues at all. Declaring **two**
partitions additionally unlocks the cross-group count/comparison clues.

### Import / export

A concrete theme is fully described by one self-contained file, and
`logicgrid.themes` round-trips it:

```python
from logicgrid.themes import theme_to_json, theme_from_json
text  = theme_to_json(theme)      # export — the whole theme as one JSON string
theme = theme_from_json(text)     # import — parses + validates (ValueError on bad input)
```

The generation and hint engines accept any concrete `Theme`, so an imported
user-authored theme generates unique puzzles and step-by-step hints with no
other changes — the foundation for a future in-browser theme editor.

## Tests

```
pip install -r requirements-dev.txt
pytest                       # Python: model, clues, solvers, generate, hints, themes, webapi, api
python test_smoke.py         # legacy uniqueness/consistency sweep across themes & seeds
node --test                  # JS: front-end grid-interaction logic (public/logic.js)
python -m logicgrid.census   # diversity / calibration census of shipped clues, per tier
```

The browser solver's interaction rules (mark cycling, the one-✓-per-line
constraint, dim auto-✗ vs. bright manual-✗, auto-revert) live in the pure,
DOM-free module `public/logic.js`, unit-tested by `tests/logic.test.js`.

## Layout

```
generate.py            CLI entry point
test_smoke.py          legacy uniqueness/consistency sweep across themes & seeds
themes/                theme data files (.yaml / .json)
vercel.json            Vercel build/route config (Python functions + static site)
docs/
  ARCHITECTURE.md      technical report: how the system works
api/
  puzzle.py            serverless function: puzzle JSON
  hint.py              serverless function: next explained deduction JSON
public/                interactive browser solver (static, no build step)
tests/                 pytest suite (one file per module) + JS tests
logicgrid/
  model.py             Theme / Category data model + validation
  clues.py             clue types: direct, sequential, counting, conditional, hierarchy
  solver.py            backtracking solution counter (uniqueness check)
  generate.py          solution -> clue pool -> semantic screen -> minimal unique set
  deduce.py            human-style deductive solver + difficulty grader
  census.py            shipped-clue diversity / calibration census
  hint.py              step-by-step hint engine (explained deductive trace)
  render.py            console rendering: clues, grids, solution table
  themes.py            YAML/JSON theme loader + import/export round-trip
  webapi.py            puzzle / payload / hint builders + web theme registry
```

## Possible next steps

- **Interlocked "staircase" grid (CLI)** — the web app renders the single
  L-shaped grid on desktop; bring the same to `render.py`.
- **Difficulty in the CLI** — expose the graded tiers (`generate_rated`) as a
  `--difficulty` flag.
- **Solvable group grids** — the payload and `public/logic.js` already
  support solving on subject-by-group grids; wire them into the UI.
- **Hints in the CLI** — surface `logicgrid/hint.py`'s explained trace as an
  interactive walkthrough mode for the terminal solver.
- **More themes** — add YAML files (CLI) or a `ThemeSpec` to `THEME_SPECS`
  (web).

## License

[PolyForm Noncommercial License 1.0.0](LICENSE.md) — free to use, modify, and
share for **noncommercial** purposes; commercial use requires a separate
license.

© 2026 Keaton Zang
