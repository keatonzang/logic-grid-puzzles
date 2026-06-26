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

  return { lineHasEqElsewhere, nextState, derive };
});
