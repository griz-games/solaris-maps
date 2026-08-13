---
description: Validate, measure and render a map, and say whether it is any good
argument-hint: [path to map json, defaults to the newest in out/]
allowed-tools: Bash(python -m solarismap:*), Bash(python maps/:*), Read
---

Check the map at **$ARGUMENTS**. If no path was given, use the most recently modified
`out/*.json`.

```sh
python -m solarismap validate <map>
python -m solarismap inspect  <map>
python -m solarismap render   <map> -o <map basename>.svg
```

Then report, in this order:

1. **Valid or not.** If not, the errors, and what in the builder produced them — the fix
   belongs in `maps/*.py`, not in the JSON.
2. **What the numbers say.** Read the inspect output rather than repeating it: per-player
   spread in stars, ships and resources; anything unreachable; stars packed below the 50u
   floor; whether there is contested ground at all. Say which of these look deliberate and
   which look like accidents.
3. **What Solaris will override** — player limit, stars per player, `splitResources` — since
   those come from the map, not from the Create Game form.
4. **The SVG path**, so it can be opened.

If everything is clean, say so plainly and keep it short. A map that passes does not need
five paragraphs.
