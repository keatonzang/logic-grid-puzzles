"use strict";

const $ = (id) => document.getElementById(id);
const STATES = ["", "=", "×"]; // 0 blank, 1 link (=), 2 no-link (×)
// Per-group accent colors, ordered by hue (amber → green → blue → violet →
// pink) so alphabetically-sorted groups pick up an even spread across the wheel.
const GROUP_COLORS = ["#ffc46e", "#51cf66", "#6ea8fe", "#c9a7ff", "#ff8fab"];
// Supergroup bands (the coarse level of a nested hierarchy) use a muted,
// clearly-different palette so the two tiers never read as one.
const SUPER_COLORS = ["#9bb0d3", "#d3a98c"];
const DESKTOP = window.matchMedia("(min-width: 821px)"); // staircase vs pairwise
// Daily-challenge mode (/daily sets body[data-mode="daily"]): one shared
// puzzle per day whose payload ships NO solution — checking happens server-
// side — plus a leaderboard. Hint/Reveal/Check-as-you-go don't exist there.
const DAILY = document.body.dataset.mode === "daily";
// Big-puzzles mode (/big): pre-generated oversized grids served as static
// JSON, each playable under several themes — same logic, swapped vocabulary.
const BIG = document.body.dataset.mode === "big";

let puzzle = null;        // current payload
// `manual` is the source of truth: what the user explicitly set in each cell
// (0 blank, 1 link "=", 2 no-link "×"). The displayed × marks are *derived*:
// any blank cell sharing a row or column with a manual "=" shows an auto "×".
let manual = {};          // "i-j" -> n_i x n_j array of 0/1/2 (user intent)
let linked = {};          // "i-j" -> Set of "aIdx,bIdx" that are truly linked
let pendingHint = null;   // a fetched hint awaiting its "reveal tile" click

// Solve timer: counts up from generation completion to a verified solve. Purely
// in-browser (performance.now, no server/leaderboard). `timerStart` is the t0;
// `timerRAF` is the live animation-frame handle; `timerDone` freezes it after a
// solve or reveal so re-checking doesn't restart the clock.
let timerStart = 0;
let timerRAF = null;
let timerDone = false;
// Captured once, on the checking run that first solves the puzzle — reused by
// "Share result" even if the player clicks Check again afterward.
let solvedElapsedMs = null;

// Undo/redo. Rapid repeat clicks on one cell within this window count as a
// single gesture (so a double-click blank → × → = undoes in one step); slower
// clicks stay separate. `history.size()` is the step count reported on a solve.
const COALESCE_MS = 350;
const history = LG.makeHistory(COALESCE_MS);

// Snapshot of every grid's manual array, for diffing a mutation into an action.
function snapshotManual() {
  const s = {};
  for (const key of Object.keys(manual)) s[key] = manual[key].map((row) => row.slice());
  return s;
}

// Run a board mutation and log it as one undoable action. `coalesceKey`
// (a cell id) lets same-cell rapid edits merge; pass null for bulk changes.
function recordMutation(mutate, coalesceKey) {
  const before = snapshotManual();
  mutate();
  const cells = [];
  for (const key of Object.keys(manual)) {
    const M = manual[key], B = before[key];
    for (let a = 0; a < M.length; a++)
      for (let b = 0; b < M[a].length; b++)
        if (M[a][b] !== B[a][b]) cells.push({ key, a, b, before: B[a][b], after: M[a][b] });
  }
  if (!cells.length) return;
  history.record(cells, cells.length === 1 ? coalesceKey : null, performance.now());
  updateUndoUI();
}

function repaintCells(cells) {
  const keys = new Set(cells.map((c) => c.key));
  for (const key of keys) paintGrid(key);
}

// Shared tail for every board edit: a change invalidates a prior check and any
// pending hint, and the live solution table must follow.
function afterEdit() {
  clearHighlights();
  resetHintButton();
  setFeedback("");
  renderProgress();
}

function undoEdit() {
  const act = history.undo();
  if (!act) return;
  for (const c of act.cells) manual[c.key][c.a][c.b] = c.before;
  repaintCells(act.cells);
  afterEdit();
  updateUndoUI();
}

function redoEdit() {
  const act = history.redo();
  if (!act) return;
  for (const c of act.cells) manual[c.key][c.a][c.b] = c.after;
  repaintCells(act.cells);
  afterEdit();
  updateUndoUI();
}

function updateUndoUI() {
  $("undo").disabled = !history.canUndo();
  $("redo").disabled = !history.canRedo();
}

