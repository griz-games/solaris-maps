#!/usr/bin/env python3
"""Stop hook: no turn ends with an invalid map sitting in out/.

Sweeps every out/*.json and blocks with the failures if any of them would be
rejected by Solaris. Exits 0 when `stop_hook_active` is set - without that guard
a blocking Stop hook re-triggers itself forever.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    # Already inside a stop triggered by this hook: let the turn end.
    if payload.get("stop_hook_active"):
        return 0

    out_dir = REPO / "out"
    if not out_dir.is_dir():
        return 0

    try:
        from solarismap import validate
    except ImportError:
        return 0

    broken: list[tuple[Path, list[str]]] = []
    for path in sorted(out_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("stars"), list):
            continue
        report = validate.validate(data)
        if not report.ok:
            broken.append((path, report.errors))

    if not broken:
        return 0

    print("out/ holds map(s) Solaris would reject:", file=sys.stderr)
    for path, errors in broken:
        print(f"\n{path.name}  ({len(errors)} error(s))", file=sys.stderr)
        for error in errors[:10]:
            print(f"  - {error}", file=sys.stderr)
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more", file=sys.stderr)
    print("\nFix them, or delete the file if it was scratch.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        print(f"validate_out hook failed: {exc}", file=sys.stderr)
        sys.exit(0)
