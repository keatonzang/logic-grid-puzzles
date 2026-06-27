"""The step-by-step hint engine: a sound, explained trace and next_hint()."""

from __future__ import annotations

import random

import pytest

from logicgrid.deduce import N, U, Y, Board, board_solution
from logicgrid.generate import generate_puzzle, generate_rated
from logicgrid.hint import TIER_NAMES, next_hint, trace
from logicgrid.webapi import build_cafe_theme, build_hint, build_puzzle


def _apply(theme, steps) -> Board:
    """Replay an explained trace onto a fresh board."""
    b = Board(theme)
    for s in steps:
        i, j = (int(x) for x in s["key"].split("-"))
        b.set(i, s["a"], j, s["b"], Y if s["value"] == 1 else N)
    return b


def _agrees(theme, board, solution) -> bool:
    """Every determined cell matches the true solution (soundness)."""
    n, k = theme.n, theme.k
    ent = {(c, solution[e][c]): e for e in range(n) for c in range(k)}
    for (i, j), m in board.cell.items():
        for a in range(n):
            for b in range(n):
                if m[a][b] == U:
                    continue
                want = Y if ent[(i, a)] == ent[(j, b)] else N
                if m[a][b] != want:
                    return False
    return True


def _known_from_solution(theme, solution) -> dict:
    """A fully-filled player board (every ✓/✗) for a known solution."""
    n, k = theme.n, theme.k
    ent = {(c, solution[e][c]): e for e in range(n) for c in range(k)}
    known = {}
    for i in range(k):
        for j in range(i + 1, k):
            known[f"{i}-{j}"] = [
                [1 if ent[(i, a)] == ent[(j, b)] else 2 for b in range(n)]
                for a in range(n)
            ]
    return known


def test_trace_is_always_sound(plain_theme):
    # Like the deductive solver, the trace is sound on every puzzle (each step
    # matches the true solution) and completes on the large majority — only rare
    # puzzles needing techniques beyond what-if (tier 5+) fall short, exactly as
    # deduce.solve does. (The product path, generate_rated, is band-filtered to
    # always be solvable — see test_rated_traces_fully_solve.)
    solved = 0
    for s in range(15):
        p = generate_puzzle(plain_theme, random.Random(s), difficulty="medium")
        board = _apply(plain_theme, trace(plain_theme, p.clues))
        assert _agrees(plain_theme, board, p.solution), f"steps must be sound (seed {s})"
        solved += board.solved()
    assert solved >= 10


@pytest.mark.parametrize("target", ["easy", "medium", "hard"])
def test_rated_traces_fully_solve(target):
    for s in range(6):
        theme, puzzle, _ = generate_rated(
            lambda r: build_cafe_theme(r, 4), random.Random(s), target
        )
        board = _apply(theme, trace(theme, puzzle.clues))
        assert board.solved(), f"rated {target} puzzle should trace to a full solve"
        assert board_solution(board) == puzzle.solution


def test_trace_steps_are_well_formed(plain_theme):
    p = generate_puzzle(plain_theme, random.Random(1), difficulty="medium")
    seen = set()
    for s in trace(plain_theme, p.clues):
        assert s["value"] in (1, 2)
        assert s["link"] is (s["value"] == 1)
        assert s["tier"] in TIER_NAMES
        assert s["tier_name"] == TIER_NAMES[s["tier"]]
        assert s["text"].strip()
        cell = (s["key"], s["a"], s["b"])
        assert cell not in seen, "each cell is explained at most once"
        seen.add(cell)


def test_first_hint_on_empty_board_is_a_given(plain_theme):
    p = generate_puzzle(plain_theme, random.Random(0), difficulty="medium")
    step = next_hint(plain_theme, p.clues, known={})
    assert step["tier"] == 0
    assert step["tier_name"] == "Given"


def test_next_hint_skips_cells_already_known(plain_theme):
    p = generate_puzzle(plain_theme, random.Random(3), difficulty="medium")
    full = trace(plain_theme, p.clues)
    # Tell the engine the first ten deductions are already on the board.
    known: dict = {}
    for s in full[:10]:
        known.setdefault(s["key"], [[0] * plain_theme.n for _ in range(plain_theme.n)])
        known[s["key"]][s["a"]][s["b"]] = s["value"]
    step = next_hint(plain_theme, p.clues, known)
    early = {(s["key"], s["a"], s["b"]) for s in full[:10]}
    assert (step["key"], step["a"], step["b"]) not in early


def test_next_hint_done_on_solved_board(plain_theme):
    p = generate_puzzle(plain_theme, random.Random(4), difficulty="medium")
    known = _known_from_solution(plain_theme, p.solution)
    assert next_hint(plain_theme, p.clues, known) == {"done": True}


def test_hard_trace_uses_a_contradiction_step():
    theme, puzzle, report = generate_rated(
        lambda r: build_cafe_theme(r, 4), random.Random(2), "hard"
    )
    assert report["ceiling"] == 4
    steps = trace(theme, puzzle.clues)
    whatif = [s for s in steps if s["tier"] == 4]
    assert whatif, "a hard puzzle's trace should include a what-if step"
    assert all(s["tier_name"] == "What-if" for s in whatif)
    assert _apply(theme, steps).solved()


def test_sequential_price_trace_is_sound():
    theme, puzzle, _ = generate_rated(
        lambda r: build_cafe_theme(r, 4, categories=4, use_price=True),
        random.Random(7),
        "medium",
    )
    board = _apply(theme, trace(theme, puzzle.clues))
    assert board.solved()
    assert board_solution(board) == puzzle.solution


def test_build_hint_is_deterministic_and_grounded():
    # Same seed + params -> same puzzle -> same first hint.
    a = build_hint(3, "medium", 4, 3, known={})
    b = build_hint(3, "medium", 4, 3, known={})
    assert a == b
    assert a["tier"] == 0  # nothing known yet -> a given

    # The hint targets a real, correct cell of the regenerated puzzle.
    theme, puzzle, _r, _s = build_puzzle(3, "medium", 4, 3)
    i, j = (int(x) for x in a["key"].split("-"))
    ent = {
        (c, puzzle.solution[e][c]): e
        for e in range(theme.n)
        for c in range(theme.k)
    }
    want = Y if ent[(i, a["a"])] == ent[(j, a["b"])] else N
    assert (Y if a["value"] == 1 else N) == want


def test_build_hint_done_when_board_complete():
    theme, puzzle, _r, _s = build_puzzle(11, "medium", 4, 3)
    known = _known_from_solution(theme, puzzle.solution)
    assert build_hint(11, "medium", 4, 3, known) == {"done": True}