function fmtTime(ms) {
  const tenths = Math.floor(ms / 100); // a tenth-of-a-second resolution
  const s = Math.floor(tenths / 10), d = tenths % 10;
  if (s < 60) return `${s}.${d}s`;
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}.${d}`;
}

// The live ticking clock is hidden in free play — we still measure the elapsed
// time and report it on a solve, just without a running display. The daily is
// a race, so there the clock shows (the OFFICIAL time is measured server-side
// from when the puzzle was fetched; this display is a close approximation).
const SHOW_LIVE_TIMER = DAILY;

function paintTimer() {
  $("timer").textContent = fmtTime(performance.now() - timerStart);
}

function startTimer() {
  if (timerRAF) cancelAnimationFrame(timerRAF);
  timerStart = performance.now();
  timerDone = false;
  const t = $("timer");
  t.classList.remove("done");
  if (!SHOW_LIVE_TIMER) { t.hidden = true; return; } // measure silently
  t.hidden = false;
  const tick = () => {
    if (timerDone) return;
    paintTimer();
    timerRAF = requestAnimationFrame(tick);
  };
  tick();
}

// Freeze/unfreeze only the ticking DISPLAY (the measured elapsed time keeps
// its original t0). The daily pauses the readout the instant Submit is
// clicked — the official clock stops when the request reaches the server —
// and resumes it if the verdict comes back "not correct".
function pauseTimerDisplay() {
  if (timerRAF) { cancelAnimationFrame(timerRAF); timerRAF = null; }
}
function resumeTimerDisplay() {
  if (timerDone || !SHOW_LIVE_TIMER || timerRAF) return;
  const tick = () => {
    if (timerDone) return;
    paintTimer();
    timerRAF = requestAnimationFrame(tick);
  };
  tick();
}

// Freeze the clock. `solved` true marks a genuine solve (the time stays as a
// little trophy); otherwise it just stops (e.g. the player revealed the answer).
function stopTimer(solved) {
  if (timerDone || !timerStart) return;
  timerDone = true;
  if (timerRAF) { cancelAnimationFrame(timerRAF); timerRAF = null; }
  if (!SHOW_LIVE_TIMER) return; // stays hidden; the time is reported in the solve banner
  paintTimer();
  if (solved) $("timer").classList.add("done");
}

const TIMEOUT_MSG =
  "The puzzle took too long to generate. Tap Generate to try again — " +
  "a fresh attempt usually comes right through (or pick a smaller size).";

// Parse a JSON response, but turn a timeout / gateway error (which comes back as
// a non-JSON HTML page, not our {error: …} shape) into a friendly, retry-able
// message instead of a cryptic "Unexpected token <".
async function readJSON(res) {
  let data;
  try {
    data = await res.json();
  } catch {
    throw new Error(res.status >= 500 ? TIMEOUT_MSG : `Request failed (${res.status})`);
  }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

async function fetchJSON(url) {
  return readJSON(await fetch(url));
}

async function postJSON(url, body) {
  return readJSON(
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

// --- Sharing ------------------------------------------------------------
// The native share sheet on mobile (email/SMS/social all show up for free);
// desktop browsers mostly lack navigator.share, so clipboard is the fallback.
// Reuses the existing feedback banner rather than adding a new toast component.
async function shareOrCopy({ text, url }) {
  const full = url ? `${text}\n${url}` : text;
  if (navigator.share) {
    try {
      await navigator.share({ text: full });
      return;
    } catch (e) {
      if (e.name === "AbortError") return; // the user dismissed the share sheet
    }
  }
  try {
    await navigator.clipboard.writeText(full);
    setFeedback("Copied to clipboard!", "good");
  } catch (e) {
    setFeedback("Couldn't copy automatically — link: " + (url || ""), "warn");
  }
}

// --- Custom (user-authored) themes -------------------------------------------
// A theme document is the single-file JSON the /builder page exports. The main
// page plays it via POST /api/puzzle (the doc travels in the body), and every
// hint request re-sends the SAME document the current puzzle was generated
// from, so seed-determinism regenerates the identical puzzle server-side.
const CUSTOM_KEY = "custom";
const CUSTOM_STORE = "lgp-custom-theme"; // written by builder.js "Play this theme"
let customDoc = null; // the currently loaded theme document
let puzzleDoc = null; // the document the CURRENT puzzle was generated from

function loadStoredCustom() {
  try {
    const raw = localStorage.getItem(CUSTOM_STORE);
    if (raw) customDoc = JSON.parse(raw);
  } catch (e) { /* blocked storage or bad JSON — start without one */ }
}

function ensureCustomOption() {
  const sel = $("theme");
  let opt = sel.querySelector(`option[value="${CUSTOM_KEY}"]`);
  if (!opt) {
    opt = document.createElement("option");
    opt.value = CUSTOM_KEY;
    sel.appendChild(opt);
  }
  opt.textContent = customDoc ? `Custom: ${customDoc.name || "My theme"}` : "My theme (upload…)";
}

function isCustom() {
  return $("theme").value === CUSTOM_KEY;
}

function syncCustomControls() {
  // a custom document fixes its own grid, so the size dropdowns don't apply
  $("items").disabled = isCustom();
  $("categories").disabled = isCustom();
}

// Difficulty bands, easiest→hardest (matches the <select> order and the server's
// DIFFICULTIES). Used to pick the closest band when an exact re-roll match fails.
const BANDS = ["normal", "hard", "mega", "giga", "tera"];
// How many fresh seeds to try when enforcing the requested band. The server's
// grade can land a band off the request (e.g. a "giga" ask overshooting to
// "tera"); re-rolling almost always lands the exact band within a couple tries.
// Bounded so an unreachable band (e.g. tera on a tiny grid) still returns the
// closest we found instead of looping forever.
const REROLL_CAP = 6;

// Bumped on every generate() call so a slower earlier request can detect that a
// newer one has superseded it and bail out instead of clobbering its puzzle.
let genToken = 0;

// A generated puzzle is fully reproducible from theme+difficulty+categories+
// items+seed (the server seeds one random.Random up front), so every generate()
// reflects those into the URL — a "Share puzzle" link is just the address bar.
function reflectPuzzleURL() {
  const p = new URLSearchParams({
    theme: puzzle.theme,
    difficulty: puzzle.requested,
    categories: String(puzzle.categories.length),
    items: String(puzzle.items),
    seed: String(puzzle.seed),
  });
  window.history.replaceState(null, "", `?${p}`); // `history` here is the undo/redo stack, not window.history
}

// The read-back half of reflectPuzzleURL(): a shared link arrives with these
// params, so pin the controls to them before the first generate() fires.
function applySharedPuzzleParams() {
  const p = new URLSearchParams(location.search);
  const seed = p.get("seed");
  if (!seed) return;
  const theme = p.get("theme");
  if (theme && $("theme").querySelector(`option[value="${theme}"]`)) $("theme").value = theme;
  const difficulty = p.get("difficulty");
  if (difficulty && BANDS.includes(difficulty)) $("difficulty").value = difficulty;
  const categories = p.get("categories");
  if (categories) $("categories").value = categories;
  syncItemOptions();
  const items = p.get("items");
  if (items) $("items").value = items;
  $("seed").value = seed;
}

async function generate() {
  const myGen = ++genToken;
  const stale = () => myGen !== genToken;
  const want = $("difficulty").value;
  const baseParams = () => {
    const p = new URLSearchParams({
      difficulty: want,
      items: $("items").value,
      categories: $("categories").value,
    });
    const theme = $("theme").value;
    if (theme) p.set("theme", theme);
    return p;
  };
  const seed = $("seed").value.trim();
  const doc = isCustom() ? customDoc : null;
  if (isCustom() && !doc) {
    $("theme-file").click(); // no document loaded yet — ask for the file first
    return;
  }
  // GET for registry themes; POST with the document for custom ones.
  const fetchCand = (seedVal) => {
    if (doc) {
      const body = { theme_doc: doc, difficulty: want };
      if (seedVal !== undefined) body.seed = seedVal;
      return postJSON("/api/puzzle", body);
    }
    const p = baseParams();
    if (seedVal !== undefined) p.set("seed", seedVal);
    return fetchJSON(`/api/puzzle?${p}`);
  };

  $("error").hidden = true;
  $("loading").hidden = false;
  $("loading").textContent = "Loading…";
  $("puzzle").hidden = true;
  try {
    if (seed !== "") {
      // Pinned seed: reproduce exactly that puzzle — never re-roll.
      const result = await fetchCand(seed);
      if (stale()) return; // a newer generate() took over while we awaited
      puzzle = result;
    } else {
      // No seed: re-roll fresh seeds until the *measured* band matches the
      // request, so a "giga" request yields a giga-graded puzzle. Each fetch
      // omits the seed, so the server randomises and echoes back a reproducible
      // one. Keep the closest-by-band candidate as a fallback if no exact hit.
      // The loading line reports each attempt and which band it rolled, so the
      // re-rolling is visible rather than a silent wait.
      let best = null;
      const rolled = [];
      const dist = (b) => Math.abs(BANDS.indexOf(b) - BANDS.indexOf(want));
      const status = (attempt) => {
        const sofar = rolled.length ? ` — rolled ${rolled.join(", ")}` : "";
        $("loading").textContent =
          `Generating a ${want} puzzle… attempt ${attempt}/${REROLL_CAP}${sofar}`;
      };
      for (let attempt = 1; attempt <= REROLL_CAP; attempt++) {
        status(attempt);
        const cand = await fetchCand();
        if (stale()) return; // a newer generate() took over while we awaited
        if (cand.difficulty === want) { best = cand; break; }
        rolled.push(cand.difficulty);
        if (best === null || dist(cand.difficulty) < dist(best.difficulty)) best = cand;
      }
      puzzle = best;
    }
    puzzleDoc = doc; // hints must re-send exactly what this puzzle was built from
    if (!doc) reflectPuzzleURL(); // a custom theme doc has no short URL form
    buildState();
    render();
    $("puzzle").hidden = false;
    fitBoard(); // now the grid has a real width to measure against
    startTimer(); // time the solve from the moment the puzzle is on screen
  } catch (err) {
    if (stale()) return; // don't surface a superseded request's failure
    $("error").textContent = err.message;
    $("error").hidden = false;
  } finally {
    // Only the latest request owns the loading line; a stale one leaving it
    // alone keeps the newer request's spinner intact.
    if (!stale()) $("loading").hidden = true;
  }
}

function pairs() {
  const k = puzzle.categories.length;
  const out = [];
  for (let i = 0; i < k; i++) for (let j = i + 1; j < k; j++) out.push([i, j]);
  return out;
}

// --- Group display helpers --------------------------------------------------
// A grouped category's items are reordered for display so each group's members
// sit contiguously, which lets us draw a labelled group band with sub-dividers.
// Only the visual order changes — data indices (data-a/-b, manual[], linked[])
// stay the natural index order, so all link/state logic is untouched.
function catGroups(ci) {
  const c = puzzle.categories[ci];
  const gs = c && c.groups && c.groups.length ? c.groups : null;
  if (!gs) return null;
  // With a nested hierarchy, order the groups so wards of the same side of
  // town sit adjacent — the coarse structure then reads off the band order
  // (the rosters themselves are spelled out under the description).
  const sgs = c.supergroups && c.supergroups.length ? c.supergroups : null;
  if (!sgs) return gs;
  const superOf = (g) => {
    const i = sgs.findIndex((s) => s.items.includes(g.items[0]));
    return i < 0 ? sgs.length : i;
  };
  return gs.slice().sort(
    (a, b) => superOf(a) - superOf(b) || a.label.localeCompare(b.label)
  );
}

// Item indices of category `ci` in display order (group order, then theme order).
function displayOrder(ci) {
  const c = puzzle.categories[ci];
  const gs = catGroups(ci);
  if (!gs) return c.items.map((_, k) => k);
  const order = [];
  for (const g of gs) for (const it of g.items) order.push(c.items.indexOf(it));
  return order;
}

// Contiguous group runs over the display order: {label, color, start, size}.
function groupSegments(ci) {
  const gs = catGroups(ci);
  if (!gs) return null;
  let start = 0;
  return gs.map((g, gi) => {
    const seg = { label: g.label, color: GROUP_COLORS[gi % GROUP_COLORS.length], start, size: g.items.length };
    start += g.items.length;
    return seg;
  });
}

// Contiguous supergroup runs over the display order: {label, color, start,
// size}. catGroups already orders a nest's groups supergroup-contiguously,
// so each supergroup is one run — the outer band tier above the group band.
function supergroupSegments(ci) {
  const c = puzzle.categories[ci];
  const sgs = c.supergroups && c.supergroups.length ? c.supergroups : null;
  if (!sgs) return null;
  const segs = [];
  displayOrder(ci).forEach((b, pos) => {
    const gi = sgs.findIndex((s) => s.items.includes(c.items[b]));
    if (gi < 0) return;
    const last = segs[segs.length - 1];
    if (last && last.gi === gi) { last.size += 1; return; }
    segs.push({
      gi, label: sgs[gi].label,
      color: SUPER_COLORS[segs.length % SUPER_COLORS.length],
      start: pos, size: 1,
    });
  });
  return segs;
}

// Per display-position metadata for one axis: true item index `b`, display
// position `pos`, and `grpEdge` (a new group starts here, and it isn't the first).
function axisCells(ci) {
  const order = displayOrder(ci);
  const segs = groupSegments(ci);
  const starts = new Set();
  if (segs) for (const s of segs) if (s.start > 0) starts.add(s.start);
  return order.map((b, pos) => ({ b, pos, grpEdge: starts.has(pos) }));
}

function buildState() {
  manual = {};
  linked = {};
  history.reset(); // a fresh puzzle starts with an empty undo stack
  solvedElapsedMs = null;
  $("share-result").hidden = true; // a new attempt hasn't earned a result to share yet
  const cats = puzzle.categories;
  for (const [i, j] of pairs()) {
    const key = `${i}-${j}`;
    manual[key] = cats[i].items.map(() => cats[j].items.map(() => 0));
    const set = new Set();
    for (const row of puzzle.solution || []) { // the daily ships no solution
      const a = cats[i].items.indexOf(row[i]);
      const b = cats[j].items.indexOf(row[j]);
      set.add(`${a},${b}`);
    }
    linked[key] = set;
  }
}

function render() {
  $("p-name").textContent = puzzle.name;
  $("p-desc").textContent = puzzle.description;
  const tier = puzzle.rating ? puzzle.rating.ceiling : null;
  const tierNote = tier != null
    ? ` · <span title="hardest deduction technique needed (4 = advanced forward logic, 5 = proof by contradiction, 6 = nested what-if)">logic tier ${tier}</span>`
    : "";
  // measured band can differ from the request when a small grid can't reach the
  // asked-for tier — surface that honestly rather than silently downgrading.
  const reqNote = (puzzle.requested && puzzle.requested !== puzzle.difficulty)
    ? ` <span class="muted" title="you asked for ${puzzle.requested}; this grid could only reach ${puzzle.difficulty} — try more categories or items">(asked ${puzzle.requested})</span>`
    : "";
  const tail = DAILY
    ? `daily for <b>${dailyDate}</b>` // no seed: it would reproduce the answer key
    : BIG
      ? `big puzzle <code>${bigBundle ? bigBundle.id : ""}</code>`
      : `seed <code>${puzzle.seed}</code>`;
  $("p-meta").innerHTML =
    `${puzzle.categories.length} × ${puzzle.items} · <b>${puzzle.difficulty}</b>${reqNote}${tierNote} · ` +
    `${puzzle.clues.length} clues · ${tail}`;

  const ol = $("clues");
  ol.innerHTML = "";
  for (const c of puzzle.clues) {
    const li = document.createElement("li");
    li.textContent = c;
    li.tabIndex = 0;
    li.title = "Click to cross off";
    li.addEventListener("click", () => li.classList.toggle("done"));
    li.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); li.classList.toggle("done"); }
    });
    ol.appendChild(li);
  }

  renderAnswerKey();
  renderBoard();
  resetHintButton();
  setFeedback("");
  renderProgress();
  updateUndoUI();
}

// Solution table, shown only when printing (its own page, after the puzzle).
function renderAnswerKey() {
  if (!puzzle.solution) return; // the daily keeps its answer key server-side
  const body = $("answer-key-body");
  body.innerHTML = "";
  const table = document.createElement("table");
  table.className = "key-table";
  const head = document.createElement("tr");
  for (const c of puzzle.categories) head.appendChild(cell("th", c.name, ""));
  table.appendChild(head);
  for (const row of puzzle.solution) {
    const tr = document.createElement("tr");
    for (const label of row) tr.appendChild(cell("td", label, ""));
    table.appendChild(tr);
  }
  body.appendChild(table);
}

// --- Live solution table: each entity's items, derived from the user's ✓ links.
// Links are chained across grids (union-find over ✓ marks), so a ✓ anywhere that
// connects back to a row's anchor fills that cell in. When every cell is filled,
// the Check button lights up.
function computeEntityRows() {
  const cats = puzzle.categories;
  const k = cats.length, n = cats[0].items.length;
  const parent = Array.from({ length: k * n }, (_, x) => x);
  const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  for (const [i, j] of pairs()) {
    const M = manual[`${i}-${j}`];
    for (let a = 0; a < n; a++)
      for (let b = 0; b < n; b++)
        if (M[a][b] === 1) parent[find(i * n + a)] = find(j * n + b);
  }
  const rows = [];
  for (let a = 0; a < n; a++) {
    const root = find(a); // anchor: item a of category 0
    const row = [a];
    for (let c = 1; c < k; c++) {
      const hits = [];
      for (let i = 0; i < n; i++) if (find(c * n + i) === root) hits.push(i);
      row.push(hits.length === 1 ? hits[0] : null); // unique link only
    }
    rows.push(row);
  }
  return rows;
}

// The "solution so far" reconstructed from the player's links, plus how much of
// it is pinned down. `complete` means every entity's every category is resolved
// — the table is full — which is exactly when we accept the puzzle as done, even
// if not every ✓ was placed by hand (links inferred transitively count too).
function tableProgress() {
  const cats = puzzle.categories;
  const k = cats.length, n = cats[0].items.length;
  const rows = computeEntityRows();
  let filled = 0;
  for (const row of rows) for (let c = 1; c < k; c++) if (row[c] != null) filled++;
  const total = n * (k - 1);
  return { rows, filled, total, complete: total > 0 && filled === total };
}

function renderProgress() {
  const host = $("progress");
  host.hidden = false;
  const cats = puzzle.categories;
  const k = cats.length, n = cats[0].items.length;
  const { rows, filled, total, complete } = tableProgress();

  const table = document.createElement("table");
  table.className = "key-table progress-table";
  const head = document.createElement("tr");
  for (const c of cats) head.appendChild(cell("th", c.name, ""));
  table.appendChild(head);

  for (const row of rows) {
    const tr = document.createElement("tr");
    row.forEach((item, c) => {
      const label = item == null ? "" : cats[c].items[item];
      const td = cell("td", label, item == null ? "blank" : "");
      tr.appendChild(td);
    });
    table.appendChild(tr);
  }
  const body = $("progress-body");
  body.innerHTML = "";
  body.appendChild(table);

  $("progress-count").textContent = `${filled} / ${total}`;
  $("check").classList.toggle("ready", complete);
  $("progress-count").classList.toggle("done", complete);

  // Size the desktop sidebar so the table's (equal) columns fit without scroll.
  const sideW = Math.max(280, Math.min(500, k * 86 + 40));
  document.querySelector(".layout").style.setProperty("--side-w", sideW + "px");
}

// Pick the layout for the viewport, (re)build the DOM, and repaint marks from
// `manual` so state survives a desktop/mobile switch.
function renderBoard() {
  const host = $("grids");
  host.innerHTML = "";
  const cats = puzzle.categories;
  if (DESKTOP.matches) {
    host.className = "board-staircase";
    host.appendChild(renderStaircase(cats));
  } else {
    host.className = "board-pairwise";
    for (const [i, j] of pairs()) host.appendChild(renderGrid(i, j, cats));
  }
  for (const key of Object.keys(manual)) paintGrid(key);
  fitBoard();
}

// Fit the board to the viewport. Order matters: an initial cell fit gives the
// guild bands real dimensions; widening the left guild column changes the table
// width, so re-fit the cells around it; then shrink any label whose longest word
// still overflows its cell-bound dimension.
function fitBoard() {
  fitItemLabelBoxes();   // trim the row-label width + column-header height to their text
  fitCells();            // initial cell fit (gives guild bands real dims to measure)
  sizeGuildColumns();    // grow the left guild column to fit its rotated labels
  fitCells();            // re-fit cells around it — and guarantee the grid never scrolls
  fitGuildBands();       // shrink guild fonts (bound dim) + grow the top band height
}

// Trim the item-label boxes to the text they hold (capped at the standard size),
// so short labels don't leave a lopsided gap: the row-label column width and the
// rotated column-header band height each become min(default, longest + padding).
// Height doesn't affect table width; the (smaller) row-label width is set before
// fitCells so the cells get the freed space.
function fitItemLabelBoxes() {
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const ROWLAB = 4.75 * rem, HEADER = 6.25 * rem, PAD = 0.9 * rem;
  const range = document.createRange();
  document.querySelectorAll("table.staircase, table.grid").forEach((table) => {
    // row labels (horizontal): width is the limiting dimension. Measure the text
    // extent via a Range — th.row is right-aligned, so scrollWidth would just
    // report the box width and miss short labels.
    let w = 0;
    table.querySelectorAll("th.row").forEach((th) => {
      range.selectNodeContents(th);
      w = Math.max(w, range.getBoundingClientRect().width);
    });
    if (w) table.style.setProperty("--rowlab", Math.min(ROWLAB, Math.ceil(w + PAD)) + "px");
    // column labels (rotated): the header band height is the limiting dimension.
    // The vertical single-line text overflows the bottom, so scrollHeight reports
    // its true length regardless of the current band height.
    let h = 0;
    table.querySelectorAll("th.col span").forEach((sp) => { h = Math.max(h, sp.scrollHeight); });
    // + ~24px above the label and ~4px below it (the th's bottom padding), so the
    // rotated instance labels sit lower in the band rather than looking centred.
    if (h) table.style.setProperty("--header-h", Math.min(HEADER, Math.ceil(h) + 28) + "px");
  });
}

// Shrink the desktop staircase's cells so the whole grid ALWAYS fits the available
// width — the grid is the priority and must never need a horizontal scrollbar nor
// be cropped. Cells are capped at the default size (never enlarged); a final guard
// loop nudges the size down until the measured width actually fits, so rounding or
// overhead drift can never leave a sliver that triggers a scrollbar.
function fitCells() {
  if (!puzzle || !DESKTOP.matches) return;
  const host = $("grids");
  const table = host.querySelector("table.staircase");
  if (!table) return;
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const cols = (puzzle.categories.length - 1) * puzzle.categories[0].items.length;
  if (cols <= 0) return;
  const DEFAULT = 2.2 * rem, FLOOR = 0.5 * rem;
  table.style.setProperty("--cell", DEFAULT + "px");
  const avail = host.clientWidth - 2;
  if (table.scrollWidth <= avail) return;          // already fits — keep default size
  const overhead = table.scrollWidth - cols * DEFAULT; // labels + all borders (constant)
  let cell = Math.max(FLOOR, Math.min(DEFAULT, (avail - overhead) / cols));
  table.style.setProperty("--cell", cell + "px");
  let guard = 48;
  while (table.scrollWidth > avail && cell > 4 && guard-- > 0) {
    cell -= 1;
    table.style.setProperty("--cell", cell + "px");
  }
}

// Grow each table's (shared) left guild column to fit the widest rotated label at
// base font — the left band's non-disruptive (free) dimension. Measured on
// .gl-i.scrollWidth, the full content width even while the column is still narrow.
function sizeGuildColumns() {
  // Same clamp as the top band's height (fitGuildBands): a floor so short
  // rotated labels get the same breathing room the top band enjoys, a cap so
  // a heavily wrapped one can't blow the layout open (the font shrinker
  // handles what the cap pinches).
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const MINW = 1.6 * rem, MAXW = 4.5 * rem;
  document.querySelectorAll("table.staircase, table.grid").forEach((table) => {
    for (const [sel, colSel] of [
      ["th.sc-rowguild .gl-i", "col.sc-rowguild-col"],
      ["th.sc-rowsuper .gl-i", "col.sc-rowsuper-col"],
    ]) {
      const left = table.querySelectorAll(sel);
      if (!left.length) continue;
      let need = 0;
      left.forEach((el) => { el.style.removeProperty("--glfs"); need = Math.max(need, el.scrollWidth); });
      const colEl = table.querySelector(colSel);
      if (colEl && need) {
        colEl.style.width = Math.min(MAXW, Math.max(MINW, Math.ceil(need + 8))) + "px";
      }
    }
  });
}

// Final guild-label pass. The labels are absolutely placed, so this never affects
// table width. For each band: shrink the font only if a single word still overflows
// the cell-bound dimension (top: wider than its columns; left: taller than its
// rows). Then grow the top band's HEIGHT (its free dimension) to fit the wrap.
function fitGuildBands() {
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const MINF = 7; // px font floor; below this it's unreadable (full name is on hover)
  const shrink = (el, axis) => {
    el.style.removeProperty("--glfs");
    let size = parseFloat(getComputedStyle(el).fontSize);
    let guard = 28;
    const over = axis === "width"
      ? () => el.scrollWidth > el.clientWidth + 0.5
      : () => el.scrollHeight > el.clientHeight + 0.5;
    while (over() && size > MINF && guard-- > 0) {
      size -= 0.5;
      el.style.setProperty("--glfs", size + "px");
    }
  };
  document.querySelectorAll("table.staircase, table.grid").forEach((table) => {
    const side = [...table.querySelectorAll("th.sc-rowguild .gl-i, th.sc-rowsuper .gl-i")];
    side.forEach((el) => shrink(el, "height"));
    const top = [...table.querySelectorAll("th.sc-guild .gl-i, th.g-band .gl-i")];
    top.forEach((el) => shrink(el, "width"));
    const sideCols = [...table.querySelectorAll("col.sc-rowguild-col, col.sc-rowsuper-col")];
    if (!top.length && !sideCols.length) return;
    // ONE shared thickness for the top band's height and the side bands'
    // column widths — sized to whichever needs more — so the two axes read
    // as equals instead of the top (which must fit wrapped labels) running
    // visibly thicker than the side (whose text lies along its long axis).
    let needTop = 0;
    top.forEach((el) => { needTop = Math.max(needTop, el.scrollHeight + 6); });
    let needSide = 0;
    side.forEach((el) => { needSide = Math.max(needSide, el.scrollWidth + 8); });
    const MINT = 1.6 * rem, MAXT = 4.5 * rem;
    const t = Math.min(MAXT, Math.max(MINT, Math.ceil(Math.max(needTop, needSide))));
    if (top.length) table.style.setProperty("--gband-h", t + "px");
    sideCols.forEach((c) => { c.style.width = t + "px"; });
  });
}

function cell(tag, text, cls) {
  const el = document.createElement(tag);
  el.className = cls;
  el.textContent = text;
  return el;
}

function col(cls) {
  const c = document.createElement("col");
  c.className = cls;
  return c;
}

function vlabel(th, text) {
  th.title = text;
  const span = document.createElement("span"); // rotated vertically in CSS
  span.textContent = text;
  th.appendChild(span);
  return th;
}

// A six-digit #hex to an rgba() string. Used for the translucent guild tint so we
// don't rely on CSS color-mix (unsupported on some mobile browsers, where the
// band would otherwise render with no color at all).
function hexToRgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

// A guild-band label cell. The label lives in a `.gl` box with an inner `.gl-i`
// that wraps at word boundaries and is fitted by sizeGuildColumns/fitGuildBands
// so it never makes a data tile non-square. The left band rotates `.gl-i` via CSS
// to match the row-category label. Full text stays available on hover.
function guildCell(cls, label, color) {
  const th = cell("th", "", cls);
  th.style.setProperty("--gcolor", color);
  th.style.setProperty("--gcolor-soft", hexToRgba(color, 0.22));
  th.title = label;
  const gl = document.createElement("span");
  gl.className = "gl";
  const inner = document.createElement("span");
  inner.className = "gl-i";
  inner.textContent = label;
  gl.appendChild(inner);
  th.appendChild(gl);
  return th;
}

function dataCell(key, a, b, extra) {
  const td = cell("td", "", "cell" + (extra ? " " + extra : ""));
  td.dataset.key = key;
  td.dataset.a = a;
  td.dataset.b = b;
  td.addEventListener("click", onCellClick);
  return td;
}

// --- Mobile: separate pairwise blocks ---------------------------------------
function renderGrid(i, j, cats) {
  const key = `${i}-${j}`;
  const block = document.createElement("div");
  block.className = "grid-block";
  const title = document.createElement("h4");
  title.innerHTML = `<b>${cats[i].name}</b> × <b>${cats[j].name}</b>`;
  block.appendChild(title);

  // Items reorder so each group is contiguous; sub-dividers mark the splits and
  // a labelled guild band sits over each grouped axis (top + left). Labels are
  // clipped/shrink-to-fit so they never stretch a tile out of square.
  const colCells = axisCells(j);
  const rowCells = axisCells(i);
  const colSegs = groupSegments(j);
  const rowSegs = groupSegments(i);
  const colSuper = supergroupSegments(j);
  const rowSuper = supergroupSegments(i);
  // row-label (+ guild-label) (+ supergroup-label) column(s)
  const leftCols = 1 + (rowSegs ? 1 : 0) + (rowSuper ? 1 : 0);

  const table = document.createElement("table");
  table.className = "grid";
  const colgroup = document.createElement("colgroup");
  if (rowSuper) colgroup.appendChild(col("sc-rowsuper-col"));
  if (rowSegs) colgroup.appendChild(col("sc-rowguild-col"));
  colgroup.appendChild(col("rowlab-col"));
  colCells.forEach(() => colgroup.appendChild(col("cell-col")));
  table.appendChild(colgroup);

  // supergroup band over the column category — the outer tier of a nest
  if (colSuper) {
    const sh = document.createElement("tr");
    const s0 = cell("th", "", "corner");
    s0.colSpan = leftCols;
    sh.appendChild(s0);
    colSuper.forEach((seg, si) => {
      const th = guildCell("g-band g-superband" + (si > 0 ? " grp-left" : ""), seg.label, seg.color);
      th.colSpan = seg.size;
      sh.appendChild(th);
    });
    table.appendChild(sh);
  }

  // guild band over the column category (its members are now contiguous)
  if (colSegs) {
    const gh = document.createElement("tr");
    const c0 = cell("th", "", "corner");
    c0.colSpan = leftCols;
    gh.appendChild(c0);
    colSegs.forEach((seg, gi) => {
      const th = guildCell("g-band" + (gi > 0 ? " grp-left" : ""), seg.label, seg.color);
      th.colSpan = seg.size;
      gh.appendChild(th);
    });
    table.appendChild(gh);
  }

  const head = document.createElement("tr");
  const c1 = cell("th", "", "corner");
  c1.colSpan = leftCols;
  head.appendChild(c1);
  colCells.forEach(({ b, grpEdge }) =>
    head.appendChild(vlabel(cell("th", "", "col" + (grpEdge ? " grp-left" : "")), cats[j].items[b]))
  );
  table.appendChild(head);

  rowCells.forEach(({ b: a, pos: posI, grpEdge: grpEdgeI }) => {
    const tr = document.createElement("tr");
    if (rowSuper) {  // left-axis supergroup band (outer tier)
      const sseg = rowSuper.find((s) => s.start === posI);
      if (sseg) {
        const sth = guildCell("sc-rowsuper" + (sseg.start > 0 ? " grp-top" : ""), sseg.label, sseg.color);
        sth.rowSpan = sseg.size;
        tr.appendChild(sth);
      }
    }
    if (rowSegs) {  // left-axis guild band
      const seg = rowSegs.find((s) => s.start === posI);
      if (seg) {
        const gth = guildCell("sc-rowguild" + (seg.start > 0 ? " grp-top" : ""), seg.label, seg.color);
        gth.rowSpan = seg.size;
        tr.appendChild(gth);
      }
    }
    const rh = cell("th", cats[i].items[a], "row" + (grpEdgeI ? " grp-top" : ""));
    rh.title = cats[i].items[a];
    tr.appendChild(rh);
    colCells.forEach(({ b, grpEdge: grpEdgeJ }) => {
      const edge = ((grpEdgeJ ? "grp-left " : "") + (grpEdgeI ? "grp-top" : "")).trim();
      tr.appendChild(dataCell(key, a, b, edge));
    });
    table.appendChild(tr);
  });

  block.appendChild(table);
  return block;
}

// --- Desktop: one interlocked staircase grid --------------------------------
// Row blocks are categories 0..K-2 (top→bottom); column blocks are K-1..1 in
// REVERSE (left→right) — the conventional logic-grid layout, so the staircase
// notch falls on the lower-right. A block (row i, col j) exists only when i < j.
function renderStaircase(cats) {
  const K = cats.length;
  const N = cats[0].items.length;
  const colCats = [];
  for (let j = K - 1; j >= 1; j--) colCats.push(j);
  const rowCats = [];
  for (let i = 0; i < K - 1; i++) rowCats.push(i);

  // Thick category dividers sit BETWEEN blocks, not before the first one (the
  // row-label column / first row already separates it). Grouped categories get a
  // labelled, color-coded guild band over their (now contiguous) items plus thin
  // sub-dividers between groups — on BOTH axes (top band + left band). Labels are
  // fitted (see guildCell + sizeGuildColumns/fitGuildBands) so they never push
  // a cell out of square.
  const firstCol = colCats[0];
  const anyColGrouped = colCats.some((j) => catGroups(j));
  const anyRowGrouped = rowCats.some((i) => catGroups(i));
  const anyColSuper = colCats.some((j) => supergroupSegments(j));
  const anyRowSuper = rowCats.some((i) => supergroupSegments(i));
  // cat-label (+ supergroup) (+ guild) + row-label
  const leftCols = 2 + (anyRowGrouped ? 1 : 0) + (anyRowSuper ? 1 : 0);

  const table = document.createElement("table");
  table.className = "staircase";

  const cg = document.createElement("colgroup");
  cg.appendChild(col("sc-catcol"));
  if (anyRowSuper) cg.appendChild(col("sc-rowsuper-col"));
  if (anyRowGrouped) cg.appendChild(col("sc-rowguild-col"));
  cg.appendChild(col("sc-rowlab-col"));
  colCats.forEach(() => cats[0].items.forEach(() => cg.appendChild(col("cell-col"))));
  table.appendChild(cg);

  // header row 1: column-category names
  const h1 = document.createElement("tr");
  const corner = cell("th", "", "sc-corner");
  corner.colSpan = leftCols;
  corner.rowSpan = 2 + (anyColGrouped ? 1 : 0) + (anyColSuper ? 1 : 0);
  h1.appendChild(corner);
  for (const j of colCats) {
    const th = cell("th", cats[j].name, "sc-colcat" + (j !== firstCol ? " blk-left" : ""));
    th.colSpan = N;
    // centre over whichever band rows this category doesn't fill
    th.rowSpan = 1
      + (anyColSuper && !supergroupSegments(j) ? 1 : 0)
      + (anyColGrouped && !catGroups(j) ? 1 : 0);
    h1.appendChild(th);
  }
  table.appendChild(h1);

  // header row 1a: supergroup band — the outer tier of a nested hierarchy.
  if (anyColSuper) {
    const hs = document.createElement("tr");
    for (const j of colCats) {
      const segs = supergroupSegments(j);
      if (!segs) continue;
      const catEdge = j !== firstCol ? " blk-left" : "";
      segs.forEach((seg, si) => {
        const th = guildCell("sc-guild sc-superband" + (si === 0 ? catEdge : " grp-left"), seg.label, seg.color);
        th.colSpan = seg.size;
        hs.appendChild(th);
      });
    }
    table.appendChild(hs);
  }

  // header row 1b: guild band — a labelled tinted cell per group. Ungrouped
  // categories skip it (their name cell rowspans down into this row instead), so
  // there's no empty filler and no color bleeds under them.
  if (anyColGrouped) {
    const hg = document.createElement("tr");
    for (const j of colCats) {
      const segs = groupSegments(j);
      if (!segs) continue;
      const catEdge = j !== firstCol ? " blk-left" : "";
      segs.forEach((seg, gi) => {
        const th = guildCell("sc-guild" + (gi === 0 ? catEdge : " grp-left"), seg.label, seg.color);
        th.colSpan = seg.size;
        hg.appendChild(th);
      });
    }
    table.appendChild(hg);
  }

  // header row 2: column item labels (vertical), in group display order
  const h2 = document.createElement("tr");
  for (const j of colCats) {
    axisCells(j).forEach(({ b, pos, grpEdge }) => {
      const edge = pos === 0 ? (j !== firstCol ? " blk-left" : "") : (grpEdge ? " grp-left" : "");
      h2.appendChild(vlabel(cell("th", "", "col" + edge), cats[j].items[b]));
    });
  }
  table.appendChild(h2);

  // body
  for (const i of rowCats) {
    const rowSegs = groupSegments(i);
    const rowSuper = supergroupSegments(i);
    axisCells(i).forEach(({ b: a, pos: posI, grpEdge: grpEdgeI }) => {
      const tr = document.createElement("tr");
      const horizTop = posI === 0 ? (i > 0 ? " blk-top" : "") : (grpEdgeI ? " grp-top" : "");
      if (posI === 0) {
        const catTh = vlabel(cell("th", "", "sc-rowcat" + (i > 0 ? " blk-top" : "")), cats[i].name);
        catTh.rowSpan = N;
        // span whichever band columns this category doesn't fill
        catTh.colSpan = 1
          + (anyRowSuper && !rowSuper ? 1 : 0)
          + (anyRowGrouped && !rowSegs ? 1 : 0);
        tr.appendChild(catTh);
      }
      if (rowSuper) {  // left-axis supergroup band: the outer tier of a nest
        const sseg = rowSuper.find((s) => s.start === posI);
        if (sseg) {
          const sEdge = sseg.start === 0 ? (i > 0 ? " blk-top" : "") : " grp-top";
          const sth = guildCell("sc-rowsuper" + sEdge, sseg.label, sseg.color);
          sth.rowSpan = sseg.size;
          tr.appendChild(sth);
        }
      }
      if (rowSegs) {  // left-axis guild band: a rotated label per group
        const seg = rowSegs.find((s) => s.start === posI);
        if (seg) {
          const gEdge = seg.start === 0 ? (i > 0 ? " blk-top" : "") : " grp-top";
          const gth = guildCell("sc-rowguild" + gEdge, seg.label, seg.color);
          gth.rowSpan = seg.size;
          tr.appendChild(gth);
        }
      }
      const rh = cell("th", cats[i].items[a], "row" + horizTop);
      rh.title = cats[i].items[a];
      tr.appendChild(rh);
      for (const j of colCats) {
        axisCells(j).forEach(({ b, pos: posJ, grpEdge: grpEdgeJ }) => {
          const vert = posJ === 0 ? (j !== firstCol ? "blk-left " : "") : (grpEdgeJ ? "grp-left " : "");
          const edge = (vert + horizTop.trim()).trim();
          if (i < j) {
            tr.appendChild(dataCell(`${i}-${j}`, a, b, edge));
          } else {
            tr.appendChild(cell("td", "", ("void " + edge).trim()));
          }
        });
      }
      table.appendChild(tr);
    });
  }

  const wrap = document.createElement("div");
  wrap.className = "staircase-wrap";
  wrap.appendChild(table);
  return wrap;
}

function cellEl(key, a, b) {
  return document.querySelector(
    `td.cell[data-key="${key}"][data-a="${a}"][data-b="${b}"]`
  );
}

// Grid-interaction logic (derive / nextState / lineHasEqElsewhere) lives in the
// shared, unit-tested module logic.js, exposed here as the global `LG`.
function paintGrid(key) {
  const { display, lit } = LG.derive(manual[key]);
  for (let a = 0; a < display.length; a++) {
    for (let b = 0; b < display[a].length; b++) {
      const td = cellEl(key, a, b);
      if (!td) continue;
      const state = display[a][b];
      td.textContent = STATES[state];
      td.classList.toggle("yes", state === 1);
      td.classList.toggle("no", state === 2);
      td.classList.toggle("lit", lit[a][b]);
      td.classList.remove("right", "wrong");
    }
  }
}

function onCellClick(e) {
  const td = e.currentTarget;
  const key = td.dataset.key;
  const a = +td.dataset.a;
  const b = +td.dataset.b;
  recordMutation(
    () => { manual[key][a][b] = LG.nextState(manual[key], a, b); },
    `${key}-${a}-${b}`, // same cell within COALESCE_MS merges (double-click = one step)
  );
  paintGrid(key);
  afterEdit();
}

function clearHighlights() {
  document.querySelectorAll("td.cell.right, td.cell.wrong").forEach((td) => {
    td.classList.remove("right", "wrong");
  });
}

function puzzleShapeLabel() {
  return `${puzzle.categories.length}×${puzzle.items} ${puzzle.difficulty}`;
}

// Shared by free-play and big (DAILY has its own share, further down — it has
// no user-chosen seed/theme to link back to).
function sharePuzzle() {
  if (!puzzle) return; // free-play's button lives in the always-visible controls bar
  shareOrCopy({
    text: `${puzzle.name} — a ${puzzleShapeLabel()} logic grid puzzle`,
    url: BIG ? bigShareUrl() : location.href,
  });
}

function shareResult() {
  shareOrCopy({
    text: `Solved "${puzzle.name}" (${puzzleShapeLabel()}) in ${fmtTime(solvedElapsedMs)} — Logic Grid Puzzles`,
    url: BIG ? bigShareUrl() : location.href,
  });
}

function check() {
  if (DAILY) { dailySubmit(); return; } // no per-cell feedback on the competitive board
  clearHighlights();
  // Flag any mark that contradicts the truth (a ✓ on a non-link, or a ✗ on a
  // real link). The puzzle is done once the *table* is fully reconstructed — you
  // needn't have placed every ✓ by hand — so completion is judged from the
  // solution-so-far, not from counting explicit links on the board.
  let mistakes = 0;
  for (const [i, j] of pairs()) {
    const key = `${i}-${j}`;
    const { display } = LG.derive(manual[key]);
    for (let a = 0; a < display.length; a++) {
      for (let b = 0; b < display[a].length; b++) {
        const truth = linked[key].has(`${a},${b}`);
        const state = display[a][b];
        const td = cellEl(key, a, b);
        if (!td) continue;
        if (state === 1 && truth) td.classList.add("right");
        else if (state === 1 && !truth) { td.classList.add("wrong"); mistakes++; }
        else if (state === 2 && truth) { td.classList.add("wrong"); mistakes++; }
      }
    }
  }
  const { filled, total, complete } = tableProgress();
  const remaining = total - filled;
  if (mistakes === 0 && complete) {
    const first = !timerDone; // only the checking run that solves it reports the stats
    if (first && timerStart) {
      solvedElapsedMs = performance.now() - timerStart;
      const steps = history.size();
      const stats =
        `<b>${fmtTime(solvedElapsedMs)}</b>` +
        ` · <b>${steps}</b> step${steps === 1 ? "" : "s"}`;
      stopTimer(true);
      setFeedback(`<b>Solved!</b> The whole table checks out — ${stats}.`, "good");
    } else {
      stopTimer(true);
      setFeedback("<b>Solved!</b> The whole table checks out.", "good");
    }
    $("share-result").hidden = false;
  } else if (mistakes === 0) {
    setFeedback(`No mistakes so far — <b>${remaining}</b> more to work out.`, "warn");
  } else {
    const bits = [`<b>${mistakes}</b> mistake${mistakes > 1 ? "s" : ""} (highlighted)`];
    if (remaining > 0) bits.push(`<b>${remaining}</b> still to work out`);
    setFeedback(bits.join(" · "), "bad");
  }
}

function reveal() {
  if (DAILY) return; // the daily has no reveal (and no solution client-side)
  clearHighlights();
  resetHintButton();
  for (const [i, j] of pairs()) {
    const key = `${i}-${j}`;
    const M = manual[key];
    for (let a = 0; a < M.length; a++) {
      for (let b = 0; b < M[a].length; b++) {
        M[a][b] = linked[key].has(`${a},${b}`) ? 1 : 2;
      }
    }
    paintGrid(key);
  }
  stopTimer(false); // revealing the answer ends the run (no solve time earned)
  history.reset();  // the run is over — nothing left to undo back into
  updateUndoUI();
  setFeedback("Solution revealed.", "");
  renderProgress();
}

function clearGrids() {
  clearHighlights();
  resetHintButton();
  // Clear is a "restart this puzzle's work": wipe the board and zero the step
  // count (history.size()), so a solve after Clear reports only the moves made
  // since. Because the step count *is* the undo-stack depth, this also empties
  // undo/redo — Clear can't be taken back. The timer is left running: it measures
  // time since the puzzle loaded, so clearing your marks doesn't stop the clock.
  for (const key of Object.keys(manual)) {
    const M = manual[key];
    for (let a = 0; a < M.length; a++) M[a].fill(0);
  }
  history.reset();
  updateUndoUI();
  for (const key of Object.keys(manual)) paintGrid(key);
  // Also un-cross any clues the player struck through on the left.
  document.querySelectorAll("#clues li.done").forEach((li) => li.classList.remove("done"));
  setFeedback("");
  renderProgress();
}

// A persistent status bar with a reserved height (CSS), so messages never shift
// the grid below. With no message it shows a muted default tip rather than
// collapsing.
const DEFAULT_FEEDBACK = DAILY
  ? "Click a cell to cycle ✓ / ✗. Fill the whole table, then <b>Submit</b> — the clock is running."
  : "Click a cell to cycle ✓ / ✗. Press <b>Hint</b> for the next logical step.";
function setFeedback(html, cls) {
  const el = $("feedback");
  const empty = !html;
  el.className = "feedback" + (empty ? " empty" : "") + (cls ? " " + cls : "");
  el.innerHTML = empty ? DEFAULT_FEEDBACK : html;
}

// --- Hints: ask the server for the next single explained deduction ----------
// The board the player can "see" — derived ✓/✗ per pair (auto-× included), so
// the server skips anything they've already worked out. Matches a hint's value
// encoding: 0 blank · 1 link (=) · 2 no-link (×).
function currentKnown() {
  const out = {};
  for (const key of Object.keys(manual)) out[key] = LG.derive(manual[key]).display;
  return out;
}

function hintHtml(step, placed) {
  const tail = placed
    ? `<span class="hint-placed">— placed ✓</span>`
    : `<span class="hint-cta">Tap the glowing cell or “Reveal tile” to fill it in.</span>`;
  let chain = "";
  if (Array.isArray(step.chain) && step.chain.length) {
    const items = step.chain.map((s) => `<li>${escapeHtml(s)}</li>`).join("");
    chain =
      `<details class="hint-chain"><summary>Show the steps to the contradiction</summary>` +
      `<ol>${items}</ol></details>`;
  }
  return (
    `<span class="hint-tier">${step.tier_name}</span>` +
    `<span class="hint-text">${escapeHtml(step.text)}</span> ${tail}${chain}`
  );
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function applyHint(step) {
  recordMutation(() => {
    const M = manual[step.key];
    if (step.value === 1) {
      // a confirmed link clears any (mistaken) link the player had in its row/col
      for (let b = 0; b < M[step.a].length; b++) if (M[step.a][b] === 1) M[step.a][b] = 0;
      for (let a = 0; a < M.length; a++) if (M[a][step.b] === 1) M[a][step.b] = 0;
    }
    M[step.a][step.b] = step.value;
  });
  paintGrid(step.key);
  const td = cellEl(step.key, step.a, step.b);
  if (td) { td.classList.add("hint-flash"); setTimeout(() => td.classList.remove("hint-flash"), 800); }
}

// Resets only the pending-hint UI (the glowing target + button label). The
// feedback banner is managed separately by the caller.
function resetHintButton() {
  pendingHint = null;
  document.querySelectorAll("td.cell.hint-target").forEach((td) => td.classList.remove("hint-target"));
  $("hint").textContent = "Hint";
}

async function hint() {
  if (!puzzle || DAILY) return; // hints would need the seed the daily withholds
  if (pendingHint) {              // second click reveals the tile we explained
    const step = pendingHint;
    resetHintButton();
    applyHint(step);
    setFeedback(hintHtml(step, true), "hint");
    clearHighlights();
    renderProgress();
    return;
  }
  const btn = $("hint");
  btn.disabled = true;
  setFeedback("");
  try {
    // Big puzzles ship their full solve path in the bundle, so the next hint
    // is found client-side: the first step the player hasn't already made.
    const step = BIG ? bigNextHint() : await postJSON("/api/hint", {
      seed: puzzle.seed,
      difficulty: puzzle.requested,
      items: puzzle.items,
      categories: puzzle.n_categories,
      theme: puzzle.theme,
      ...(puzzle.theme === CUSTOM_KEY && puzzleDoc ? { theme_doc: puzzleDoc } : {}),
      known: currentKnown(),
    });
    if (step.done) {
      setFeedback("Every remaining tile follows from what you've got — you've effectively cracked it. Hit <b>Check</b>!", "good");
      return;
    }
    pendingHint = step;
    setFeedback(hintHtml(step, false), "hint");
    btn.textContent = "Reveal tile";
    const td = cellEl(step.key, step.a, step.b);
    if (td) { td.classList.add("hint-target"); td.scrollIntoView({ block: "nearest", inline: "nearest" }); }
  } catch (err) {
    setFeedback(escapeHtml(err.message), "bad");
  } finally {
    btn.disabled = false;
  }
}

// More categories allow fewer items (generation must stay fast) — mirror the
// server's cap (logicgrid/webapi.py _MAX_ITEMS_BY_K) so the Items dropdown only
// offers sizes the server will actually honour, instead of silently downgrading.
const MAX_ITEMS_BY_K = { 3: 5, 4: 4, 5: 4 };
function syncItemOptions() {
  const maxN = MAX_ITEMS_BY_K[+$("categories").value] || 5;
  const sel = $("items");
  for (const opt of sel.options) opt.disabled = +opt.value > maxN;
  if (+sel.value > maxN) sel.value = String(maxN);
}

// Populate the theme picker from the server catalogue.
async function loadThemes() {
  try {
    const data = await fetchJSON("/api/puzzle?themes=1");
    const sel = $("theme");
    sel.innerHTML = "";
    for (const t of data.themes) {
      const opt = document.createElement("option");
      opt.value = t.key;
      opt.textContent = t.name;
      opt.title = t.description;
      sel.appendChild(opt);
    }
  } catch (err) {
    // leave the picker empty; generation falls back to the server default theme
  }
  ensureCustomOption();
}

// --- Color-blind palette toggle. A display-only preference (no re-generation),
// persisted in localStorage and applied via a `body.cblind` class — see the
// `body.cblind` block in style.css. Wrapped in try/catch so a blocked
// localStorage (private mode) degrades to a non-persisted toggle, never a crash.
const CBLIND_KEY = "lg.colorblind";
function applyColorblind(on) {
  document.body.classList.toggle("cblind", on);
}
function initColorblind() {
  let on = false;
  try { on = localStorage.getItem(CBLIND_KEY) === "1"; } catch (e) { /* no storage */ }
  $("cblind").checked = on;
  applyColorblind(on);
}
$("cblind").addEventListener("change", (e) => {
  const on = e.target.checked;
  applyColorblind(on);
  try { localStorage.setItem(CBLIND_KEY, on ? "1" : "0"); } catch (e) { /* no storage */ }
});

// --- Daily challenge (used only when DAILY) ----------------------------------
// The server is the referee: the payload carries no solution, a signed session
// token pins the official start time, and a solve is a two-phase exchange —
// "finish" (verify the table, freeze the server-measured time) then "claim"
// (attach a display name), so typing a name never costs leaderboard time.
let dailyDate = null;   // "YYYY-MM-DD" of the loaded puzzle
let dailyToken = null;  // signed session token from GET /api/daily
let dailyResult = null; // {time_ms, result_token} after a verified solve
let dailyRank = null;   // set once claimSpot() succeeds; upgrades the share text

// No seed/theme to link back to (the daily is the same puzzle for everyone),
// so this only ever shares the *result* — time, and rank once claimed.
function shareDailyResult() {
  const rankBit = dailyRank ? `, rank #${dailyRank} today` : "";
  shareOrCopy({
    text: `Solved the Logic Grid Puzzles daily (${puzzleShapeLabel()}) in ${fmtTime(dailyResult.time_ms)}${rankBit}`,
    url: `${location.origin}/daily`,
  });
}

