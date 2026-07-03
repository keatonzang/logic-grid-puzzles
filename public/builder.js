"use strict";
// Theme Builder: edit -> single-file JSON (the logicgrid.themes format) ->
// download / upload / server-validated preview / hand off to the main page.
// The document in the "The file" panel IS the theme: same file + same
// settings + same seed always regenerates the identical puzzle. Every card
// carries a live "how it reads" preview that mirrors the engine's clue-text
// conventions (referent templates, plural agreement, units, group nouns).

const $ = (id) => document.getElementById(id);

const STORE_KEY = "lgp-custom-theme"; // read by app.js on the main page

// --- Editor state ------------------------------------------------------------
// Categories are kept as raw *text* fields (items one-per-line etc.) so typing
// never fights a parser; buildDoc() converts to the file format on demand.
let cats = [];

function blankCat() {
  return {
    name: "", itemsText: "", referent: "", plural: false,
    ordered: false, valueMode: "fixed", valuesText: "",
    minStart: "", startMax: "", stepsText: "", unit: "", unitSuffix: "",
    compareMore: "", compareLess: "",
    groupMode: "pinned", groupNoun: "", groupsText: "",
  };
}

const lines = (t) => t.split("\n").map((s) => s.trim()).filter(Boolean);
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");
const q = (s) => `<span class="q">“${esc(s)}”</span>`;
// Reference phrases are ALWAYS shown; missing pieces render as blanks that
// visibly fill in as the user types (never hide the phrase, never fake values).
const BLANK = '<span class="blank">____</span>';
const slot = (v) => (v ? esc(v) : BLANK);
const qh = (html) => `<span class="q">“${html}”</span>`;

// Mirrors the engine's pluraliser (clues._plural): entry -> entries,
// class -> classes, party -> parties. Enter nouns SINGULAR; clue text
// pluralises where needed.
function pluralize(noun) {
  if (/y$/i.test(noun) && !/[aeiou]y$/i.test(noun)) return noun.slice(0, -1) + "ies";
  if (/(s|x|z|ch|sh)$/i.test(noun)) return noun + "es";
  return noun + "s";
}
function looksPlural(noun) {
  const low = noun.toLowerCase();
  return low.endsWith("s") && !/(ss|us|is)$/.test(low);
}

// --- doc <-> state -----------------------------------------------------------
function buildDoc() {
  const doc = {
    name: $("b-name").value.trim() || "Untitled puzzle",
    description: $("b-desc").value.trim(),
    entity_noun: $("b-noun").value.trim() || "entry",
    categories: [],
  };
  for (const c of cats) {
    const randomValues = c.ordered && c.valueMode === "random";
    const cd = { name: c.name.trim() };
    if (!randomValues) cd.items = lines(c.itemsText);
    if (c.ordered) {
      cd.ordered = true;
      if (randomValues) {
        const steps = c.stepsText.split(",").map((x) => Number(x.trim())).filter((x) => Number.isFinite(x) && x > 0);
        cd.value_spec = {
          min_start: Number(c.minStart) || 0,
          start_max: Number(c.startMax) || 0,
          steps: steps.length ? steps : [1],
        };
      } else {
        const vals = lines(c.valuesText).map(Number);
        if (vals.length && vals.every((v) => Number.isFinite(v))) cd.values = vals;
      }
      if (c.unit) cd.unit = c.unit;                 // units keep their spacing
      if (c.unitSuffix) cd.unit_suffix = c.unitSuffix;
      if (c.compareMore.trim() || c.compareLess.trim()) {
        cd.compare = [c.compareMore.trim(), c.compareLess.trim()];
      }
    }
    if (c.referent.trim()) cd.referent = c.referent.trim();
    if (c.plural && c.ordered) cd.plural = true;  // plural only affects comparison text
    if (c.groupMode === "random") {
      const labels = lines(c.groupsText).map((l) => l.replace(/:.*$/, "").trim()).filter(Boolean);
      if (labels.length) {
        cd.group_labels = labels;
        cd.group_noun = c.groupNoun.trim() || "group";
      }
    } else {
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
    valueMode: cd.value_spec ? "random" : "fixed",
    valuesText: (cd.values || []).join("\n"),
    minStart: cd.value_spec ? String(cd.value_spec.min_start ?? "") : "",
    startMax: cd.value_spec ? String(cd.value_spec.start_max ?? "") : "",
    stepsText: cd.value_spec ? (cd.value_spec.steps || []).join(", ") : "",
    compareMore: (cd.compare || [])[0] || "",
    compareLess: (cd.compare || [])[1] || "",
    unit: cd.unit || "",
    unitSuffix: cd.unit_suffix || "",
    groupMode: cd.group_labels ? "random" : "pinned",
    groupNoun: cd.group_noun || "",
    groupsText: cd.group_labels
      ? cd.group_labels.join("\n")
      : (cd.groups || []).map((g) => `${g.label}: ${g.items.join(", ")}`).join("\n"),
  }));
  if (!cats.length) cats = [blankCat()];
}

