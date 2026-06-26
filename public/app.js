"use strict";

const $ = (id) => document.getElementById(id);
const STATES = ["", "=", "×"]; // 0 blank, 1 link (=), 2 no-link (×)

let puzzle = null;        // current payload
// `manual` is the source of truth: what the user explicitly set in each cell
// (0 blank, 1 link "=", 2 no-link "×"). The displayed × marks are *derived*:
// any blank cell sharing a row or column with a manual "=" shows an auto "×".
// Removing the "=" therefore reverts only those auto marks, never manual ones.
let manual = {};          // "i-j" -> n_i x n_j array of 0/1/2 (user intent)
let linked = {};          // "i-j" -> Set of "aIdx,bIdx" that are truly linked

async function fetchJSON(url) {
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

async function loadThemes() {
  const { themes } = await fetchJSON("/api/puzzle?list=1");
  const sel = $("theme");
  sel.innerHTML = "";
  for (const t of themes) {
    const opt = document.createElement("option");
    opt.value = t.key;
    opt.textContent = `${t.name} (${t.size}×${t.categories})`;
    sel.appendChild(opt);
  }
}

async function generate() {
  const theme = $("theme").value;
  const seed = $("seed").value.trim();
  const params = new URLSearchParams({ theme });
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
  $("p-meta").innerHTML =
    `Seed <code>${puzzle.seed}</code> · ${puzzle.clues.length} clues`;

  const ol = $("clues");
  ol.innerHTML = "";
  for (const c of puzzle.clues) {
    const li = document.createElement("li");
    li.textContent = c;
    ol.appendChild(li);
  }

  const host = $("grids");
  host.innerHTML = "";
  const cats = puzzle.categories;
  for (const [i, j] of pairs()) {
    host.appendChild(renderGrid(i, j, cats));
  }
  setResult("", "");
}

function renderGrid(i, j, cats) {
  const key = `${i}-${j}`;
  const block = document.createElement("div");
  block.className = "grid-block";
  const title = document.createElement("h4");
  title.innerHTML = `<b>${cats[i].name}</b> × <b>${cats[j].name}</b>`;
  block.appendChild(title);

  const table = document.createElement("table");
  table.className = "grid";

  // Fixed column widths via <colgroup> + table-layout:fixed so every grid has
  // identical dimensions no matter how long the labels are.
  const colgroup = document.createElement("colgroup");
  const lab = document.createElement("col");
  lab.className = "rowlab-col";
  colgroup.appendChild(lab);
  cats[j].items.forEach(() => {
    const c = document.createElement("col");
    c.className = "cell-col";
    colgroup.appendChild(c);
  });
  table.appendChild(colgroup);

  const head = document.createElement("tr");
  head.appendChild(cell("th", "", "corner"));
  for (const label of cats[j].items) {
    const th = cell("th", "", "col");
    th.title = label;
    const span = document.createElement("span"); // rotated vertically in CSS
    span.textContent = label;
    th.appendChild(span);
    head.appendChild(th);
  }
  table.appendChild(head);

  cats[i].items.forEach((rowLabel, a) => {
    const tr = document.createElement("tr");
    const rh = cell("th", rowLabel, "row");
    rh.title = rowLabel;
    tr.appendChild(rh);
    cats[j].items.forEach((_, b) => {
      const td = cell("td", "", "cell");
      td.dataset.key = key;
      td.dataset.a = a;
      td.dataset.b = b;
      td.addEventListener("click", onCellClick);
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });

  block.appendChild(table);
  return block;
}

function cell(tag, text, cls) {
  const el = document.createElement(tag);
  el.className = cls;
  el.textContent = text;
  return el;
}

function cellEl(key, a, b) {
  return document.querySelector(
    `td.cell[data-key="${key}"][data-a="${a}"][data-b="${b}"]`
  );
}

// Grid-interaction logic (derive / nextState / lineHasEqElsewhere) lives in the
// shared, unit-tested module logic.js, exposed here as the global `LG`.

// Re-derive one grid and repaint all its cells.
function paintGrid(key) {
  const { display, lit } = LG.derive(manual[key]);
  for (let a = 0; a < display.length; a++) {
    for (let b = 0; b < display[a].length; b++) {
      const td = cellEl(key, a, b);
      const state = display[a][b];
      td.textContent = STATES[state];
      td.classList.toggle("yes", state === 1);
      td.classList.toggle("no", state === 2);
      td.classList.toggle("lit", lit[a][b]);
      td.classList.remove("right", "wrong");
    }
  }
  return display;
}

function onCellClick(e) {
  const td = e.currentTarget;
  const key = td.dataset.key;
  const a = +td.dataset.a;
  const b = +td.dataset.b;
  manual[key][a][b] = LG.nextState(manual[key], a, b);
  paintGrid(key);
  clearHighlights(); // a fresh edit invalidates any prior check
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

$("generate").addEventListener("click", generate);
$("check").addEventListener("click", check);
$("reveal").addEventListener("click", reveal);
$("clear").addEventListener("click", clearGrids);

(async function init() {
  try {
    await loadThemes();
    await generate();
  } catch (err) {
    $("loading").hidden = true;
    $("error").textContent = err.message;
    $("error").hidden = false;
  }
})();
