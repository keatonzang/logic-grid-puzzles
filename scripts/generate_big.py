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

_SPEC = re.compile(r"^(\d+)x(\d+):(normal|hard|mega|giga|tera):(\d+)((?::[gd])*)$")


def parse_spec(text: str) -> tuple[int, int, str, int, bool, int]:
    """(categories, items, band, count, groups, n_ordered) from a spec.
    Flags: :g rolls group hierarchies, :d a second sequential dial."""
    m = _SPEC.match(text.strip())
    if not m:
        raise argparse.ArgumentTypeError(
            f"bad spec {text!r} (want CATxITEMS:BAND:COUNT[:g][:d], e.g. 4x6:mega:2:d)"
        )
    flags = set(m[5].replace(":", ""))
    if flags >= {"g", "d"}:
        raise argparse.ArgumentTypeError(
            f"{text!r}: no registry theme carries flavor groups AND two dials"
        )
    return (int(m[1]), int(m[2]), m[3], int(m[4]),
            "g" in flags, 2 if "d" in flags else 1)


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


# Ordered-logic phrasing, for bundles from before exact sequential-clue
# counts were stored — a text heuristic good enough for a catalog tag.
_SEQ_HINT = re.compile(
    r"higher|lower|more than|less than|immediately|between .+ and|"
    r"at least .+ more|at most|away from|ranks",
    re.IGNORECASE,
)


def _group_blocks(bundle: dict) -> int:
    default = bundle["themes"][bundle["default_theme"]]
    return sum(
        len(c.get("groups", [])) + len(c.get("supergroups", []))
        for c in default["categories"]
    )


def _group_categories(bundle: dict) -> int:
    default = bundle["themes"][bundle["default_theme"]]
    return sum(1 for c in default["categories"] if c.get("groups"))


def _sequential_clues(bundle: dict) -> int:
    if "sequential_clues" in bundle:
        return bundle["sequential_clues"]
    default = bundle["themes"][bundle["default_theme"]]
    return sum(1 for c in default["clues"] if _SEQ_HINT.search(c))


def rebuild_index() -> int:
    bundles = []
    for path in sorted(OUT.glob("*.json")):
        if path.name == "index.json":
            continue
        bundles.append(json.loads(path.read_text()))
    # family = the root puzzle a variant's solution came from; every member
    # lists its siblings so the catalog can cross-link them
    members: dict[str, list] = {}
    for b in bundles:
        members.setdefault(b.get("family") or b["id"], []).append(b["id"])
    entries = []
    for b in bundles:
        family = b.get("family") or b["id"]
        entries.append({
            "id": b["id"],
            "categories": b["categories"],
            "items": b["items"],
            "difficulty": b["difficulty"],
            "grouped": b.get("grouped", False),
            "nested": b.get("nested", False),
            "has_ordered": b.get("has_ordered", False),
            "adjusted": b.get("adjusted", False),
            "family": family,
            "siblings": [pid for pid in members[family] if pid != b["id"]],
            # our big puzzles always carry exactly one ordered category when
            # has_ordered — a safe backfill for bundles predating the field
            "group_categories": b.get("group_categories", _group_categories(b)),
            "sequential_categories": b.get(
                "sequential_categories", 1 if b.get("has_ordered") else 0
            ),
            "group_blocks": b.get("group_blocks", _group_blocks(b)),
            "sequential_clues": _sequential_clues(b),
            # older bundles predate the counter — the phrasing is distinctive
            "cross_dial_clues": b.get("cross_dial_clues", sum(
                "whoever has the" in c
                for c in b["themes"][b["default_theme"]]["clues"]
            )),
            "clue_count": len(b["themes"][b["default_theme"]]["clues"]),
            "themes": {key: t["name"] for key, t in b["themes"].items()},
        })
    entries.sort(key=lambda e: (e["categories"] * e["items"], e["id"]))
    OUT.joinpath("index.json").write_text(json.dumps(
        {"themes": bigpuzzles.theme_capabilities(), "puzzles": entries}, indent=1
    ))
    return len(entries)


_DERIVE = re.compile(r"^([a-z0-9-]+):((?:normal|hard|mega|giga|tera)(?:,(?:normal|hard|mega|giga|tera))*)$")


def parse_derive(text: str) -> tuple[str, list[str]]:
    m = _DERIVE.match(text.strip())
    if not m:
        raise argparse.ArgumentTypeError(
            f"bad derive {text!r} (want PARENT_ID:BAND[,BAND...], "
            "e.g. 5x5-tera-001:mega,hard)"
        )
    return m[1], m[2].split(",")


def run_derive(parent_id: str, targets: list[str]) -> None:
    src = OUT / f"{parent_id}.json"
    bundle = json.loads(src.read_text())
    print(f"{parent_id}: replaying its walk to derive {','.join(targets)} ...",
          flush=True)
    t0 = time.monotonic()
    variants = bigpuzzles.derive_variants(bundle, targets)
    for target, theme_obj, variant, report in variants:
        pid = next_id(bundle["categories"], bundle["items"], report["band"])
        out = bigpuzzles.bundle_candidate(
            pid, bundle["seed"], bundle["requested"], theme_obj, variant,
            report, donor=bundle["default_theme"],
            family=bundle.get("family") or bundle["id"],
            derived_from=bundle["id"],
        )
        OUT.joinpath(f"{pid}.json").write_text(json.dumps(out, indent=1))
        print(f"{pid}: adjusted {report['band']} from {parent_id} | "
              f"{len(out['themes'][out['default_theme']]['clues'])} clues",
              flush=True)
    missed = set(targets) - {t for t, *_ in variants}
    if missed:
        print(f"{parent_id}: note — {','.join(sorted(missed))} not exactly "
              "reachable from this parent", flush=True)
    print(f"{parent_id}: derivation done in {time.monotonic() - t0:.0f}s",
          flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=parse_spec, action="append", default=[],
                    help="CATxITEMS:BAND:COUNT[:g], repeatable")
    ap.add_argument("--derive", type=parse_derive, action="append", default=[],
                    help="PARENT_ID:BAND[,BAND...] — downgraded same-solution "
                         "variants of a shipped puzzle, repeatable")
    args = ap.parse_args()
    if not args.spec and not args.derive:
        ap.error("nothing to do: pass --spec and/or --derive")
    OUT.mkdir(parents=True, exist_ok=True)

    for parent_id, targets in args.derive:
        run_derive(parent_id, targets)

    for cats, items, band, count, groups, n_ordered in args.spec:
        donor = bigpuzzles.pick_donor(groups, n_ordered)
        for _ in range(count):
            seed = bigpuzzles.random_seed()
            t0 = time.monotonic()
            print(f"{cats}x{items} {band}: generating (seed {seed}, "
                  f"groups={groups}, dials={n_ordered}) ...", flush=True)
            # Ship EVERY logic-solvable candidate the walk grades — at these
            # shapes each attempt costs minutes-to-hours, so a mega that
            # rolled while hunting a giga is a puzzle, not waste. Ids carry
            # the MEASURED band.
            candidates = bigpuzzles.generate_big_all(
                seed, band, cats, items, ordered=n_ordered, groups=groups,
                donor=donor
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
