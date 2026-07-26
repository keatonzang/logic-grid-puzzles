"""Pre-generate everyday puzzles into public/pool/ (static JSON, committed).

Free play used to generate on demand, and generate-and-grade is a rejection
loop: asking for the same mega 4x4 four times measured 0.8s, 4.0s, 22.0s and
33.2s. The band the player asked for is the *measured* band, so the client
re-rolls whole puzzles until one grades right — several serverless requests
deep on a bad draw. That wait lands on a first-time visitor.

This is the same trick /big already plays, pointed at the ordinary sizes: hunt
offline, ship static JSON, and let the page pick one instantly. The API stays
the fallback — for a pinned seed, a custom theme, an empty bucket, or a player
who has already played everything in one.

    python scripts/generate_pool.py --per-bucket 12
    python scripts/generate_pool.py --bands mega,giga --budget-s 1800

A *bucket* is one (theme, band, categories x items) combination, and its
puzzles are ``<theme>-<band>-<k>x<n>-<NNN>.json``. Only a candidate whose
measured band equals the requested one is kept: that keeps ``requested`` and
``difficulty`` equal, so the shared link in the address bar regenerates the
same puzzle (generation depends on the requested band, not the measured one).

Re-running only ever tops buckets up to --per-bucket, so a scheduled run
grows the pool instead of rebuilding it. The index is rebuilt from the
directory afterward.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logicgrid.webapi import THEME_SPECS, build_payload  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "public" / "pool"

BANDS = ["normal", "hard", "mega", "giga", "tera"]

# The shapes the free-play pickers actually offer: more categories allow fewer
# items, mirroring webapi._MAX_ITEMS_BY_K (and the client's MAX_ITEMS_BY_K).
SHAPES = [(3, 3), (3, 4), (3, 5), (4, 3), (4, 4), (5, 3), (5, 4)]

# Give up on a bucket after this many misses in a row. Small grids can't reach
# the top bands at all (a 3x3 has nowhere to hide a nested what-if), and there
# is no way to know which but to try.
MISS_LIMIT = 12


def bucket_key(theme: str, band: str, cats: int, items: int) -> str:
    return f"{theme}-{band}-{cats}x{items}"


def existing_counts() -> dict[str, int]:
    """How many puzzles each bucket already holds."""
    counts: dict[str, int] = {}
    for path in OUT.glob("*.json"):
        if path.name == "index.json":
            continue
        bucket = path.stem.rsplit("-", 1)[0]
        counts[bucket] = counts.get(bucket, 0) + 1
    return counts


def write_index() -> dict:
    """Rebuild index.json from the directory.

    Only *counts* are stored, never id lists: a full listing of 300-odd
    buckets would be a six-figure download before the first puzzle appears.
    Ids follow from the count, because they are sequential.
    """
    counts = existing_counts()
    index = {"buckets": dict(sorted(counts.items())), "total": sum(counts.values())}
    (OUT / "index.json").write_text(json.dumps(index))
    return index


def fill_bucket(theme: str, band: str, cats: int, items: int, want: int,
                have: int, rng: random.Random, deadline: float | None) -> int:
    """Generate up to ``want`` puzzles for one bucket. Returns how many landed."""
    bucket = bucket_key(theme, band, cats, items)
    made, misses = 0, 0
    while have + made < want and misses < MISS_LIMIT:
        if deadline is not None and time.monotonic() > deadline:
            break
        seed = rng.randrange(1, 10_000_000)
        t0 = time.monotonic()
        try:
            payload = build_payload(
                seed=seed, difficulty=band, items=items, categories=cats,
                theme=theme, hints=True,
            )
        except ValueError as exc:  # an impossible ask for this theme/shape
            print(f"  {bucket}: {exc}", flush=True)
            return made
        dt = time.monotonic() - t0
        if payload["difficulty"] != band:
            misses += 1
            print(f"  {bucket}: rolled {payload['difficulty']} in {dt:.1f}s "
                  f"(miss {misses}/{MISS_LIMIT})", flush=True)
            continue
        misses = 0
        made += 1
        path = OUT / f"{bucket}-{have + made:03d}.json"
        path.write_text(json.dumps(payload))
        print(f"  {bucket}: +{path.name} in {dt:.1f}s "
              f"({have + made}/{want})", flush=True)
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-bucket", type=int, default=8,
                    help="target puzzles per (theme, band, shape) bucket")
    ap.add_argument("--themes", default="",
                    help="comma-separated theme keys (default: all registry themes)")
    ap.add_argument("--bands", default=",".join(BANDS),
                    help=f"comma-separated bands (default: {','.join(BANDS)})")
    ap.add_argument("--shapes", default="",
                    help="comma-separated CATxITEMS (default: every offered shape)")
    ap.add_argument("--budget-s", type=float, default=None,
                    help="stop starting new work after this many seconds")
    ap.add_argument("--seed", type=int, default=None,
                    help="seed the seed-picker, for a reproducible run")
    args = ap.parse_args()

    themes = ([t.strip() for t in args.themes.split(",") if t.strip()]
              or [s.key for s in THEME_SPECS])
    bands = [b.strip() for b in args.bands.split(",") if b.strip()]
    if args.shapes:
        shapes = []
        for chunk in args.shapes.split(","):
            c, _, i = chunk.strip().partition("x")
            shapes.append((int(c), int(i)))
    else:
        shapes = SHAPES
    for band in bands:
        if band not in BANDS:
            ap.error(f"unknown band {band!r} (want one of {', '.join(BANDS)})")

    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    deadline = time.monotonic() + args.budget_s if args.budget_s else None

    counts = existing_counts()
    total_made = 0
    t0 = time.monotonic()
    # Cheapest first: bands and shapes both get more expensive down the list, so
    # a budgeted run spends itself on breadth before depth.
    plan = sorted(
        ((t, b, c, i) for t in themes for b in bands for (c, i) in shapes),
        key=lambda x: (BANDS.index(x[1]), x[2] * x[3]),
    )
    for theme, band, cats, items in plan:
        if deadline is not None and time.monotonic() > deadline:
            print("budget spent — stopping", flush=True)
            break
        bucket = bucket_key(theme, band, cats, items)
        have = counts.get(bucket, 0)
        if have >= args.per_bucket:
            continue
        made = fill_bucket(theme, band, cats, items,
                           args.per_bucket, have, rng, deadline)
        if made:
            total_made += made
            # Rewrite after every bucket, not just at the end: a run killed by
            # a workflow timeout should still leave a usable pool rather than
            # puzzles no index points at.
            write_index()

    index = write_index()
    print(f"\n{total_made} new puzzles in {time.monotonic() - t0:.0f}s; "
          f"pool now holds {index['total']} across {len(index['buckets'])} buckets",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
