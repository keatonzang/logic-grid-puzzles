"use strict";

const $ = (id) => document.getElementById(id);
const STATES = ["", "=", "×"]; // 0 blank, 1 link (=), 2 no-link (×)
// Per-group accent colors, ordered by hue (amber → green → blue → violet →
// pink) so alphabetically-sorted groups pick up an even spread across the wheel.
const GROUP_COLORS = ["#ffc46e", "#51cf66", "#6ea8fe", "#c9a7ff", "#ff8fab"];
const DESKTOP = window.matchMedia("(min-width: 821px)"); // staircase vs pairwise

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

// The live ticking clock is hidden for now — we still measure the elapsed time
// and report it on a solve, just without a running display during play. Flip
// this (e.g. from a future user setting) to show the clock live again.
const SHOW_LIVE_TIMER = false;

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
  return c && c.groups && c.groups.length ? c.groups : null;
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
  const cats = puzzle.categories;
  for (const [i, j] of pairs()) {
    const key = `${i}-${j}`;
    manual[key] = cats[i].items.map(() => cats[j].items.map(() => 0));
    const set = new Set();
    for (const row of puzzle.solution) {
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
  $("p-meta").innerHTML =
    `${puzzle.categories.length} × ${puzzle.items} · <b>${puzzle.difficulty}</b>${reqNote}${tierNote} · ` +
    `${puzzle.clues.length} clues · seed <code>${puzzle.seed}</code>`;

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
  document.querySelectorAll("table.staircase, table.grid").forEach((table) => {
    const left = table.querySelectorAll("th.sc-rowguild .gl-i");
    if (!left.length) return;
    let need = 0;
    left.forEach((el) => { el.style.removeProperty("--glfs"); need = Math.max(need, el.scrollWidth); });
    const colEl = table.querySelector("col.sc-rowguild-col");
    if (colEl && need) colEl.style.width = Math.ceil(need + 8) + "px"; // + padding + border
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
    table.querySelectorAll("th.sc-rowguild .gl-i").forEach((el) => shrink(el, "height"));
    const top = [...table.querySelectorAll("th.sc-guild .gl-i, th.g-band .gl-i")];
    if (!top.length) return;
    top.forEach((el) => shrink(el, "width"));
    let need = 0;
    top.forEach((el) => { need = Math.max(need, el.scrollHeight); });
    const MINH = 1.6 * rem, MAXH = 4.5 * rem;
    table.style.setProperty("--gband-h", Math.min(MAXH, Math.max(MINH, Math.ceil(need) + 6)) + "px");
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
  const leftCols = rowSegs ? 2 : 1;  // row-label (+ guild-label) column(s)

  const table = document.createElement("table");
  table.className = "grid";
  const colgroup = document.createElement("colgroup");
  if (rowSegs) colgroup.appendChild(col("sc-rowguild-col"));
  colgroup.appendChild(col("rowlab-col"));
  colCells.forEach(() => colgroup.appendChild(col("cell-col")));
  table.appendChild(colgroup);

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
  const leftCols = anyRowGrouped ? 3 : 2;  // cat-label (+ guild) + row-label

  const table = document.createElement("table");
  table.className = "staircase";

  const cg = document.createElement("colgroup");
  cg.appendChild(col("sc-catcol"));
  if (anyRowGrouped) cg.appendChild(col("sc-rowguild-col"));
  cg.appendChild(col("sc-rowlab-col"));
  colCats.forEach(() => cats[0].items.forEach(() => cg.appendChild(col("cell-col"))));
  table.appendChild(cg);

  // header row 1: column-category names
  const h1 = document.createElement("tr");
  const corner = cell("th", "", "sc-corner");
  corner.colSpan = leftCols;
  corner.rowSpan = anyColGrouped ? 3 : 2;
  h1.appendChild(corner);
  for (const j of colCats) {
    const th = cell("th", cats[j].name, "sc-colcat" + (j !== firstCol ? " blk-left" : ""));
    th.colSpan = N;
    if (anyColGrouped && !catGroups(j)) th.rowSpan = 2;  // centre over the (absent) band row
    h1.appendChild(th);
  }
  table.appendChild(h1);

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
    axisCells(i).forEach(({ b: a, pos: posI, grpEdge: grpEdgeI }) => {
      const tr = document.createElement("tr");
      const horizTop = posI === 0 ? (i > 0 ? " blk-top" : "") : (grpEdgeI ? " grp-top" : "");
      if (posI === 0) {
        const catTh = vlabel(cell("th", "", "sc-rowcat" + (i > 0 ? " blk-top" : "")), cats[i].name);
        catTh.rowSpan = N;
        if (anyRowGrouped && !rowSegs) catTh.colSpan = 2;  // span the empty guild slot
        tr.appendChild(catTh);
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

function check() {
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
      const steps = history.size();
      const stats =
        `<b>${fmtTime(performance.now() - timerStart)}</b>` +
        ` · <b>${steps}</b> step${steps === 1 ? "" : "s"}`;
      stopTimer(true);
      setFeedback(`<b>Solved!</b> The whole table checks out — ${stats}.`, "good");
    } else {
      stopTimer(true);
      setFeedback("<b>Solved!</b> The whole table checks out.", "good");
    }
  } else if (mistakes === 0) {
    setFeedback(`No mistakes so far — <b>${remaining}</b> more to work out.`, "warn");
  } else {
    const bits = [`<b>${mistakes}</b> mistake${mistakes > 1 ? "s" : ""} (highlighted)`];
    if (remaining > 0) bits.push(`<b>${remaining}</b> still to work out`);
    setFeedback(bits.join(" · "), "bad");
  }
}

function reveal() {
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
const DEFAULT_FEEDBACK = "Click a cell to cycle ✓ / ✗. Press <b>Hint</b> for the next logical step.";
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
  if (!puzzle) return;
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
    const step = await postJSON("/api/hint", {
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

$("generate").addEventListener("click", generate);
$("hint").addEventListener("click", hint);
$("print").addEventListener("click", () => window.print());
$("check").addEventListener("click", check);
$("reveal").addEventListener("click", reveal);
$("clear").addEventListener("click", clearGrids);
$("undo").addEventListener("click", undoEdit);
$("redo").addEventListener("click", redoEdit);

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
  syncItemOptions();
  loadStoredCustom();
  await loadThemes();
  if (location.hash === "#custom" && customDoc) {
    $("theme").value = CUSTOM_KEY; // arrived from the builder's "Play this theme"
  }
  syncCustomControls();
  try {
    await generate();
  } catch (err) {
    $("loading").hidden = true;
    $("error").textContent = err.message;
    $("error").hidden = false;
  }
})();
