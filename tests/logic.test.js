"use strict";

// Unit tests for the grid-interaction logic in public/logic.js.
// Run with:  node --test
const test = require("node:test");
const assert = require("node:assert/strict");
const {
  lineHasEqElsewhere, nextState, derive, makeHistory, nextStateGroup, deriveGroup,
} = require("../public/logic.js");

// 0 = blank, 1 = "=", 2 = "×"
const grid = (n) => Array.from({ length: n }, () => new Array(n).fill(0));
const tap = (M, a, b) => { M[a][b] = nextState(M, a, b); }; // simulate one click
const countEq = (row) => row.filter((v) => v === 1).length;

test("lineHasEqElsewhere: detects an = elsewhere in the row or column", () => {
  const M = grid(4);
  M[1][2] = 1; // an "=" at (1,2)
  assert.equal(lineHasEqElsewhere(M, 1, 0), true, "same row");
  assert.equal(lineHasEqElsewhere(M, 3, 2), true, "same column");
  assert.equal(lineHasEqElsewhere(M, 1, 2), false, "the = cell itself is excluded");
  assert.equal(lineHasEqElsewhere(M, 3, 3), false, "unrelated cell");
});

test("nextState: a free cell cycles blank → × → = → blank", () => {
  const M = grid(4);
  assert.equal(nextState(M, 0, 0), 2); tap(M, 0, 0); // blank → ×
  assert.equal(nextState(M, 0, 0), 1); tap(M, 0, 0); // × → =
  assert.equal(nextState(M, 0, 0), 0); tap(M, 0, 0); // = → blank
  assert.equal(M[0][0], 0);
});

test("nextState: a forced cell toggles auto-× ⇄ manual-× and never becomes a 2nd =", () => {
  const M = grid(4);
  M[0][0] = 1; // "=" at (0,0) forces the rest of row 0 / column 0
  // (0,1) shares row 0 -> forced. Currently blank (auto ×).
  assert.equal(nextState(M, 0, 1), 2, "auto-× → manual-×"); tap(M, 0, 1);
  assert.equal(nextState(M, 0, 1), 0, "manual-× → back to auto (not =)"); tap(M, 0, 1);
  assert.equal(M[0][1], 0);
  // it must never offer "=" while row 0 already has one
  assert.notEqual(nextState(M, 0, 1), 1);
});

test("derive: an empty grid shows nothing and nothing is lit", () => {
  const { display, lit } = derive(grid(4));
  assert.ok(display.flat().every((s) => s === 0));
  assert.ok(lit.flat().every((b) => b === false));
});

test("derive: placing an = auto-fills its row and column with dim ×", () => {
  const M = grid(4);
  M[0][0] = 1;
  const { display, lit } = derive(M);
  assert.equal(display[0][0], 1, "the = itself");
  assert.equal(display[0][2], 2, "auto-× across the row");
  assert.equal(display[3][0], 2, "auto-× down the column");
  assert.equal(lit[0][2], false, "auto-× is dim");
  assert.equal(display[2][2], 0, "cell off the line stays blank");
});

test("derive: a hand-placed × is lit (bright)", () => {
  const M = grid(4);
  M[2][3] = 2; // manual ×
  const { display, lit } = derive(M);
  assert.equal(display[2][3], 2);
  assert.equal(lit[2][3], true);
});

test("regression: a manual × stays bright after an = appears in its row", () => {
  const M = grid(4);
  tap(M, 0, 3);            // manual × at (0,3)
  assert.equal(derive(M).lit[0][3], true, "bright before the =");
  tap(M, 0, 1); tap(M, 0, 1); // place "=" at (0,1), same row
  const d = derive(M);
  assert.equal(d.display[0][1], 1, "= placed");
  assert.equal(d.lit[0][3], true, "manual × is STILL bright");
  assert.equal(d.lit[0][2], false, "the auto × beside it is dim");
});