const playedKey = () => `lg.daily.played.${dailyDate}`;
function playedName() {
  try { return localStorage.getItem(playedKey()); } catch (e) { return null; }
}
function markPlayed(name) {
  try { localStorage.setItem(playedKey(), name); } catch (e) { /* no storage */ }
}

const NAME_STORE = "lg.daily.name";
let boardAvailable = false; // GET /api/daily returned a leaderboard (store is up)

function renderLeaderboard(list, ownRank) {
  const ol = $("board-list");
  ol.innerHTML = "";
  const rows = list || [];
  $("board-empty").hidden = rows.length > 0;
  rows.forEach((r, i) => {
    const li = document.createElement("li");
    if (ownRank === i + 1) li.className = "own";
    const name = document.createElement("span");
    name.className = "board-name";
    name.textContent = r.name;
    const time = document.createElement("span");
    time.className = "board-time";
    time.textContent = fmtTime(r.time_ms);
    li.appendChild(name);
    li.appendChild(time);
    li.title = r.steps ? `${r.steps} steps` : "";
    ol.appendChild(li);
  });
}

// Submit flow (bound to the repurposed Check button). All-or-nothing: the
// server only says correct / not correct — mistake locations would leak the
// answer key one probe at a time.
async function dailySubmit() {
  if (!puzzle || !dailyToken) return;
  if (dailyResult) { showClaim(); return; } // solved already — just re-open the name form
  const prog = tableProgress();
  if (!prog.complete) {
    setFeedback(`Fill in the whole solution table first — <b>${prog.total - prog.filled}</b> to go. The daily is checked all-or-nothing.`, "warn");
    return;
  }
  const labels = prog.rows.map((row) => row.map((it, c) => puzzle.categories[c].items[it]));
  const btn = $("check");
  btn.disabled = true;
  pauseTimerDisplay(); // the official clock stops on arrival at the server
  try {
    const res = await postJSON("/api/daily", {
      action: "finish",
      token: dailyToken,
      rows: labels,
      steps: history.size(),
    });
    if (!res.correct) {
      resumeTimerDisplay();
      setFeedback("Not quite — at least one placement is off. Recheck your deductions and submit again (the clock keeps running).", "bad");
      return;
    }
    dailyResult = res;
    stopTimer(true);
    $("timer").textContent = fmtTime(res.time_ms); // sync the readout to the official time
    $("share-result").hidden = false;
    if (playedName()) {
      setFeedback(`<b>Correct</b> in ${fmtTime(res.time_ms)} — but you've already posted a time today, so the board stands.`, "good");
    } else {
      setFeedback(`<b>Solved!</b> Official time <b>${fmtTime(res.time_ms)}</b> — enter a name to join the board.`, "good");
      showClaim();
    }
  } catch (err) {
    resumeTimerDisplay(); // the submission never landed — still on the clock
    setFeedback(escapeHtml(err.message), "bad");
  } finally {
    btn.disabled = false;
  }
}

