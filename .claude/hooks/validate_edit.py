#!/usr/bin/env python3
"""PostToolUse hook: validate a map JSON that was just written or edited.

Map builders validate on write, so this covers the gap they cannot: a map JSON
edited directly, by hand or by an agent, and then left invalid. Exits 2 with the
validator's complaint on stderr, which is what feeds the problem back rather
than letting it pass silently.

Anything that is not a custom galaxy is none of this hook's business - a missing
file, unparseable JSON, or a JSON file with no `stars` array all exit 0.
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
        return 0

    path_text = (payload.get("tool_input") or {}).get("file_path")
    if not path_text:
        return 0

    path = Path(path_text)
    if path.suffix.lower() != ".json" or not path.exists():
        return 0

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return 0
    if not isinstance(data, dict) or not isinstance(data.get("stars"), list):
        return 0

    try:
        from solarismap import validate
    except ImportError:
        return 0

    report = validate.validate(data)
    if report.ok:
        return 0

    print(f"{path.name} is not a map Solaris will load "
          f"({len(report.errors)} error(s)):", file=sys.stderr)
    for error in report.errors[:20]:
        print(f"  - {error}", file=sys.stderr)
    if len(report.errors) > 20:
        print(f"  ... and {len(report.errors) - 20} more", file=sys.stderr)
    print(f"\nRun: python -m solarismap validate {path}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                  # noqa: BLE001
        # A broken hook must never wedge the session; say so and get out of the way.
        print(f"validate_edit hook failed: {exc}", file=sys.stderr)
        sys.exit(0)
