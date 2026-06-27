"use strict";

const $ = (id) => document.getElementById(id);
const STATES = ["", "=", "×"]; // 0 blank, 1 link (=), 2 no-link (×)
const DESKTOP = window.matchMedia("(min-width: 821px)"); // staircase vs pairwise

let puzzle = null;        // current payload
// `manual` is the source of truth: what the user explicitly set in each cell
// (0 blank, 1 link "=", 2 no-link "×"). The displayed × marks are *derived*:
// any blank cell sharing a row or column with a manual "=" shows an auto "×".
let manual = {};          // "i-j" -> n_i x n_j array of 0/1/2 (user intent)
let linked = {};          // "i-j" -> Set of "aIdx,bIdx" that are truly linked
let pendingHint = null;   // a fetched hint awaiting its "reveal tile" click

async function fetchJSON(url) {
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

async function postJSON(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

async function generate() {
  const params = new URLSearchParams({
    difficulty: $("difficulty").value,
    items: $("items").value,
    categories: $("categories").value,
  });
  const seed = $("seed").value.trim();
  if (seed !== "") params.set("seed", seed);

  $("error").hidden = true;
  $("loading").hidden = false;
  $("puzzle").hidden = true;
  try {
    puzzle = await fetchJSON(`/api/puzzle?${params}`);
    buildState();
    render();
    $("puzzle").hidden = false;
  } catch (err) {
    $("error").textContent = err.message;
    $("error").hidden = false;
  } finally {
    $("loading").hidden = true;
  }
}

function pairs() {
  const k = puzzle.categories.length;
  const out = [];
  for (let i = 0; i < k; i++) for (let j = i + 1; j < k; j++) out.push([i, j]);
  return out;
}

function buildState() {
  manual = {};
  linked = {};
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
    ? ` · <span title="hardest deduction technique needed (4 = proof by contradiction)">logic tier ${tier}</span>`
    : "";
  $("p-meta").innerHTML =
    `${puzzle.categories.length} × ${puzzle.items} · <b>${puzzle.difficulty}</b>${tierNote} · ` +
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
  clearHint();
  setResult("", "");
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

  const table = document.createElement("table");
  table.className = "grid";
  const colgroup = document.createElement("colgroup");
  colgroup.appendChild(col("rowlab-col"));
  cats[j].items.forEach(() => colgroup.appendChild(col("cell-col")));
  table.appendChild(colgroup);

  const head = document.createElement("tr");
  head.appendChild(cell("th", "", "corner"));
  for (const label of cats[j].items) head.appendChild(vlabel(cell("th", "", "col"), label));
  table.appendChild(head);

  cats[i].items.forEach((rowLabel, a) => {
    const tr = document.createElement("tr");
    const rh = cell("th", rowLabel, "row");
    rh.title = rowLabel;
    tr.appendChild(rh);
    cats[j].items.forEach((_, b) => tr.appendChild(dataCell(key, a, b)));
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

  const table = document.createElement("table");
  table.className = "staircase";

  const cg = document.createElement("colgroup");
  cg.appendChild(col("sc-catcol"));
  cg.appendChild(col("sc-rowlab-col"));
  colCats.forEach(() => cats[0].items.forEach(() => cg.appendChild(col("cell-col"))));
  table.appendChild(cg);

  // header row 1: column-category names
  const h1 = document.createElement("tr");
  const corner = cell("th", "", "sc-corner");
  corner.colSpan = 2;
  corner.rowSpan = 2;
  h1.appendChild(corner);
  for (const j of colCats) {
    const th = cell("th", cats[j].name, "sc-colcat blk-left");
    th.colSpan = N;
    h1.appendChild(th);
  }
  table.appendChild(h1);

  // header row 2: column item labels (vertical)
  const h2 = document.createElement("tr");
  for (const j of colCats) {
    cats[j].items.forEach((label, b) =>
      h2.appendChild(vlabel(cell("th", "", "col" + (b === 0 ? " blk-left" : "")), label))
    );
  }
  table.appendChild(h2);

  // body
  for (const i of rowCats) {
    cats[i].items.forEach((rowLabel, a) => {
      const tr = document.createElement("tr");
      if (a === 0) {
        const catTh = vlabel(cell("th", "", "sc-rowcat" + (i > 0 ? " blk-top" : "")), cats[i].name);
        catTh.rowSpan = N;
        tr.appendChild(catTh);
      }
      const rh = cell("th", rowLabel, "row" + (a === 0 && i > 0 ? " blk-top" : ""));
      rh.title = rowLabel;
      tr.appendChild(rh);
      for (const j of colCats) {
        for (let b = 0; b < N; b++) {
          const edge = (b === 0 ? "blk-left " : "") + (a === 0 && i > 0 ? "blk-top" : "");
          if (i < j) {
            tr.appendChild(dataCell(`${i}-${j}`, a, b, edge.trim()));
          } else {
            tr.appendChild(cell("td", "", ("void " + edge).trim()));
          }
        }
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
  manual[key][a][b] = LG.nextState(manual[key], a, b);
  paintGrid(key);
  clearHighlights(); // a fresh edit invalidates any prior check
  clearHint();       // ...and any pending hint
  setResult("", "");
}

function clearHighlights() {
  document.querySelectorAll("td.cell.right, td.cell.wrong").forEach((td) => {
    td.classList.remove("right", "wrong");
  });
}

function check() {
  clearHighlights();
  let correctYes = 0, mistakes = 0, totalLinks = 0;
  for (const [i, j] of pairs()) {
    const key = `${i}-${j}`;
    const { display } = LG.derive(manual[key]);
    totalLinks += puzzle.solution.length; // n links per pair
    for (let a = 0; a < display.length; a++) {
      for (let b = 0; b < display[a].length; b++) {
        const truth = linked[key].has(`${a},${b}`);
        const state = display[a][b];
        const td = cellEl(key, a, b);
        if (!td) continue;
        if (state === 1 && truth) { td.classList.add("right"); correctYes++; }
        else if (state === 1 && !truth) { td.classList.add("wrong"); mistakes++; }
        else if (state === 2 && truth) { td.classList.add("wrong"); mistakes++; }
      }
    }
  }
  const missing = totalLinks - correctYes;
  if (mistakes === 0 && missing === 0) {
    setResult("Solved! 🎉", "good");
  } else {
    const bits = [];
    if (mistakes) bits.push(`${mistakes} mistake${mistakes > 1 ? "s" : ""}`);
    if (missing) bits.push(`${missing} link${missing > 1 ? "s" : ""} to go`);
    setResult(bits.join(" · "), "bad");
  }
}

function reveal() {
  clearHighlights();
  clearHint();
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
  setResult("Solution revealed", "");
}

function clearGrids() {
  clearHighlights();
  clearHint();
  for (const key of Object.keys(manual)) {
    const M = manual[key];
    for (let a = 0; a < M.length; a++) M[a].fill(0);
    paintGrid(key);
  }
  setResult("", "");
}

function setResult(text, cls) {
  const el = $("result");
  el.textContent = text;
  el.className = "result" + (cls ? " " + cls : "");
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

function showHintBox(step, placed) {
  const box = $("hint-box");
  box.hidden = false;
  const tail = placed
    ? `<span class="hint-placed">— placed ✓</span>`
    : `<span class="hint-cta">Tap the glowing cell or “Reveal tile” to fill it in.</span>`;
  box.innerHTML =
    `<span class="hint-tier">${step.tier_name}</span>` +
    `<span class="hint-text">${escapeHtml(step.text)}</span> ${tail}`;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function applyHint(step) {
  const M = manual[step.key];
  if (step.value === 1) {
    // a confirmed link clears any (mistaken) link the player had in its row/col
    for (let b = 0; b < M[step.a].length; b++) if (M[step.a][b] === 1) M[step.a][b] = 0;
    for (let a = 0; a < M.length; a++) if (M[a][step.b] === 1) M[a][step.b] = 0;
  }
  M[step.a][step.b] = step.value;
  paintGrid(step.key);
  const td = cellEl(step.key, step.a, step.b);
  if (td) { td.classList.add("hint-flash"); setTimeout(() => td.classList.remove("hint-flash"), 800); }
}

function clearHint() {
  pendingHint = null;
  document.querySelectorAll("td.cell.hint-target").forEach((td) => td.classList.remove("hint-target"));
  $("hint").textContent = "💡 Hint";
  const box = $("hint-box");
  box.hidden = true;
  box.innerHTML = "";
}

async function hint() {
  if (!puzzle) return;
  if (pendingHint) {              // second click reveals the tile we explained
    const step = pendingHint;
    clearHint();
    applyHint(step);
    showHintBox(step, true);
    clearHighlights();
    return;
  }
  const btn = $("hint");
  btn.disabled = true;
  setResult("", "");
  try {
    const step = await postJSON("/api/hint", {
      seed: puzzle.seed,
      difficulty: puzzle.requested,
      items: puzzle.items,
      categories: puzzle.n_categories,
      known: currentKnown(),
    });
    if (step.done) {
      const box = $("hint-box");
      box.hidden = false;
      box.innerHTML = `<span class="hint-text">Every remaining tile follows from what you've got — you've effectively cracked it. Hit <b>Check</b>!</span>`;
      return;
    }
    pendingHint = step;
    showHintBox(step, false);
    btn.textContent = "Reveal tile ✨";
    const td = cellEl(step.key, step.a, step.b);
    if (td) { td.classList.add("hint-target"); td.scrollIntoView({ block: "nearest", inline: "nearest" }); }
  } catch (err) {
    setResult(err.message, "bad");
  } finally {
    btn.disabled = false;
  }
}

$("generate").addEventListener("click", generate);
$("hint").addEventListener("click", hint);
$("print").addEventListener("click", () => window.print());
$("check").addEventListener("click", check);
$("reveal").addEventListener("click", reveal);
$("clear").addEventListener("click", clearGrids);
// Swap layouts when crossing the breakpoint, preserving marks.
DESKTOP.addEventListener("change", () => { if (puzzle) renderBoard(); });

(async function init() {
  try {
    await generate();
  } catch (err) {
    $("loading").hidden = true;
    $("error").textContent = err.message;
    $("error").hidden = false;
  }
})();
