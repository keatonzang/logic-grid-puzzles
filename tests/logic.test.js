"use strict";

// Unit tests for the grid-interaction logic in public/logic.js.
// Run with:  node --test
const test = require("node:test");
const assert = require("node:assert/strict");
const { lineHasEqElsewhere, nextState, derive } = require("../public/logic.js");

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
