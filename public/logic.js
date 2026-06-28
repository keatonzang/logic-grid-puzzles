"use strict";

// Pure grid-interaction logic, shared by the browser UI (window.LG) and the
// Node test suite (require). No DOM access lives here so it can be unit-tested.
//
// A grid's state is a 2D `manual` array M[a][b] of the user's intent:
//   0 = blank   1 = "=" (link)   2 = "×" (no-link)
// Displayed × marks are *derived*: any blank cell sharing a row or column with
// an "=" shows an auto "×". The rules enforced here:
//   * at most one "=" per row and per column (a bijection),
//   * an auto × renders dim, a hand-placed × renders bright,
//   * removing an "=" reverts only the auto marks it implied.
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.LG = api;
})(typeof self !== "undefined" ? self : this, function () {
  // True if some *other* cell in (a,b)'s row or column already holds an "=".
  // Such a cell is forced to × and can't itself become a second "=".
  function lineHasEqElsewhere(M, a, b) {
    const rows = M.length;
    const cols = M[0].length;
    for (let c = 0; c < cols; c++) if (c !== b && M[a][c] === 1) return true;
    for (let r = 0; r < rows; r++) if (r !== a && M[r][b] === 1) return true;
    return false;
  }

  // The manual value a cell takes when tapped.
  //   Free cell (no "=" in its line):  blank → × → = → blank
  //   Forced cell (line has an "="):   dim auto-× ⇄ bright manual-×  (never a 2nd "=")
  function nextState(M, a, b) {
    const cur = M[a][b];
    const canLink = !lineHasEqElsewhere(M, a, b);
    if (cur === 0) return 2;
    if (cur === 2) return canLink ? 1 : 0;
    return 0; // cur === 1 ("=") → blank
  }

  // Displayed state for every cell, plus which × marks render bright.
  //   display[a][b] ∈ {0,1,2}
  //   lit[a][b]     = true  → a hand-placed × (bright); auto × stay dim.
  function derive(M) {
    const rows = M.length;
    const cols = M[0].length;
    const rowHasEq = new Array(rows).fill(false);
    const colHasEq = new Array(cols).fill(false);
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (M[r][c] === 1) { rowHasEq[r] = true; colHasEq[c] = true; }
      }
    }
    const display = [];
    const lit = [];
    for (let r = 0; r < rows; r++) {
      display.push([]);
      lit.push([]);
      for (let c = 0; c < cols; c++) {
        const forced = rowHasEq[r] || colHasEq[c];
        const state = M[r][c] !== 0 ? M[r][c] : forced ? 2 : 0;
        display[r].push(state);
        lit[r].push(M[r][c] === 2); // bright iff the user placed this × by hand
      }
    }
    return { display, lit };
  }

  // --- Undo/redo history ----------------------------------------------------
  // A small, DOM-free action stack so undo/redo can be unit-tested. An *action*
  // is a list of cell changes: `{cells: [{key,a,b,before,after}], t, coalesceKey}`.
  // A single click is one action over one cell; a hint or "clear" is one action
  // over many. Rapid repeat clicks on the *same* cell (e.g. a double-click that
  // runs blank → × → =) coalesce into a single action so undo reverts the whole
  // gesture at once, while two deliberate, slower clicks stay two actions.
  //
  // The caller owns the board: `record` only logs intent, and `undo`/`redo`
  // hand back the action so the caller can re-apply `before`/`after` itself.
  // `now` is passed in (performance.now in the browser) so tests stay deterministic.
  function makeHistory(coalesceMs) {
    let undo = [];
    let redo = [];

    function record(cells, coalesceKey, now) {
      redo = []; // any fresh edit invalidates the redo branch
      if (coalesceKey && cells.length === 1) {
        const last = undo[undo.length - 1];
        if (
          last &&
          last.coalesceKey === coalesceKey &&
          last.cells.length === 1 &&
          last.cells[0].after === cells[0].before &&
          now - last.t <= coalesceMs
        ) {
          last.cells[0].after = cells[0].after; // extend the gesture's end state
          last.t = now;
          if (last.cells[0].before === last.cells[0].after) undo.pop(); // net no-op
          return;
        }
      }
      undo.push({ cells, t: now, coalesceKey: coalesceKey || null });
    }

    return {
      record,
      undo() { return undo.length ? (redo.push(undo[undo.length - 1]), undo.pop()) : null; },
      redo() { return redo.length ? (undo.push(redo[redo.length - 1]), redo.pop()) : null; },
      canUndo: () => undo.length > 0,
      canRedo: () => redo.length > 0,
      size: () => undo.length, // committed steps — the "steps to solve" count
      reset() { undo = []; redo = []; },
    };
  }

  // --- Group (subject × group) grids ----------------------------------------
  // A group column is NOT a permutation: each subject is in exactly ONE group
  // (one ✓ per row) but a group holds a known number of subjects (`sizes[g]`
  // ✓ per column). So the rules are: a ✓ crosses out the rest of its row, and a
  // column auto-crosses its blanks once it already has `sizes[g]` ✓.
  function _groupCanLink(M, sizes, s, g) {
    for (let c = 0; c < M[s].length; c++) if (c !== g && M[s][c] === 1) return false;
    let ones = 0;
    for (let r = 0; r < M.length; r++) if (M[r][g] === 1) ones++;
    return ones < sizes[g];
  }

  // The value a group cell takes when clicked: blank → × → (✓ if allowed) → blank.
  function nextStateGroup(M, sizes, s, g) {
    const cur = M[s][g];
    if (cur === 0) return 2;
    if (cur === 2) return _groupCanLink(M, sizes, s, g) ? 1 : 0;
    return 0;
  }

  // Displayed state of a group grid, with auto-× for full rows/columns. `lit`
  // marks hand-placed × (bright) versus auto × (dim), mirroring `derive`.
  function deriveGroup(M, sizes) {
    const n = M.length;
    const g = sizes.length;
    const rowHasOne = new Array(n).fill(false);
    const colOnes = new Array(g).fill(0);
    for (let r = 0; r < n; r++)
      for (let c = 0; c < g; c++)
        if (M[r][c] === 1) { rowHasOne[r] = true; colOnes[c]++; }
    const display = [];
    const lit = [];
    for (let r = 0; r < n; r++) {
      display.push([]);
      lit.push([]);
      for (let c = 0; c < g; c++) {
        const forced = rowHasOne[r] || colOnes[c] >= sizes[c];
        display[r].push(M[r][c] !== 0 ? M[r][c] : forced ? 2 : 0);
        lit[r].push(M[r][c] === 2);
      }
    }
    return { display, lit };
  }

  return { lineHasEqElsewhere, nextState, derive, makeHistory, nextStateGroup, deriveGroup };
});
