"use strict";
// Theme Builder: edit -> single-file JSON (the logicgrid.themes format) ->
// download / upload / server-validated preview / hand off to the main page.
// The document in the "The file" panel IS the theme: same file + same
// settings + same seed always regenerates the identical puzzle.

const $ = (id) => document.getElementById(id);

const STORE_KEY = "lgp-custom-theme"; // read by app.js on the main page

// --- Editor state ------------------------------------------------------------
// Categories are kept as raw *text* fields (items one-per-line etc.) so typing
// never fights a parser; buildDoc() converts to the file format on demand.
let cats = [];

function blankCat() {
  return {
    name: "", itemsText: "", referent: "", plural: false,
    ordered: false, valuesText: "", unit: "", unitSuffix: "",
    groupNoun: "", groupsText: "",
  };
}

const lines = (t) => t.split("\n").map((s) => s.trim()).filter(Boolean);

// --- doc <-> state -----------------------------------------------------------
function buildDoc() {
  const doc = {
    name: $("b-name").value.trim() || "Untitled puzzle",
    description: $("b-desc").value.trim(),
    entity_noun: $("b-noun").value.trim() || "entry",
    categories: [],
  };
  for (const c of cats) {
    const cd = { name: c.name.trim(), items: lines(c.itemsText) };
    if (c.ordered) {
      cd.ordered = true;
      const vals = lines(c.valuesText).map(Number);
      if (vals.length && vals.every((v) => Number.isFinite(v))) cd.values = vals;
      if (c.unit.trim()) cd.unit = c.unit.trim();
      if (c.unitSuffix.trim()) cd.unit_suffix = c.unitSuffix.trim();
    }
    if (c.referent.trim()) cd.referent = c.referent.trim();
    if (c.plural) cd.plural = true;
    const groups = lines(c.groupsText).map((line) => {
      const i = line.indexOf(":");
      return {
        label: (i < 0 ? line : line.slice(0, i)).trim(),
        items: (i < 0 ? "" : line.slice(i + 1)).split(",").map((s) => s.trim()).filter(Boolean),
      };
    }).filter((g) => g.label && g.items.length);
    if (groups.length) {
      cd.group_noun = c.groupNoun.trim() || "group";
      cd.groups = groups;
    }
    doc.categories.push(cd);
  }
  return doc;
}

function docToState(doc) {
  $("b-name").value = doc.name || "";
  $("b-desc").value = doc.description || "";
  $("b-noun").value = doc.entity_noun || "";
  cats = (doc.categories || []).map((cd) => ({
    name: cd.name || "",
    itemsText: (cd.items || []).join("\n"),
    referent: cd.referent || "",
    plural: !!cd.plural,
    ordered: !!cd.ordered,
    valuesText: (cd.values || []).join("\n"),
    unit: cd.unit || "",
    unitSuffix: cd.unit_suffix || "",
    groupNoun: cd.group_noun || "",
    groupsText: (cd.groups || []).map((g) => `${g.label}: ${g.items.join(", ")}`).join("\n"),
  }));
}

