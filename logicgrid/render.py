"""Console rendering: clue list, blank pairwise grids, and the solution table."""

from __future__ import annotations

from .generate import Puzzle
from .model import Theme


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    sep = "-+-".join("-" * w for w in widths)
    out = [" | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)), sep]
    for row in rows:
        out.append(" | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
    return "\n".join(out)


def render_clues(puzzle: Puzzle) -> str:
    lines = ["CLUES", "====="]
    for i, clue in enumerate(puzzle.clues, 1):
        lines.append(f"{i:>2}. {clue.text(puzzle.theme)}")
    return "\n".join(lines)


def render_solution(puzzle: Puzzle) -> str:
    theme, X = puzzle.theme, puzzle.solution
    headers = [c.name for c in theme.categories]
    rows = []
    for e in range(theme.n):
        rows.append([theme.categories[c].items[X[e][c]] for c in range(theme.k)])
    return "SOLUTION\n========\n" + _table(headers, rows)


def _short(label: str, width: int) -> str:
    return label if len(label) <= width else label[: width - 1] + "."


def render_grids(puzzle: Puzzle, solved: bool = False) -> str:
    """Pairwise grids for every pair of categories.

    Blank for solving; with X (linked) / . (not linked) marks when `solved`.
    A compact stand-in for the interlocked staircase grid.
    """
    theme, X = puzzle.theme, puzzle.solution
    n, k = theme.n, theme.k
    cell_w = 3
    blocks = []
    for c1 in range(k):
        for c2 in range(c1 + 1, k):
            cat1, cat2 = theme.categories[c1], theme.categories[c2]
            row_label_w = max(len(it) for it in cat1.items)
            header_cells = [_short(it, cell_w).center(cell_w) for it in cat2.items]
            header = " " * (row_label_w + 1) + " ".join(header_cells)
            title = f"{cat1.name}  x  {cat2.name}"
            lines = [title, header]
            for e1 in range(n):
                cells = []
                for e2 in range(n):
                    if solved:
                        # entity carrying item e1 in cat1 vs item e2 in cat2
                        ent1 = next(e for e in range(n) if X[e][c1] == e1)
                        ent2 = next(e for e in range(n) if X[e][c2] == e2)
                        mark = "X" if ent1 == ent2 else "."
                    else:
                        mark = "_"
                    cells.append(mark.center(cell_w))
                lines.append(cat1.items[e1].ljust(row_label_w) + " " + " ".join(cells))
            blocks.append("\n".join(lines))
    heading = "GRID (solved)" if solved else "GRID (blank — fill while solving)"
    return heading + "\n" + "=" * len(heading) + "\n\n" + "\n\n".join(blocks)


def render_puzzle(puzzle: Puzzle, show_solution: bool = False, grid: bool = True) -> str:
    theme = puzzle.theme
    parts = [theme.name, "=" * len(theme.name)]
    if theme.description:
        parts.append(theme.description)
    parts.append("")
    parts.append(render_clues(puzzle))
    if grid:
        parts.append("")
        parts.append(render_grids(puzzle, solved=False))
    if show_solution:
        parts.append("")
        parts.append(render_solution(puzzle))
        if grid:
            parts.append("")
            parts.append(render_grids(puzzle, solved=True))
    return "\n".join(parts)
