#!/usr/bin/env python3
"""Regenerate specialists.json from the editor's specialist store.

The store is a defineStore() call in TypeScript, so it cannot be imported from
Python. Rather than hand-copying the table - which is how it drifts - this reads
the source and converts the two object literals into JSON. It is hand-maintained
JS-ish syntax (unquoted keys, trailing commas, single quotes), so the conversion
below is targeted rather than pretending to be a parser for the language.

The editor is not vendored here, only its art, so point this at a clone:

    git clone https://github.com/IHateAttackMaps/solaris-custom-galaxy-editor
    python -m solarismap sync-specialists \\
        solaris-custom-galaxy-editor/src/stores/specialists.ts

specialists.json is generated. Never edit it by hand.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE / "specialists.json"


def extract_array(text: str, key: str) -> str:
    """Return the source of the `key: [ ... ]` array literal in the store state."""
    start = text.index(f"{key}: [")
    open_bracket = text.index("[", start)
    depth = 0
    in_string: str | None = None
    escaped = False
    for i in range(open_bracket, len(text)):
        ch = text[i]
        if in_string is not None:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in "'\"`":
            in_string = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return text[open_bracket:i + 1]
    raise ValueError(f"unterminated array literal for {key!r}")


def to_json(source: str) -> list[dict]:
    """Convert a JS array-of-objects literal into parsed JSON."""
    out: list[str] = []
    in_string: str | None = None
    i = 0
    while i < len(source):
        ch = source[i]

        if in_string is not None:
            if ch == "\\" and i + 1 < len(source):
                nxt = source[i + 1]
                # \' is legal in a single-quoted JS string and illegal in JSON;
                # every other escape carries over untouched.
                out.append(nxt if nxt == "'" else "\\" + nxt)
                i += 2
                continue
            if ch == in_string:
                in_string = None
                out.append('"')
                i += 1
                continue
            # A single-quoted JS string may contain a bare double quote.
            out.append('\\"' if ch == '"' else ch)
            i += 1
            continue

        if ch in "'\"":
            in_string = ch
            out.append('"')
            i += 1
            continue

        if source.startswith("//", i):                      # line comment
            i = source.index("\n", i)
            continue

        out.append(ch)
        i += 1

    text = "".join(out)
    text = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', text)   # quote keys
    text = re.sub(r",(\s*[}\]])", r"\1", text)                                  # trailing commas
    return json.loads(text)


def sync(source: Path) -> int:
    """Regenerate specialists.json from `source`. Returns a process exit code."""
    source = Path(source)
    if not source.exists():
        print(f"no such file: {source}\n\n"
              f"Point this at specialists.ts in a clone of the editor:\n"
              f"  git clone https://github.com/IHateAttackMaps/"
              f"solaris-custom-galaxy-editor\n"
              f"  python -m solarismap sync-specialists \\\n"
              f"      solaris-custom-galaxy-editor/src/stores/specialists.ts",
              file=sys.stderr)
        return 1

    text = source.read_text(encoding="utf-8")
    try:
        table = {kind: to_json(extract_array(text, kind)) for kind in ("carrier", "star")}
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"could not read the specialist table out of {source}: {exc}", file=sys.stderr)
        return 1

    TARGET.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")

    for kind, entries in table.items():
        custom = [s for s in entries if s["active"]["custom"]]
        print(f"{kind:<8} {len(entries):>3} specialists, "
              f"{len(custom):>3} usable in a custom galaxy")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m solarismap sync-specialists <specialists.ts>")
    sys.exit(sync(Path(sys.argv[1])))