function showClaim() {
  if (playedName()) return;
  if (!boardAvailable) {
    setFeedback("Solved and verified — but the leaderboard isn't available right now.", "warn");
    return;
  }
  $("claim-time").innerHTML = `Verified solve — official time <b>${fmtTime(dailyResult.time_ms)}</b>.`;
  $("claim-error").hidden = true;
  try { $("claim-name").value = localStorage.getItem(NAME_STORE) || $("claim-name").value; } catch (e) { /* fine */ }
  $("claim").hidden = false;
  $("claim-name").focus();
}

async function claimSpot() {
  const name = $("claim-name").value.trim();
  const errEl = $("claim-error");
  errEl.hidden = true;
  const btn = $("claim-submit");
  btn.disabled = true;
  try {
    const res = await postJSON("/api/daily", {
      action: "claim",
      result_token: dailyResult.result_token,
      name,
    });
    markPlayed(res.name);
    try { localStorage.setItem(NAME_STORE, res.name); } catch (e) { /* fine */ }
    dailyRank = res.rank || null;
    $("claim").hidden = true;
    renderLeaderboard(res.leaderboard, res.rank);
    const spot = res.rank ? `<b>#${res.rank}</b> today` : "On the board";
    setFeedback(`${spot} — ${fmtTime(res.time_ms)}. Come back tomorrow for a fresh one!`, "good");
  } catch (err) {
    errEl.textContent = err.message; // e.g. a rejected name, or a replayed token
    errEl.hidden = false;
  } finally {
    btn.disabled = false;
  }
}