// --- Rendering ----------------------------------------------------------------
function catCard(c, idx) {
  const card = document.createElement("section");
  card.className = "card";
  card.innerHTML = `
    <div class="cat-head">
      <h4>Category ${idx + 1}</h4>
      <span class="cat-tools">
        <button data-act="up" title="Move up" ${idx === 0 ? "disabled" : ""}>↑</button>
        <button data-act="down" title="Move down" ${idx === cats.length - 1 ? "disabled" : ""}>↓</button>
        <button data-act="del" title="Remove category" ${cats.length <= 2 ? "disabled" : ""}>✕</button>
      </span>
    </div>
    <div class="row">
      <label class="field"><span>Name</span><input data-f="name" type="text" placeholder="Vendor" /></label>
      <label class="field"><span>Referent (optional)</span><input data-f="referent" type="text" placeholder="the vendor selling {}" />
        <small>Template for naming a row by this category's item — <code>{}</code> is the item: “the vendor selling <i>Lanterns</i>”.</small></label>
    </div>
    <label class="field"><span>Items — one per line (every category needs the same count; labels unique across the whole theme)</span>
      <textarea data-f="itemsText" placeholder="Mei&#10;Omar&#10;Petra&#10;Quinn"></textarea></label>
    <label class="inline-check"><input data-f="plural" type="checkbox" /> plural name (“Earnings”)</label>
    <label class="inline-check"><input data-f="ordered" type="checkbox" /> ordered / numeric</label>
    <div class="ordered-extra" hidden>
      <label class="field"><span>Values — one number per line, ascending, matching the items</span>
        <textarea data-f="valuesText" placeholder="10&#10;20&#10;30&#10;40"></textarea></label>
      <div class="row">
        <label class="field"><span>Unit prefix (optional)</span><input data-f="unit" type="text" placeholder="$" /></label>
        <label class="field"><span>Unit suffix (optional)</span><input data-f="unitSuffix" type="text" placeholder=" coins" /></label>
      </div>
    </div>
    <label class="field" style="margin-top:.6rem"><span>Groups (optional) — “Label: item, item” per line; unlocks hierarchy clues</span>
      <textarea data-f="groupsText" placeholder="North Row: Mei, Omar&#10;South Row: Petra, Quinn"></textarea></label>
    <div class="groups-extra">
      <label class="field"><span>Group noun (used when groups are present)</span>
        <input data-f="groupNoun" type="text" placeholder="row" /></label>
    </div>
  `;
  for (const el of card.querySelectorAll("[data-f]")) {
    const f = el.dataset.f;
    if (el.type === "checkbox") {
      el.checked = c[f];
      el.addEventListener("change", () => { c[f] = el.checked; onEdit(); if (f === "ordered") card.querySelector(".ordered-extra").hidden = !el.checked; });
    } else {
      el.value = c[f];
      el.addEventListener("input", () => { c[f] = el.value; onEdit(); });
    }
  }
  card.querySelector(".ordered-extra").hidden = !c.ordered;
  card.querySelector('[data-act="del"]').addEventListener("click", () => { cats.splice(idx, 1); renderCats(); onEdit(); });
  card.querySelector('[data-act="up"]').addEventListener("click", () => { [cats[idx - 1], cats[idx]] = [cats[idx], cats[idx - 1]]; renderCats(); onEdit(); });
  card.querySelector('[data-act="down"]').addEventListener("click", () => { [cats[idx + 1], cats[idx]] = [cats[idx], cats[idx + 1]]; renderCats(); onEdit(); });
  return card;
}

function renderCats() {
  const host = $("b-cats");
  host.innerHTML = "";
  cats.forEach((c, i) => host.appendChild(catCard(c, i)));
}

// --- Quick client-side sanity (server stays authoritative) --------------------
function localProblems(doc) {
  const probs = [];
  if (doc.categories.length < 2) probs.push("A theme needs at least 2 categories.");
  const counts = doc.categories.map((c) => c.items.length);
  if (counts.length && new Set(counts).size > 1) {
    probs.push(`Every category needs the same number of items (got ${counts.join(", ")}).`);
  }
  if (counts.some((n) => n < 2)) probs.push("Each category needs at least 2 items.");
  if (counts.some((n) => n > 6)) probs.push("Custom themes are capped at 6 items per category.");
  const all = doc.categories.flatMap((c) => c.items);
  const dupes = all.filter((x, i) => all.indexOf(x) !== i);
  if (dupes.length) probs.push(`Item labels must be unique across ALL categories: ${[...new Set(dupes)].join(", ")}.`);
  for (const c of doc.categories) {
    if (!c.name) probs.push("Every category needs a name.");
    if (c.referent && !c.referent.includes("{}")) {
      probs.push(`“${c.name}”: the referent needs a {} where the item goes (e.g. “the seller of {}”).`);
    }
    if (c.ordered && c.values && c.values.length !== c.items.length) {
      probs.push(`“${c.name}”: values (${c.values.length}) must match items (${c.items.length}).`);
    }
  }
  return probs;
}

