---
name: solaris-map
description: Build, validate, measure and draw custom galaxy maps for the game Solaris. Use when creating or editing a map builder in maps/, when working with a custom galaxy JSON (stars/players/carriers), when a map needs checking against Solaris's rules, when rendering a map to SVG, or when reasoning about hyperspace range, scanning range, star resources, specialists or map balance.
---

# Building Solaris maps

A map is a JSON file Solaris loads at Create Game → Galaxy Type `Custom`. It is built by a
Python script in `maps/`, not by hand: hand-editing 900 stars is how invariants break.

## The loop

```sh
python maps/<name>.py                          # build; it validates as it writes
python -m solarismap validate out/<name>.json  # exit 1 if Solaris would reject it
python -m solarismap inspect  out/<name>.json  # balance, spacing, reach, scanning
python -m solarismap metrics  out/<name>.json  # fairness, compactness, novelty
python -m solarismap render   out/<name>.json -o out/<name>.svg
```

Start a new map by copying `maps/example.py` — a working 25-star, 4-player map, short enough
to read in one go. `maps/spy_v_spy.py` is the full-size one: 909 stars, 36 players, nine
galaxies on a ring.

## Two different questions

Keep these apart; conflating them is how a technically-valid unplayable map ships.

- **`validate` — will Solaris load this?** Field types, the hard limits, the semantic rules.
  Binary answer, no judgement. A map must always pass.
- **`inspect`, `metrics` and the builder's own checks — is this the map I meant?** Are the
  players balanced, is anything marooned, is contested ground actually equidistant. Judgement
  required, and the builder is where map-specific invariants belong. Look at
  `report()` in `maps/example.py` and `check()` in `maps/spy_v_spy.py` for the pattern:
  compute the property, print it, and fail the build if it is wrong. `metrics` is the
  impartial half of this: eleven statistics that score any map without knowing what it
  meant to be, and never fail anything. See [METRICS.md](../../../METRICS.md).

## Rules that are not negotiable

Run `python -m solarismap rules` for the full table, or `--json` to consume it. The ones
that bite most often:

- **1500 stars maximum.** Player count is not a setting — Solaris counts stars with
  `homeStar: true`. `starsPerPlayer` is `starCount / playerLimit`, so 36 players caps at
  41 stars each.
- **Every home star needs a `playerId`,** and the player claiming it via `homeStarId` must be
  that same player.
- **Unowned stars must have 0 ships.**
- **A dead star** — natural resources summing to 0 — may not carry infrastructure, a
  specialist or a warp gate.
- **Specialists must be flagged `active.custom`.** All 18 star specialists are; of the 21
  carrier specialists, Joker is not.
- **Star names are 3–30 characters** if set at all. Shorter passes the editor and fails Solaris.
- **Carriers need ≥ 1 ship.** Their waypoints are wasted effort: outside tutorial games
  Solaris truncates them.
- **Wormholes** need a target that exists and is not the star itself. Solaris tolerates
  one-way links; the editor does not, so use `model.link_wormhole(a, b)`, which does both ends.
- **IDs are strings.** `"1"`, not `1`.

Distances are in world units, and one light year is 50 of them. A carrier at hyperspace *h*
jumps `(h + 1.5) * 50`; a star at scanning *s* sees `(s + 1) * 50`. They are not the same
formula — do not reuse one for the other.

## The package

`solarismap/`, standard library only, imported by every builder:

| Module | Use it for |
| --- | --- |
| `rules` | ranges, terraforming, dead stars, effective scanning, the limits |
| `geometry` | `polar`, `rotate`, `mirror`, `dist`, spacing, `connected_hops`, `scanned_by` |
| `model` | `new_star`, `set_resources`, `make_home_star`, `link_wormhole`, `new_player`, `assign_ids`, `galaxy`, `write` |
| `validate` | `validate(data).raise_for_errors()` |
| `inspect` | `report(data)` — the same numbers the CLI prints |
| `metrics` | `summary(data)` — fairness spreads, compactness, novelty; `read(data)` first if you want them one at a time |
| `render` | `draw(data, options, annotate_over=...)` |
| `specialists` | `by_name("Telescope Array")`, `scanning_bonus(id)`, `is_custom_star_specialist(id)` |

Never write a star dict by hand — `model.new_star()` emits every required field, and fields
you add starting with `_` are scratch, stripped on write. Never hand-edit
`solarismap/specialists.json`; it is generated.

See [references/authoring.md](references/authoring.md) for the factory-by-factory walkthrough
and the symmetry techniques, and [references/troubleshooting.md](references/troubleshooting.md)
for what each validator error means.

## Drawing a map

`python -m solarismap render` handles any map with no map-specific knowledge. Useful flags:
`--labels` (star ids), `--scan` (scanning ranges), `--hyperspace-circles`, `--focus X,Y,R` to
crop to one region.

For callouts on top, pass `annotate_under` / `annotate_over` hooks to `render.draw` — each
takes a context and yields SVG strings, with the primitives and lookups on the context so a
hook imports nothing. `render_figures()` in `maps/spy_v_spy.py` is the worked example.

## Hooks in this repo

A map JSON written or edited directly is validated automatically, and a turn will not end
with an invalid map in `out/`. If either fires, fix the map — do not work around the hook.