// Ticking countdown to the next puzzle (the day rolls at UTC midnight). When
// it lands, offer a reload link rather than reloading — someone mid-solve at
// midnight shouldn't have the board yanked out from under them.
let countdownInterval = null;
function startDailyCountdown() {
  const [y, m, d] = dailyDate.split("-").map(Number);
  const next = Date.UTC(y, m - 1, d + 1); // midnight after the puzzle's day
  const el = $("daily-countdown");
  const tick = () => {
    const left = next - Date.now();
    if (left <= 0) {
      el.innerHTML = `new puzzle is ready — <a href="/daily">load it</a>`;
      clearInterval(countdownInterval);
      countdownInterval = null;
      return;
    }
    const s = Math.floor(left / 1000);
    const two = (n) => String(n).padStart(2, "0");
    el.textContent =
      `Next puzzle in ${two(Math.floor(s / 3600))}:${two(Math.floor((s % 3600) / 60))}:${two(s % 60)}`;
  };
  if (countdownInterval) clearInterval(countdownInterval);
  tick();
  countdownInterval = setInterval(tick, 1000);
}

async function loadDaily() {
  $("error").hidden = true;
  $("loading").hidden = false;
  $("loading").textContent = "Fetching today's puzzle…";
  try {
    const data = await fetchJSON("/api/daily");
    dailyDate = data.date;
    dailyToken = data.token;
    // null board = store unavailable (an empty day is [] — still a board)
    boardAvailable = data.leaderboard !== null && data.leaderboard !== undefined;
    puzzle = data.puzzle;
    $("daily-info").textContent = `Puzzle for ${data.date} (UTC)`;
    $("board-date").textContent = data.date;
    startDailyCountdown();
    buildState();
    render();
    $("puzzle").hidden = false;
    fitBoard();
    startTimer(); // display only — the official clock started server-side
    renderLeaderboard(data.leaderboard);
    const prior = playedName();
    if (prior) {
      setFeedback(`You've already posted a time today as <b>${escapeHtml(prior)}</b> — replays are just for fun.`, "warn");
    }
  } catch (err) {
    $("error").textContent = err.message;
    $("error").hidden = false;
  } finally {
    $("loading").hidden = true;
  }
}

