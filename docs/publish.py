#!/usr/bin/env python3
"""Carry built figures out of out/ and into the site's assets.

This is the only thing that connects the map builders to the website, and it
runs in one direction. A builder writes figures into `out/` under the map's own
name and knows nothing about this file; the site reads `docs/assets/` under its
own slug-based naming and knows nothing about the builders. The mapping between
the two lives in `docs/maps.json`, in each entry's `figure` key.

For a catalogue entry with slug `spy-v-spy` and figure `spy_v_spy`:

    out/spy_v_spy.svg           ->  docs/assets/spy-v-spy-map.svg
    out/spy_v_spy_targets.json  ->  docs/assets/spy-v-spy-map.json

The sidecar is what gives the figure its per-galaxy jump buttons; the page
fetches it by swapping the .svg suffix for .json, so the pair must keep the
same basename.

Run:  python docs/publish.py            # copy, reporting what changed
      python docs/publish.py --check    # exit 1 if anything is out of date
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parent
OUT = ROOT / "out"
ASSETS = DOCS / "assets"
CATALOGUE = DOCS / "maps.json"


def entries() -> list[dict]:
    """The catalogue entries that claim a built figure."""
    data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    # The array has been spelled both ways; index.html accepts either, so this
    # does too rather than forcing a rename nobody else needs.
    maps = data.get("maps") or data.get("docs") or []
    return [m for m in maps if m.get("figure")]


def pairs(entry: dict) -> list[tuple[Path, Path]]:
    """(built file, published file) for one catalogue entry."""
    figure, slug = entry["figure"], entry["slug"]
    return [
        (OUT / f"{figure}.svg", ASSETS / f"{slug}-map.svg"),
        (OUT / f"{figure}_targets.json", ASSETS / f"{slug}-map.json"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true",
                        help="report whether the site is up to date; write nothing")
    args = parser.parse_args()

    catalogue = entries()
    if not catalogue:
        print(f"no catalogue entry in {CATALOGUE.name} names a figure - nothing to publish")
        return 0

    missing: list[Path] = []
    stale: list[Path] = []
    copied = 0

    for entry in catalogue:
        for source, target in pairs(entry):
            if not source.is_file():
                missing.append(source)
                continue
            same = (target.is_file()
                    and target.read_bytes() == source.read_bytes())
            if same:
                continue
            if args.check:
                stale.append(target)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            print(f"  {source.relative_to(ROOT)} -> {target.relative_to(ROOT)}"
                  f"  ({source.stat().st_size / 1024:.0f} KB)")
            copied += 1

    if missing:
        print("\nnot built yet:", file=sys.stderr)
        for path in missing:
            print(f"  {path.relative_to(ROOT)}", file=sys.stderr)
        print("\nBuild the map with --render first, e.g.:\n"
              "  python maps/spy_v_spy.py --render", file=sys.stderr)
        return 1

    if args.check:
        if stale:
            print("site assets are out of date:", file=sys.stderr)
            for path in stale:
                print(f"  {path.relative_to(ROOT)}", file=sys.stderr)
            print("\nRun: python docs/publish.py", file=sys.stderr)
            return 1
        print(f"site is up to date ({len(catalogue)} map(s))")
        return 0

    print(f"published {copied} file(s) for {len(catalogue)} map(s)"
          if copied else f"already up to date ({len(catalogue)} map(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
