"""Backfill contradiction chains into existing big-puzzle bundles.

Bundles from before hints_v=2 shipped what-if hint steps without their
"suppose X ... contradiction" chains (the server builds those lazily from
live board context, which static JSON doesn't have). Hints can only be
rebuilt from live clue objects, so each unique WALK is replayed once and
every bundle it produced is re-bundled in place — same ids, same families,
fresh hints (and every newer bundle field along the way).

    python scripts/backfill_hints.py [--max-items N]

--max-items bounds the walk cost per lane (items drive n!^(k-1)), so cheap
shapes can backfill in one lane while a second handles the heavy ones.
Bundles already at hints_v >= 2 are skipped; run again after long-running
generation lanes drain to catch their output.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logicgrid import bigpuzzles  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "public" / "big"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-items", type=int, default=99)
    ap.add_argument("--min-items", type=int, default=0)
    args = ap.parse_args()

    stale: dict[tuple, list] = {}
    for path in sorted(OUT.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            b = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        if b.get("hints_v", 1) >= 2:
            continue
        if not (args.min_items <= b["items"] <= args.max_items):
            continue
        key = (b["seed"], b["requested"], b["categories"], b["items"],
               b["default_theme"])
        stale.setdefault(key, []).append(b)

    print(f"{sum(len(v) for v in stale.values())} bundles across "
          f"{len(stale)} walks need chains", flush=True)

    for (seed, requested, cats, items, donor), bundles in sorted(
        stale.items(), key=lambda kv: kv[0][3]  # cheapest (fewest items) first
    ):
        t0 = time.monotonic()
        print(f"walk {cats}x{items} {requested} seed {seed}: replaying for "
              f"{len(bundles)} bundle(s) ...", flush=True)
        try:
            cands = bigpuzzles.generate_big_all(
                seed, requested, cats, items,
                ordered=bundles[0].get("sequential_categories",
                                       1 if bundles[0].get("has_ordered") else 0),
                groups=donor == bigpuzzles.GROUP_DONOR, donor=donor,
            )
        except Exception as exc:  # keep the sweep going; report and move on
            print(f"walk seed {seed}: replay failed: {exc}", flush=True)
            continue
        by_solution = {}
        for theme_obj, puzzle, report in cands:
            key = tuple(map(tuple, bigpuzzles._solution_rows(theme_obj, puzzle.solution)))
            by_solution[key] = (theme_obj, puzzle, report)
        for b in bundles:
            want = tuple(map(tuple, b["themes"][donor]["solution"]))
            got = by_solution.get(want)
            if got is None:
                print(f"{b['id']}: no candidate matches its solution — skipped",
                      flush=True)
                continue
            theme_obj, puzzle, report = got
            if b.get("adjusted"):
                res = bigpuzzles.downgrade(theme_obj, puzzle, b["difficulty"])
                if res is None:
                    print(f"{b['id']}: downgrade replay missed — skipped", flush=True)
                    continue
                puzzle, report = res
            fresh = bigpuzzles.bundle_candidate(
                b["id"], b["seed"], b["requested"], theme_obj, puzzle, report,
                donor=donor, family=b.get("family"),
                derived_from=b.get("derived_from"),
            )
            OUT.joinpath(f"{b['id']}.json").write_text(json.dumps(fresh, indent=1))
            print(f"{b['id']}: chains baked", flush=True)
        print(f"walk seed {seed}: done in {time.monotonic() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
