---
description: Scaffold a new map builder from the template and run the full loop
argument-hint: <name> [one-line description of the map]
allowed-tools: Bash(python maps/:*), Bash(python -m solarismap:*), Read, Write, Edit
---

Start a new Solaris map called `$1`.

1. Read `maps/example.py`. It is the template: a working 25-star, 4-player map that already
   builds, validates and reports on itself.
2. Copy it to `maps/$1.py`. Change `OUTPUT` to `ROOT / "out" / "$1.json"` and rewrite the
   module docstring to describe this map rather than the template.
3. Shape the layout to the rest of the arguments: **$ARGUMENTS**. If nothing beyond the name
   was given, leave the template's geometry alone for now and say so — a running map is a
   better starting point than a guess at what was wanted.
4. Adapt `report()` to the invariants *this* map needs. The template checks reachability at
   the starting hyperspace level, that contested stars are equidistant, and star spacing;
   a different layout will care about different things.
5. Run it, then check it:

   ```sh
   python maps/$1.py
   python -m solarismap validate out/$1.json
   python -m solarismap inspect  out/$1.json
   python -m solarismap render   out/$1.json -o out/$1.svg
   ```

6. Report: star and player counts, resource spread between players, anything unreachable,
   and the path to the SVG. Flag any number that looks unintended rather than reporting it
   flatly — a 12% resource spread between players is a finding, not a statistic.

Do not hand-write star dictionaries; use the `model` factories. If validation fails, fix the
builder and rebuild — never patch the JSON.