test("regression: tapping a dim auto-× promotes it to a bright manual × (never =)", () => {
  const M = grid(4);
  tap(M, 0, 0); tap(M, 0, 0); // "=" at (0,0)
  assert.equal(derive(M).lit[0][2], false, "auto-× dim to start");
  tap(M, 0, 2);                // promote
  assert.equal(derive(M).lit[0][2], true, "now a bright manual ×");
  tap(M, 0, 2);                // toggle back
  assert.equal(derive(M).lit[0][2], false, "dim auto-× again");
  assert.equal(M[0][2], 0, "and it never became an =");
});

test("invariant: no row or column can ever hold two =", () => {
  const M = grid(4);
  tap(M, 1, 1); tap(M, 1, 1); // "=" at (1,1)
  // Try hard to force a second "=" everywhere in row 1 and column 1.
  for (let c = 0; c < 4; c++) for (let k = 0; k < 3; k++) tap(M, 1, c);
  for (let r = 0; r < 4; r++) for (let k = 0; k < 3; k++) tap(M, r, 1);
  for (let r = 0; r < 4; r++) assert.ok(countEq(M[r]) <= 1, `row ${r}`);
  for (let c = 0; c < 4; c++) {
    const col = M.map((row) => row[c]);
    assert.ok(countEq(col) <= 1, `col ${c}`);
  }
});

test("auto-revert: removing an = drops only its auto ×, keeping manual ×", () => {
  const M = grid(4);
  M[1][1] = 2;                // manual × somewhere
  tap(M, 0, 0); tap(M, 0, 0); // "=" at (0,0) -> auto-× across row 0 / col 0
  assert.equal(derive(M).display[0][2], 2, "auto-× present while = is set");
  tap(M, 0, 0);               // = → blank (remove it)
  const d = derive(M);
  assert.equal(d.display[0][2], 0, "auto-× reverted to blank");
  assert.equal(d.display[1][1], 2, "manual × preserved");
  assert.equal(d.lit[1][1], true, "and still bright");
});

// --- Undo/redo history ------------------------------------------------------
const cell = (key, a, b, before, after) => [{ key, a, b, before, after }];

test("history: a single click records one undoable step", () => {
  const h = makeHistory(350);
  assert.equal(h.canUndo(), false);
  h.record(cell("0-1", 0, 0, 0, 2), "0-1-0-0", 0); // blank → ×
  assert.equal(h.size(), 1);
  assert.equal(h.canUndo(), true);
  const act = h.undo();
  assert.equal(act.cells[0].before, 0);
  assert.equal(act.cells[0].after, 2);
  assert.equal(h.canUndo(), false);
  assert.equal(h.canRedo(), true);
});

test("history: a rapid double-click (blank → × → =) coalesces to one step", () => {
  const h = makeHistory(350);
  h.record(cell("0-1", 0, 0, 0, 2), "0-1-0-0", 100); // blank → ×
  h.record(cell("0-1", 0, 0, 2, 1), "0-1-0-0", 180); // × → =  (within 350ms, same cell)
  assert.equal(h.size(), 1, "merged into a single action");
  const act = h.undo();
  assert.equal(act.cells[0].before, 0, "undo reverts straight to blank");
  assert.equal(act.cells[0].after, 1);
});

test("history: two slow clicks on the same cell stay two steps", () => {
  const h = makeHistory(350);
  h.record(cell("0-1", 0, 0, 0, 2), "0-1-0-0", 100); // blank → ×
  h.record(cell("0-1", 0, 0, 2, 1), "0-1-0-0", 600); // × → =  (gap > 350ms)
  assert.equal(h.size(), 2, "kept separate");
  assert.equal(h.undo().cells[0].after, 1, "first undo: = → ×");
  assert.equal(h.undo().cells[0].after, 2, "second undo: × → blank");
});

test("history: rapid clicks on different cells do not coalesce", () => {
  const h = makeHistory(350);
  h.record(cell("0-1", 0, 0, 0, 2), "0-1-0-0", 100);
  h.record(cell("0-1", 1, 1, 0, 2), "0-1-1-1", 150); // different cell, same instant
  assert.equal(h.size(), 2);
});