// --- Live phrasing ("how it reads") -------------------------------------------
// Mirrors the engine's conventions: the subject category (first card) reads as
// the bare item; other categories read through their referent template or the
// fallback "the {entity_noun} with {item}"; plural switches verb agreement;
// units wrap numeric amounts; group clues speak in the group noun.
function refPhrase(c, idx, noun, item) {
  if (idx === 0) return item; // the subject IS the row's identity
  const ref = c.referent.trim();
  if (ref.includes("{}")) return ref.replace("{}", item);
  return `the ${noun} with ${item}`;
}

function cardReads(c, idx) {
  // Always rendered: missing pieces show as blanks that visibly fill in as
  // the user types — the phrases never hide and never fake sample values.
  const rawNoun = $("b-noun").value.trim();
  const items = lines(c.itemsText);
  const out = [];
  const a = items[0];
  const b = items[1];
  const ref = c.referent.trim();
  // A row named via THIS category's item: referent template, or the
  // entity-noun default. HTML with blank slots, mirroring clues.py exactly.
  const named = (item) => {
    if (idx === 0) return slot(item);
    if (ref.includes("{}")) return esc(cap(ref)).replace("{}", slot(item));
    return `The ${slot(rawNoun)} with ${slot(item)}`;
  };
  // The other side of the sample link: the subject's first item (or the next
  // category's, on the subject card itself).
  const other = idx === 0 ? lines(cats[1] ? cats[1].itemsText : "")[0] : lines(cats[0] ? cats[0].itemsText : "")[0];
  const randomVals = c.ordered && c.valueMode === "random";
  const step0 = randomVals
    ? c.stepsText.split(",").map((x) => Number(x.trim())).find((x) => Number.isFinite(x) && x > 0)
    : null;
  const lo = randomVals && c.minStart.trim() !== "" ? Number(c.minStart) : null;
  const sample = (i) =>
    randomVals && lo !== null && Number.isFinite(lo) && step0
      ? `${c.unit}${lo + i * step0}${c.unitSuffix}`
      : null;
  const sampleItem = a || sample(0);
  const sampleItemB = b || sample(1);
  if (idx === 0) {
    out.push(`<div><b>Named in clues:</b> ${qh(`${slot(a)} goes with ${slot(other)}.`)} — the subject reads as itself.</div>`);
  } else {
    out.push(`<div><b>Named in clues:</b> ${qh(`${named(sampleItem)} goes with ${slot(other)}.`)}${ref ? "" : " (default naming — set a referent to change it)"}</div>`);
  }
  if (c.ordered) {
    const nm = c.name.trim().toLowerCase();
    const random = c.valueMode === "random";
    const vals = random
      ? c.stepsText.split(",").map((x) => Number(x.trim())).filter((x) => Number.isFinite(x) && x > 0)
      : lines(c.valuesText).map(Number);
    const ok = random ? vals.length >= 1 : vals.length >= 2 && vals.every(Number.isFinite);
    const gap = random ? vals[0] : ok ? Math.abs(vals[1] - vals[0]) : null;
    const amount = `${esc(c.unit)}${ok ? gap : BLANK}${esc(c.unitSuffix)}`;
    const verb = c.plural ? "are" : "is";
    const article = c.plural ? "" : "a ";
    out.push(`<div><b>Comparisons:</b> ${qh(`${named(sampleItemB)}'s ${slot(nm)} ${verb} exactly ${amount} more than ${lowerFirst(named(sampleItem))}.`)}</div>`);
    const more = c.compareMore.trim() || "higher";
    out.push(`<div><b>…and:</b> ${qh(`${article}${esc(more)} ${slot(nm)}`)}${c.plural ? " (plural agreement)" : ""}</div>`);
    if (c.valueMode === "random") {
      const lo = c.minStart.trim(), hi = c.startMax.trim();
      out.push(`<div class="muted">Random values: each puzzle rolls a start (${lo || "…"}–${hi || "…"}) and a step, so items like ${qh(`${esc(c.unit)}${lo || BLANK}${esc(c.unitSuffix)}`)} vary per seed.</div>`);
    }
  }
  const gLines = lines(c.groupsText);
  if (gLines.length) {
    const gn = c.groupNoun.trim();
    const label = gLines[0].replace(/:.*$/, "").trim();
    if (label) {
      out.push(`<div><b>Groups:</b> ${qh(`${slot(a)} belongs to the ${esc(label)}.`)} · ${qh(`someone in the ${esc(label)}`)}</div>`);
      out.push(`<div><b>…and:</b> ${qh(`${slot(a)} and ${slot(b)} are in the same ${slot(gn)}.`)}${gn ? "" : " (group noun defaults to “group”)"}</div>`);
      if (c.groupMode === "random") {
        out.push(`<div class="muted">Open groups: membership is dealt fresh each puzzle (needs 4+ items to form).</div>`);
      }
    }
  }
  return out;
}

// Lowercase a leading "The " when the phrase lands mid-sentence (bare subject
// items and referent templates keep their own casing after the first word).
function lowerFirst(html) {
  return html.replace(/^The /, "the ");
}

// Only the plural-noun warning surfaces here now — the per-category "how it
// reads" boxes (cardReads) already show the noun in real sample clues, so a
// second phrase-preview at the top was pure duplication.
function themeReads() {
  const raw = $("b-noun").value.trim();
  const allItems = cats.flatMap((c) => lines(c.itemsText));
  $("noun-example").innerHTML =
    `${qh(`the ${slot(raw)} with ${slot(allItems[1])}`)} · ` +
    `${qh(`${slot(allItems[0])} and ${slot(allItems[1])} belong to different ${raw ? esc(pluralize(raw)) : BLANK}.`)}`;
  const el = $("noun-hint");
  if (raw && looksPlural(raw)) {
    el.hidden = false;
    el.textContent = "looks plural — enter the singular; clues pluralise it themselves";
  } else {
    el.hidden = true;
    el.textContent = "";
  }
}

// --- Rendering ----------------------------------------------------------------
function catCard(c, idx) {
  const card = document.createElement("section");
  card.className = "card";
  card.innerHTML = `
    <div class="cat-head">
      <h4>Category ${idx + 1}${idx === 0 ? '<span class="subject-badge">subject</span>' : ""}</h4>
      <span class="cat-tools">
        <button data-act="up" title="Move up" ${idx === 0 ? "disabled" : ""}>↑</button>
        <button data-act="down" title="Move down" ${idx === cats.length - 1 ? "disabled" : ""}>↓</button>
        <button data-act="del" title="Remove category" ${cats.length <= 1 ? "disabled" : ""}>✕</button>
      </span>
    </div>
    <div class="row">
      <label class="field"><span>Name</span><input data-f="name" type="text" placeholder="Vendor" /></label>
      <label class="field"><span>Referent <span class="opt">(optional) — names a row by its item; {} is the item</span></span>
        <input data-f="referent" type="text" placeholder="the vendor selling {}" />
        <small class="hint-inline" data-role="ref-hint"></small></label>
    </div>
    <label class="field"><span>Items <span class="opt">— one per line, same count in every category, unique across the theme</span></span>
      <textarea data-f="itemsText" placeholder="Mei&#10;Omar&#10;Petra&#10;Quinn"></textarea></label>
    <label class="inline-check"><input data-f="ordered" type="checkbox" /> Ordered / numeric value</label>
    <div class="ordered-extra" hidden>
      <label class="inline-check" style="margin-bottom:.9rem"><input data-f="plural" type="checkbox" /> Plural name (“Earnings”, “Wages”)</label>
      <label class="field"><span>Values</span>
        <select data-f="valueMode">
          <option value="fixed">Fixed — I list the items and values</option>
          <option value="random">Random per puzzle — rolled from a range (varies per seed)</option>
        </select></label>
      <label class="field" data-role="fixed-values"><span>Values <span class="opt">— one number per line, ascending, matching the items</span></span>
        <textarea data-f="valuesText" placeholder="10&#10;20&#10;30&#10;40"></textarea></label>
      <div class="row" data-role="random-values" hidden>
        <label class="field"><span>Start from</span><input data-f="minStart" type="text" inputmode="numeric" placeholder="2" /></label>
        <label class="field"><span>Start up to</span><input data-f="startMax" type="text" inputmode="numeric" placeholder="12" /></label>
        <label class="field"><span>Step choices <span class="opt">(comma-separated)</span></span><input data-f="stepsText" type="text" placeholder="1, 2" /></label>
      </div>
      <div class="row">
        <label class="field"><span>Unit prefix <span class="opt">(optional)</span></span><input data-f="unit" type="text" placeholder="$" /></label>
        <label class="field"><span>Unit suffix <span class="opt">(optional)</span></span><input data-f="unitSuffix" type="text" placeholder=" coins" /></label>
      </div>
      <div class="row" style="margin-bottom:0">
        <label class="field"><span>“Greater” word <span class="opt">(optional — defaults to “higher”)</span></span><input data-f="compareMore" type="text" placeholder="later" /></label>
        <label class="field"><span>“Lesser” word <span class="opt">(optional — defaults to “lower”)</span></span><input data-f="compareLess" type="text" placeholder="earlier" /></label>
      </div>
    </div>
    <div class="groups-extra">
      <div class="row">
        <label class="field"><span>Group membership</span>
          <select data-f="groupMode">
            <option value="pinned">Pinned — I list who's in each group</option>
            <option value="random">Open — anyone; dealt fresh each puzzle</option>
          </select></label>
        <label class="field"><span>Group noun <span class="opt">(singular)</span></span>
          <input data-f="groupNoun" type="text" placeholder="row" /></label>
      </div>
      <label class="field"><span data-role="groups-label">Groups (optional) — “Label: item, item” per line; unlocks hierarchy clues</span>
        <textarea data-f="groupsText" placeholder="North Row: Mei, Omar&#10;South Row: Petra, Quinn"></textarea></label>
    </div>
    <div class="reads" data-role="reads"></div>
  `;
  const syncValueMode = () => {
    const random = c.ordered && c.valueMode === "random";
    card.querySelector('[data-role="fixed-values"]').hidden = random;
    card.querySelector('[data-role="random-values"]').hidden = !random;
    // items are generated from the rolled values in random mode
    card.querySelector('[data-f="itemsText"]').closest(".field").hidden = random;
  };
  const syncGroupsLabel = () => {
    const span = card.querySelector('[data-role="groups-label"]');
    const ta = card.querySelector('[data-f="groupsText"]');
    if (c.groupMode === "random") {
      span.textContent = "Groups (optional) — one label per line; members are drawn per puzzle";
      ta.placeholder = "North Row\nSouth Row";
    } else {
      span.textContent = "Groups (optional) — “Label: item, item” per line; unlocks hierarchy clues";
      ta.placeholder = "North Row: Mei, Omar\nSouth Row: Petra, Quinn";
    }
  };
  // A single consolidated preview box per category — replaces the five
  // scattered hint-above lines the old layout drew above individual fields.
  // cardReads() already mirrors the engine's real clue phrasing, so this is
  // now the ONE place that live-previews how a category will read.
  const syncReads = () => {
    card.querySelector('[data-role="reads"]').innerHTML =
      '<div class="reads-label">Preview — how this reads</div>' + cardReads(c, idx).join("");

    // The referent is the least self-explanatory field, so it keeps immediate
    // at-the-field feedback: the sample clue it produces, live per keystroke.
    const refEl = card.querySelector('[data-role="ref-hint"]');
    const ref = c.referent.trim();
    const rawNoun = $("b-noun").value.trim();
    const items = lines(c.itemsText);
    const item0 = items[0];
    const other = idx === 0 ? lines(cats[1] ? cats[1].itemsText : "")[0] : lines(cats[0] ? cats[0].itemsText : "")[0];
    if (idx === 0) {
      refEl.innerHTML = `Ignored here — the subject reads as itself: ${qh(`${slot(item0)} goes with ${slot(other)}.`)}`;
    } else if (!ref) {
      refEl.innerHTML = `${qh(`The ${slot(rawNoun)} with ${slot(item0)} goes with ${slot(other)}.`)} (default — type a template to change it)`;
    } else if (!ref.includes("{}")) {
      refEl.innerHTML = `<span class="err">needs <code>{}</code> where the item goes — e.g. “the vendor selling {}”</span>`;
    } else {
      refEl.innerHTML = qh(`${esc(cap(ref)).replace("{}", slot(item0))} goes with ${slot(other)}.`);
    }
  };
  for (const el of card.querySelectorAll("[data-f]")) {
    const f = el.dataset.f;
    if (el.type === "checkbox") {
      el.checked = c[f];
      el.addEventListener("change", () => { c[f] = el.checked; if (f === "ordered") { card.querySelector(".ordered-extra").hidden = !el.checked; syncValueMode(); } onEdit(); });
    } else {
      el.value = c[f];
      el.addEventListener("input", () => {
        c[f] = el.value;
        if (f === "groupMode") syncGroupsLabel();
        if (f === "valueMode") syncValueMode();
        onEdit();
      });
      if (el.tagName === "SELECT") {
        el.addEventListener("change", () => {
          c[f] = el.value;
          syncGroupsLabel();
          syncValueMode();
          onEdit();
        });
      }
    }
  }
  card.querySelector(".ordered-extra").hidden = !c.ordered;
  if (idx === 0) card.querySelector('[data-f="referent"]').disabled = true; // subject reads as itself
  card.querySelector('[data-act="del"]').addEventListener("click", () => { cats.splice(idx, 1); renderCats(); onEdit(); });
  card.querySelector('[data-act="up"]').addEventListener("click", () => { [cats[idx - 1], cats[idx]] = [cats[idx], cats[idx - 1]]; renderCats(); onEdit(); });
  card.querySelector('[data-act="down"]').addEventListener("click", () => { [cats[idx + 1], cats[idx]] = [cats[idx], cats[idx + 1]]; renderCats(); onEdit(); });
  card._syncReads = syncReads;
  syncGroupsLabel();
  syncValueMode();
  syncReads();
  return card;
}

function renderCats() {
  const host = $("b-cats");
  host.innerHTML = "";
  cats.forEach((c, i) => host.appendChild(catCard(c, i)));
}

function refreshReads() {
  themeReads();
  for (const card of $("b-cats").children) {
    if (card._syncReads) card._syncReads();
  }
}

// --- Quick client-side sanity (server stays authoritative) --------------------
function docIsEmpty(doc) {
  return (
    !$("b-name").value.trim() && !$("b-desc").value.trim() && !$("b-noun").value.trim() &&
    doc.categories.every((c) => !c.name && !(c.items || []).length)
  );
}

function localProblems(doc) {
  const probs = [];
  if (doc.categories.length < 2) probs.push("A theme needs at least 2 categories.");
  const listed = doc.categories.filter((c) => !c.value_spec);
  const counts = listed.map((c) => (c.items || []).length);
  if (counts.length && new Set(counts).size > 1) {
    probs.push(`Every category needs the same number of items (got ${counts.join(", ")}).`);
  }
  if (counts.some((n) => n < 2)) probs.push("Each category needs at least 2 items.");
  if (counts.some((n) => n > 6)) probs.push("Custom themes are capped at 6 items per category.");
  if (!listed.length) probs.push("At least one category must list its items (they fix the row count).");
  const all = listed.flatMap((c) => c.items || []);
  const dupes = all.filter((x, i) => all.indexOf(x) !== i);
  if (dupes.length) probs.push(`Item labels must be unique across ALL categories: ${[...new Set(dupes)].join(", ")}.`);
  for (const c of doc.categories) {
    if (!c.name) probs.push("Every category needs a name.");
    if (c.referent && !c.referent.includes("{}")) {
      probs.push(`“${c.name}”: the referent needs a {} where the item goes (e.g. “the seller of {}”).`);
    }
    if (c.ordered && c.values && c.values.length !== (c.items || []).length) {
      probs.push(`“${c.name}”: values (${c.values.length}) must match items (${(c.items || []).length}).`);
    }
    if (c.compare && (!c.compare[0] || !c.compare[1])) {
      probs.push(`“${c.name}”: comparison words need both the greater and lesser word (e.g. later / earlier).`);
    }
    if (c.value_spec) {
      const v = c.value_spec;
      if (!(v.min_start <= v.start_max)) probs.push(`“${c.name}”: random values need start-from <= start-up-to.`);
      if (!v.steps.length || v.steps.some((x) => !(x > 0))) probs.push(`“${c.name}”: step choices must be positive numbers.`);
    }
    if (c.group_labels && c.group_labels.length < 2) {
      probs.push(`“${c.name}”: open groups need at least 2 labels.`);
    }
  }
  return probs;
}

// --- Edit pipeline -------------------------------------------------------------
function onEdit() {
  const doc = buildDoc();
  $("b-json").value = JSON.stringify(doc, null, 2);
  refreshReads();
  // Barriers to generation are ALWAYS visible in the Try-it card — a fresh
  // session lists exactly what the theme still needs instead of staying mute.
  const err = $("b-error");
  const probs = [...new Set(localProblems(doc))];
  err.hidden = probs.length === 0;
  err.textContent = probs.length
    ? "To generate, this theme still needs:\n" + probs.map((x) => "· " + x).join("\n")
    : "";
  $("b-status").textContent = probs.length
    ? (docIsEmpty(doc) ? "Start typing — the file and phrasing previews build as you go." : "")
    : "Looks consistent — try a preview, then download.";
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
    $("b-status").innerHTML = `<span class="ok">Valid theme — unique, logic-solvable puzzle generated.</span>`;
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

// --- Init: a stored theme if you have one, otherwise a blank slate --------------
(function init() {
  let doc = null;
  try {
    const stored = localStorage.getItem(STORE_KEY);
    if (stored) doc = JSON.parse(stored);
  } catch (e) { /* start blank */ }
  if (doc) {
    docToState(doc);
  } else {
    cats = [blankCat(), blankCat()]; // the minimum viable shape: two empty categories
  }
  renderCats();
  onEdit();

  $("b-name").addEventListener("input", onEdit);
  $("b-desc").addEventListener("input", onEdit);
  $("b-noun").addEventListener("input", onEdit);
  $("b-add-cat").addEventListener("click", () => { cats.push(blankCat()); renderCats(); onEdit(); });
  $("b-download").addEventListener("click", download);
  $("b-upload").addEventListener("click", () => $("b-file").click());
  $("b-file").addEventListener("change", (e) => { if (e.target.files[0]) upload(e.target.files[0]); e.target.value = ""; });
  $("b-generate").addEventListener("click", generatePreview);
  $("b-play").addEventListener("click", play);
})();