if (DAILY) {
  $("claim-submit").addEventListener("click", claimSpot);
  $("claim-name").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); claimSpot(); }
  });
}

// --- Big puzzles (used only when BIG) -----------------------------------------
// Bundles are static JSON: every compatible theme's full rendering (categories,
// clues, solution, solve path) of ONE logical puzzle. Swapping theme swaps the
// words, not the logic — the board's indices are identical, so marks, undo
// history, and progress survive the swap.
let bigIndex = null;    // index.json entries
let bigBundle = null;   // the loaded bundle (all theme renderings)
let bigThemeKey = null; // which rendering is on screen
const BIG_THEME_STORE = "lg.big.theme";

function bigPayload(key) {
  const t = bigBundle.themes[key];
  return {
    ...t,
    theme: key,
    items: bigBundle.items,
    n_categories: bigBundle.categories,
    difficulty: bigBundle.difficulty,
    requested: bigBundle.requested,
    rating: bigBundle.rating,
  };
}

// The bundle carries the full ordered solve path; the next hint is simply the
// first step the player hasn't already made correctly (mirrors the server's
// next_hint, with zero network).
function bigNextHint() {
  const known = currentKnown();
  for (const step of bigBundle.themes[bigThemeKey].hints) {
    const cur = known[step.key];
    if (cur && cur[step.a] && cur[step.a][step.b] === step.value) continue;
    return step;
  }
  return { done: true };
}