test("history: a coalesced gesture that returns to start drops to nothing", () => {
  const h = makeHistory(350);
  h.record(cell("0-1", 0, 0, 0, 2), "0-1-0-0", 100); // blank → ×
  h.record(cell("0-1", 0, 0, 2, 1), "0-1-0-0", 150); // × → =
  h.record(cell("0-1", 0, 0, 1, 0), "0-1-0-0", 200); // = → blank (full cycle)
  assert.equal(h.size(), 0, "net no-op leaves no step");
  assert.equal(h.canUndo(), false);
});

test("history: a new edit clears the redo branch", () => {
  const h = makeHistory(350);
  h.record(cell("0-1", 0, 0, 0, 2), "0-1-0-0", 100);
  h.undo();
  assert.equal(h.canRedo(), true);
  h.record(cell("0-1", 1, 1, 0, 2), "0-1-1-1", 500); // fresh edit
  assert.equal(h.canRedo(), false, "redo branch dropped");
  assert.equal(h.size(), 1);
});

test("history: bulk actions (e.g. Clear) undo every cell at once", () => {
  const h = makeHistory(350);
  const many = [
    { key: "0-1", a: 0, b: 0, before: 1, after: 0 },
    { key: "0-1", a: 1, b: 2, before: 2, after: 0 },
  ];
  h.record(many, null, 100); // null coalesceKey -> never merges
  assert.equal(h.size(), 1);
  const act = h.undo();
  assert.equal(act.cells.length, 2);
});

// --- Group grids (subject × group) ------------------------------------------
// 4 subjects, 2 groups with sizes [3, 1] (e.g. Furred holds 3, Finned holds 1).
const ggrid = () => Array.from({ length: 4 }, () => [0, 0]);
const SIZES = [3, 1];

test("group: a ✓ crosses out the rest of its row (one group per subject)", () => {
  const M = ggrid();
  M[0][0] = 1; // subject 0 in group 0
  const { display } = deriveGroup(M, SIZES);
  assert.equal(display[0][0], 1);
  assert.equal(display[0][1], 2, "other group in the row auto-crossed");
});

test("group: a column auto-crosses once it holds `size` ✓", () => {
  const M = ggrid();
  M[0][0] = 1; M[1][0] = 1; M[2][0] = 1; // group 0 is full (size 3)
  const { display } = deriveGroup(M, SIZES);
  assert.equal(display[3][0], 2, "4th subject can't be in the full group");
});

test("group: nextStateGroup won't allow a 2nd ✓ in a row or an over-full column", () => {
  const M = ggrid();
  M[0][0] = 1;
  assert.notEqual(nextStateGroup(M, SIZES, 0, 1), 1, "row already has a group");
  const M2 = ggrid();
  M2[0][1] = 1; // group 1 full (size 1)
  M2[1][1] = 2;
  assert.equal(nextStateGroup(M2, SIZES, 1, 1), 0, "× → blank, never ✓ (column full)");
});

test("group: cell cycles blank → × → ✓ when allowed", () => {
  const M = ggrid();
  assert.equal(nextStateGroup(M, SIZES, 0, 0), 2); M[0][0] = 2;
  assert.equal(nextStateGroup(M, SIZES, 0, 0), 1); M[0][0] = 1;
  assert.equal(nextStateGroup(M, SIZES, 0, 0), 0);
});

test("history: reset clears both stacks", () => {
  const h = makeHistory(350);
  h.record(cell("0-1", 0, 0, 0, 2), "0-1-0-0", 100);
  h.undo();
  h.reset();
  assert.equal(h.canUndo(), false);
  assert.equal(h.canRedo(), false);
  assert.equal(h.size(), 0);
});

test("an auto-× backed by two = (row and column) stays until both are gone", () => {
  const M = grid(4);
  M[0][0] = 1; // = forcing row 0
  M[2][2] = 1; // = forcing column 2
  // (0,2) sits in row 0 AND column 2 -> doubly forced.
  assert.equal(derive(M).display[0][2], 2, "forced ×");
  M[0][0] = 0; // remove the row's =
  assert.equal(derive(M).display[0][2], 2, "still × via the column's =");
  M[2][2] = 0; // remove the column's = too
  assert.equal(derive(M).display[0][2], 0, "now blank");
});
