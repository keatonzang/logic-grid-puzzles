"""Generate big-puzzle bundles into public/big/ (static JSON, committed).

Run offline — locally or by .github/workflows/big-puzzles.yml — because these
shapes take minutes-to-hours of generate-and-grade each; that cost is the
whole reason the big page serves pre-built files.

    python scripts/generate_big.py --spec 4x6:mega:2 --spec 3x8:giga:1:g

Spec: CATxITEMS:BAND:COUNT[:g] — ':g' generates with group hierarchies
(nested automatically at 6+ items). Each puzzle gets a fresh random seed
(recorded in its bundle) and a sequential id like ``4x6-mega-003``; the
index at public/big/index.json is rebuilt from the directory afterward, so
re-running only ever adds.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from logicgrid import bigpuzzles  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "public" / "big"

_SPEC = re.compile(r"^(\d+)x(\d+):(normal|hard|mega|giga|tera):(\d+)(:g)?$")


def parse_spec(text: str) -> tuple[int, int, str, int, bool]:
    m = _SPEC.match(text.strip())
    if not m:
        raise argparse.ArgumentTypeError(
            f"bad spec {text!r} (want CATxITEMS:BAND:COUNT[:g], e.g. 4x6:mega:2)"
        )
    cats, items, band, count = int(m[1]), int(m[2]), m[3], int(m[4])
    return cats, items, band, count, bool(m[5])


def next_id(cats: int, items: int, band: str) -> str:
    stem = f"{cats}x{items}-{band}-"
    taken = {
        int(p.stem[len(stem):])
        for p in OUT.glob(f"{stem}*.json")
        if p.stem[len(stem):].isdigit()
    }
    n = 1
    while n in taken:
        n += 1
    return f"{stem}{n:03d}"


def rebuild_index() -> int:
    entries = []
    for path in sorted(OUT.glob("*.json")):
        if path.name == "index.json":
            continue
        b = json.loads(path.read_text())
        default = b["themes"][b["default_theme"]]
        entries.append({
            "id": b["id"],
            "categories": b["categories"],
            "items": b["items"],
            "difficulty": b["difficulty"],
            "grouped": b.get("grouped", False),
            "nested": b.get("nested", False),
            "has_ordered": b.get("has_ordered", False),
            "clue_count": len(default["clues"]),
            "themes": {key: t["name"] for key, t in b["themes"].items()},
        })
    entries.sort(key=lambda e: (e["categories"] * e["items"], e["id"]))
    OUT.joinpath("index.json").write_text(json.dumps(entries, indent=1))
    return len(entries)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=parse_spec, action="append", required=True,
                    help="CATxITEMS:BAND:COUNT[:g], repeatable")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    for cats, items, band, count, groups in args.spec:
        donor = bigpuzzles.GROUP_DONOR if groups else bigpuzzles.DONOR
        for _ in range(count):
            seed = bigpuzzles.random_seed()
            t0 = time.monotonic()
            print(f"{cats}x{items} {band}: generating (seed {seed}, "
                  f"groups={groups}) ...", flush=True)
            # Ship EVERY logic-solvable candidate the walk grades — at these
            # shapes each attempt costs minutes-to-hours, so a mega that
            # rolled while hunting a giga is a puzzle, not waste. Ids carry
            # the MEASURED band.
            candidates = bigpuzzles.generate_big_all(
                seed, band, cats, items, ordered=True, groups=groups, donor=donor
            )
            took = time.monotonic() - t0
            for theme_obj, puzzle, report in candidates:
                pid = next_id(cats, items, report["band"])
                bundle = bigpuzzles.bundle_candidate(
                    pid, seed, band, theme_obj, puzzle, report, donor
                )
                OUT.joinpath(f"{pid}.json").write_text(json.dumps(bundle, indent=1))
                tag = "" if report["band"] == band else f" (byproduct of a {band} hunt)"
                print(
                    f"{pid}: measured {bundle['difficulty']}{tag} | "
                    f"{len(bundle['themes'])} themes | "
                    f"{len(bundle['themes'][bundle['default_theme']]['clues'])} clues",
                    flush=True,
                )
            print(f"{cats}x{items} {band}: walk done — "
                  f"{len(candidates)} puzzle(s) in {took:.0f}s", flush=True)

    total = rebuild_index()
    print(f"index rebuilt: {total} puzzles", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