// A shared big-puzzle link: the existing #id deep link (openBigPuzzle already
// maintains it) plus the viewer's current theme as a query param, so a friend
// opens the same story — still free to swap it, same as any other visit.
function bigShareUrl() {
  const u = new URL(location.href);
  u.search = new URLSearchParams({ theme: bigThemeKey }).toString();
  return u.toString();
}

function setBigTheme(key, { fresh } = {}) {
  bigThemeKey = key;
  $("big-theme").value = key;
  try { localStorage.setItem(BIG_THEME_STORE, key); } catch (e) { /* fine */ }
  puzzle = bigPayload(key);
  if (fresh) buildState(); // a new puzzle wipes marks; a theme swap keeps them
  resetHintButton();       // a pending hint's text belongs to the old wording
  render();
}

// --- The catalog: difficulty tabs -> size layers -> puzzle tiles --------------
const BIG_BAND_STORE = "lg.big.band";
const BIG_FILTER_STORE = "lg.big.filter";
const BIG_BANDS = ["normal", "hard", "mega", "giga", "tera"];
let bigById = {};        // id -> index entry
let bigThemeFilter = ""; // catalog filter: only puzzles compatible with this theme

function bigShowCatalog() {
  $("puzzle").hidden = true;
  $("big-back").hidden = true;
  $("big-theme-wrap").hidden = true;
  $("big-filter-wrap").hidden = false;
  $("cblind-wrap").hidden = true; // colorblind mode only matters once a grid is on screen
  $("catalog").hidden = false;
  stopTimer(false);
  if (location.hash) window.history.replaceState(null, "", location.pathname); // pre-existing shadowing bug: `history` is the undo/redo stack here
}

function bigVisible() {
  return bigThemeFilter
    ? bigIndex.filter((e) => bigThemeFilter in e.themes)
    : bigIndex;
}

function bigActiveBand() {
  const pool = bigVisible();
  const present = BIG_BANDS.filter((b) => pool.some((e) => e.difficulty === b));
  let band = null;
  try { band = localStorage.getItem(BIG_BAND_STORE); } catch (e) { /* fine */ }
  return present.includes(band) ? band : present[0];
}

function bigTile(e) {
  const tile = document.createElement("button");
  tile.type = "button";
  tile.className = "tile" + (e.adjusted ? " adjusted" : "");
  const num = document.createElement("span");
  num.className = "tile-id";
  num.textContent = "#" + e.id.split("-").pop();
  tile.appendChild(num);

  const tags = document.createElement("span");
  tags.className = "tile-tags";
  const tag = (text, cls) => {
    const s = document.createElement("span");
    s.className = "tag" + (cls ? " " + cls : "");
    s.textContent = text;
    tags.appendChild(s);
    return s;
  };
  if (e.adjusted) {
    // short marker; the "same solution:" row below carries the origin band.
    // Full context on hover.
    const parent = bigById[e.family];
    const t = tag("downtuned", "tag-adjusted");
    if (parent) t.title = `tuned down from ${parent.difficulty} ${parent.id}`;
  }
  if (e.nested) tag("nested groups");
  if (e.group_categories) {
    tag(`${e.group_categories} group ${e.group_categories === 1 ? "category" : "categories"}`);
  }
  if (e.sequential_categories) tag(`${e.sequential_categories} sequential`);
  tile.appendChild(tags);

  if (e.siblings && e.siblings.length) {
    const kin = document.createElement("span");
    kin.className = "tile-kin";
    kin.appendChild(document.createTextNode("same solution: "));
    e.siblings.forEach((sid, i) => {
      if (i) kin.appendChild(document.createTextNode(" · "));
      const s = bigById[sid];
      const a = document.createElement("a");
      a.href = "#" + sid;
      a.textContent = s ? s.difficulty + (s.adjusted ? " (adj.)" : "") : sid;
      a.title = sid;
      a.addEventListener("click", (ev) => { ev.stopPropagation(); ev.preventDefault(); openBigPuzzle(sid); });
      kin.appendChild(a);
    });
    tile.appendChild(kin);
  }
  tile.addEventListener("click", () => openBigPuzzle(e.id));
  return tile;
}

