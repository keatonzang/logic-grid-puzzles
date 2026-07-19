---
name: verify
description: How to run and drive this app locally to verify front-end changes at the real surface.
---

# Verifying front-end changes (public/*.js, *.html, *.css)

## Cheapest full runtime surface: /big

The big-puzzles page needs no Python API — bundles are static JSON under
`public/big/`. Serve `public/` statically and deep-link a bundle by **hash**
(not query param):

```bash
cd public && python3 -m http.server 8613 &
# open http://localhost:8613/big.html#3x6-mega-001   (ids = filenames in public/big/)
```

Free play (`index.html`) and the daily need the Python API (`/api/*`) — use a
Vercel preview deployment for those, or `vercel dev`.

## Driving it headless

No Chrome extension needed: system Chrome at `/usr/bin/google-chrome` +
`puppeteer-core` (install in the scratchpad, not the repo). Launch with
`executablePath: "/usr/bin/google-chrome"`, `args: ["--no-sandbox"]`.

Useful handles inside the page (classic script — top-level `let`s are visible
to `page.evaluate`):
- `manual[key][a][b]` — player marks (0 empty / 1 ✓ / 2 ✗), `key` = `"i-j"` pair
- `linked[key]` — Set of `"a,b"` truth links (absent on the daily)
- cells: `td.cell[data-key][data-a][data-b]`; feedback bar: `#feedback`;
  buttons by id: `#check #reveal #clear #hint #undo #redo`

Gotchas:
- Wait ~350ms between clicks on the same cell — rapid clicks coalesce into one
  undo step (COALESCE_MS).
- `pkill -f "http.server 8613"` kills your own shell (the pattern matches the
  compound command) — use a bracketed pattern: `pkill -f "[h]ttp.server 8613"`.