// --- Edit pipeline -------------------------------------------------------------
function onEdit() {
  const doc = buildDoc();
  $("b-json").value = JSON.stringify(doc, null, 2);
  const probs = localProblems(doc);
  const err = $("b-error");
  err.hidden = probs.length === 0;
  err.textContent = probs.join("\n");
  $("b-status").textContent = probs.length ? "" : "Looks consistent — try a preview, then download.";
}

// --- Actions --------------------------------------------------------------------
function download() {
  const doc = buildDoc();
  const name = (doc.name || "theme").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  const blob = new Blob([JSON.stringify(doc, null, 2) + "\n"], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${name || "theme"}.theme.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function upload(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const doc = JSON.parse(reader.result);
      if (!doc || typeof doc !== "object" || !Array.isArray(doc.categories)) {
        throw new Error("Not a theme file: expected a JSON object with a categories array.");
      }
      docToState(doc);
      renderCats();
      onEdit();
      $("b-status").textContent = `Loaded “${doc.name || file.name}”.`;
    } catch (e) {
      $("b-error").textContent = `Could not load ${file.name}: ${e.message}`;
      $("b-error").hidden = false;
    }
  };
  reader.readAsText(file);
}

async function generatePreview() {
  const doc = buildDoc();
  const probs = localProblems(doc);
  if (probs.length) { onEdit(); return; }
  const btn = $("b-generate");
  btn.disabled = true;
  $("b-status").textContent = "Generating…";
  $("b-error").hidden = true;
  $("b-preview").hidden = true;
  try {
    const body = { theme_doc: doc, difficulty: $("b-difficulty").value };
    const seed = $("b-seed").value.trim();
    if (seed !== "") body.seed = Number(seed);
    const res = await fetch("/api/puzzle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    $("preview-meta").textContent =
      `${data.items} × ${data.n_categories} · requested ${data.requested}, measured ${data.difficulty}` +
      ` · ${data.clues.length} clues · seed ${data.seed}`;
    const ol = $("preview-clues");
    ol.innerHTML = "";
    for (const clue of data.clues) {
      const li = document.createElement("li");
      li.textContent = clue;
      ol.appendChild(li);
    }
    $("b-preview").hidden = false;
    $("b-status").innerHTML = `<span class="ok">✓ Valid theme — unique, logic-solvable puzzle generated.</span>`;
  } catch (e) {
    $("b-error").textContent = e.message;
    $("b-error").hidden = false;
    $("b-status").textContent = "";
  } finally {
    btn.disabled = false;
  }
}

function play() {
  const doc = buildDoc();
  const probs = localProblems(doc);
  if (probs.length) { onEdit(); return; }
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(doc));
  } catch (e) {
    $("b-error").textContent = "Could not hand the theme to the main page (storage blocked). Download the file and upload it there instead.";
    $("b-error").hidden = false;
    return;
  }
  location.href = "/#custom";
}

// --- Starter content --------------------------------------------------------------
const STARTER = {
  name: "The Night Market",
  description: "Four vendors set up stalls at the night market, each selling different wares from a numbered pitch.",
  entity_noun: "stall",
  categories: [
    { name: "Vendor", items: ["Mei", "Omar", "Petra", "Quinn"] },
    { name: "Wares", items: ["Candles", "Lanterns", "Spices", "Teapots"], referent: "the seller of {}" },
    { name: "Pitch", items: ["Pitch 1", "Pitch 2", "Pitch 3", "Pitch 4"], ordered: true, values: [1, 2, 3, 4] },
  ],
};

(function init() {
  let doc = STARTER;
  try {
    const stored = localStorage.getItem(STORE_KEY);
    if (stored) doc = JSON.parse(stored);
  } catch (e) { /* fall back to the starter */ }
  docToState(doc);
  renderCats();
  onEdit();

  $("b-add-cat").addEventListener("click", () => { cats.push(blankCat()); renderCats(); onEdit(); });
  $("b-download").addEventListener("click", download);
  $("b-upload").addEventListener("click", () => $("b-file").click());
  $("b-file").addEventListener("change", (e) => { if (e.target.files[0]) upload(e.target.files[0]); e.target.value = ""; });
  $("b-generate").addEventListener("click", generatePreview);
  $("b-play").addEventListener("click", play);
})();