function renderCatalog() {
  const pool = bigVisible();
  const active = bigActiveBand();
  const tabs = $("band-tabs");
  tabs.innerHTML = "";
  if (!pool.length) {
    $("catalog-body").innerHTML = "";
    return;
  }
  for (const band of BIG_BANDS) {
    const count = pool.filter((e) => e.difficulty === band).length;
    if (!count) continue;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "band-tab" + (band === active ? " active" : "");
    btn.textContent = `${band} (${count})`;
    btn.addEventListener("click", () => {
      try { localStorage.setItem(BIG_BAND_STORE, band); } catch (e) { /* fine */ }
      renderCatalog();
    });
    tabs.appendChild(btn);
  }

  const body = $("catalog-body");
  body.innerHTML = "";
  const entries = pool.filter((e) => e.difficulty === active);
  const shapes = [...new Set(entries.map((e) => `${e.categories}x${e.items}`))]
    .sort((a, b2) => {
      const [ac, ai] = a.split("x").map(Number);
      const [bc, bi] = b2.split("x").map(Number);
      return ac * ai - bc * bi || ac - bc;
    });
  for (const shape of shapes) {
    const [c, n] = shape.split("x");
    const h = document.createElement("h3");
    h.className = "layer-head";
    h.textContent = `${c} categories × ${n} items`;
    body.appendChild(h);
    const grid = document.createElement("div");
    grid.className = "tiles";
    entries
      .filter((e) => `${e.categories}x${e.items}` === shape)
      .sort((a, b2) => a.id.localeCompare(b2.id))
      .forEach((e) => grid.appendChild(bigTile(e)));
    body.appendChild(grid);
  }
}

async function openBigPuzzle(id, { theme } = {}) {
  $("error").hidden = true;
  $("loading").hidden = false;
  $("loading").textContent = "Fetching the puzzle…";
  $("puzzle").hidden = true;
  $("catalog").hidden = true;
  try {
    bigBundle = await fetchJSON(`/big/${encodeURIComponent(id)}.json`);
    const sel = $("big-theme");
    sel.innerHTML = "";
    for (const [key, t] of Object.entries(bigBundle.themes)) {
      const opt = document.createElement("option");
      opt.value = key;
      opt.textContent = t.name;
      sel.appendChild(opt);
    }
    let key = bigBundle.default_theme;
    try {
      const pref = localStorage.getItem(BIG_THEME_STORE);
      if (pref && bigBundle.themes[pref]) key = pref;
    } catch (e) { /* fine */ }
    // an active catalog filter is the strongest statement of theme intent...
    if (bigThemeFilter && bigBundle.themes[bigThemeFilter]) key = bigThemeFilter;
    // ...except an explicit shared link, which beats even that.
    if (theme && bigBundle.themes[theme]) key = theme;
    if (location.hash.slice(1) !== id) location.hash = id; // shareable deep link
    setBigTheme(key, { fresh: true });
    $("big-back").hidden = false;
    $("big-theme-wrap").hidden = false;
    $("big-filter-wrap").hidden = true;
    $("cblind-wrap").hidden = false;
    $("puzzle").hidden = false;
    fitBoard();
    startTimer();
  } catch (err) {
    $("error").textContent = err.message;
    $("error").hidden = false;
    $("catalog").hidden = false;
  } finally {
    $("loading").hidden = true;
  }
}

async function loadBig() {
  let themeMeta = null;
  try {
    const data = await fetchJSON("/big/index.json");
    // the index is {themes, puzzles}; tolerate the older bare array while
    // long-running generation lanes may still rewrite it in that shape
    bigIndex = Array.isArray(data) ? data : data.puzzles;
    if (!Array.isArray(data)) themeMeta = data.themes;
  } catch (err) {
    bigIndex = [];
  }
  $("loading").hidden = true;
  if (!bigIndex.length) {
    $("error").textContent = "No big puzzles are published yet — check back soon.";
    $("error").hidden = false;
    return;
  }
  bigById = Object.fromEntries(bigIndex.map((e) => [e.id, e]));
  // theme filter options: every theme any puzzle can wear, with an
  // at-a-glance capability card when the index carries one
  const names = {};
  for (const e of bigIndex) Object.assign(names, e.themes);
  const fsel = $("big-filter-theme");
  for (const key of Object.keys(names).sort()) {
    const opt = document.createElement("option");
    opt.value = key;
    const meta = themeMeta && themeMeta[key];
    opt.textContent = meta
      ? `${names[key]} — nested: ${meta.nested ? "yes" : "no"} · groups: ${meta.group_categories} · seq: ${meta.sequential_categories}`
      : names[key];
    fsel.appendChild(opt);
  }
  try {
    const saved = localStorage.getItem(BIG_FILTER_STORE);
    if (saved && names[saved]) bigThemeFilter = saved;
  } catch (e) { /* fine */ }
  fsel.value = bigThemeFilter;
  renderCatalog();
  const wanted = location.hash.slice(1);
  if (wanted && bigById[wanted]) {
    const theme = new URLSearchParams(location.search).get("theme");
    await openBigPuzzle(wanted, { theme });
  } else {
    bigShowCatalog();
  }
}

if (BIG) {
  $("big-theme").addEventListener("change", (e) => setBigTheme(e.target.value));
  $("big-filter-theme").addEventListener("change", (e) => {
    bigThemeFilter = e.target.value;
    try { localStorage.setItem(BIG_FILTER_STORE, bigThemeFilter); } catch (err) { /* fine */ }
    renderCatalog();
  });
  $("big-back").addEventListener("click", (e) => { e.preventDefault(); bigShowCatalog(); });
  window.addEventListener("hashchange", () => {
    const id = location.hash.slice(1);
    if (!id) bigShowCatalog();
    else if (bigById[id] && (!bigBundle || bigBundle.id !== id)) openBigPuzzle(id);
  });
}

$("generate").addEventListener("click", generate);
$("hint").addEventListener("click", hint);
$("print").addEventListener("click", () => window.print());
$("check").addEventListener("click", check);
$("reveal").addEventListener("click", reveal);
$("clear").addEventListener("click", clearGrids);
$("undo").addEventListener("click", undoEdit);
$("redo").addEventListener("click", redoEdit);
if (!DAILY) $("share-puzzle").addEventListener("click", sharePuzzle); // the daily has nothing to parameterize
$("share-result").addEventListener("click", DAILY ? shareDailyResult : shareResult);

// Standard editor shortcuts: Ctrl/Cmd+Z undo, Ctrl/Cmd+Shift+Z or Ctrl+Y redo.
document.addEventListener("keydown", (e) => {
  if (!puzzle || $("puzzle").hidden) return;
  const tag = (e.target.tagName || "").toLowerCase();
  if (tag === "input" || tag === "select" || tag === "textarea") return; // let fields keep Ctrl+Z
  const mod = e.ctrlKey || e.metaKey;
  if (!mod) return;
  const k = e.key.toLowerCase();
  if (k === "z" && !e.shiftKey) { e.preventDefault(); undoEdit(); }
  else if ((k === "z" && e.shiftKey) || k === "y") { e.preventDefault(); redoEdit(); }
});
$("categories").addEventListener("change", syncItemOptions);
// Switching theme draws a fresh puzzle in that theme.
$("theme").addEventListener("change", () => {
  syncCustomControls();
  if (isCustom() && !customDoc) { $("theme-file").click(); return; }
  generate();
});
$("theme-file").addEventListener("change", (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const doc = JSON.parse(reader.result);
      if (!doc || typeof doc !== "object" || !Array.isArray(doc.categories)) {
        throw new Error("not a theme file (expected a JSON object with a categories array)");
      }
      customDoc = doc;
      try { localStorage.setItem(CUSTOM_STORE, JSON.stringify(doc)); } catch (err) { /* fine */ }
      ensureCustomOption();
      $("theme").value = CUSTOM_KEY;
      syncCustomControls();
      generate();
    } catch (err) {
      $("error").textContent = `Could not load ${file.name}: ${err.message}`;
      $("error").hidden = false;
      if (isCustom() && !customDoc) $("theme").selectedIndex = 0; // back to a registry theme
      syncCustomControls();
    }
  };
  reader.readAsText(file);
});
// If the file dialog is dismissed with nothing chosen, don't leave the picker
// stuck on an empty custom slot ("cancel" is supported in modern browsers).
$("theme-file").addEventListener("cancel", () => {
  if (isCustom() && !customDoc) { $("theme").selectedIndex = 0; syncCustomControls(); }
});
// Swap layouts when crossing the breakpoint, preserving marks.
DESKTOP.addEventListener("change", () => { if (puzzle) renderBoard(); });
// Keep the desktop grid fitted to the window as it resizes.
window.addEventListener("resize", () => { if (puzzle) fitBoard(); });

(async function init() {
  initColorblind();
  if (DAILY) {
    await loadDaily(); // fixed theme/size/difficulty — no pickers to set up
    return;
  }
  if (BIG) {
    await loadBig(); // static bundles — the pickers are the puzzle/theme lists
    return;
  }
  syncItemOptions();
  loadStoredCustom();
  await loadThemes();
  if (location.hash === "#custom" && customDoc) {
    $("theme").value = CUSTOM_KEY; // arrived from the builder's "Play this theme"
  }
  applySharedPuzzleParams(); // a shared puzzle link pins the controls before the first generate()
  syncCustomControls();
  try {
    await generate();
  } catch (err) {
    $("loading").hidden = true;
    $("error").textContent = err.message;
    $("error").hidden = false;
  }
})();
