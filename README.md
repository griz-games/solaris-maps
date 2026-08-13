# solaris-map

A command-line toolkit for building custom galaxy maps for
[Solaris](https://github.com/solaris-games/solaris), and drawing them with the game's own art.

Maps are Python scripts. The toolkit gives them Solaris's rules and measurements, factories
that emit the exact JSON the game accepts, validation that says whether it will actually
load, and a renderer for looking at the result.

Python 3.10+, standard library only. Nothing to install.

## The loop

```sh
python maps/spy_v_spy.py                            # build (validates as it writes)
python -m solarismap validate out/spy_v_spy.json    # will Solaris load it?
python -m solarismap inspect  out/spy_v_spy.json    # is it the map you meant?
python -m solarismap render   out/spy_v_spy.json -o out/spy_v_spy.svg
```

Then paste the JSON into Solaris at Create Game → Galaxy Type `Custom`. Its **Validate**
button runs the real server-side validator; `solarismap validate` reimplements it so you find
out sooner. To look at a map in a real editor, the
[public custom galaxy editor](https://ihateattackmaps.github.io/solaris-custom-galaxy-editor/)
takes the same JSON.

## Starting a new map

Copy `maps/example.py` — a complete 25-star, 4-player map, short enough to read at a sitting.
Its geometry is deliberately dull; what it demonstrates is the sequence.

```python
from solarismap import geometry, model, rules, validate

stars = [model.new_star(geometry.polar(400, a)) for a in (0, 120, 240)]
model.assign_ids(stars)                            # ids are strings, assigned once
for n, star in enumerate(stars, start=1):
    model.set_resources(star, 25)
    model.make_home_star(star, str(n), ships=10)

players = [model.new_player(str(n), s["id"]) for n, s in enumerate(stars, start=1)]
data = model.galaxy(stars, players)
validate.validate(data).raise_for_errors()         # refuse to ship a map Solaris rejects
model.write("out/my_map.json", data)
```

`maps/spy_v_spy.py` is the real one: 909 stars, 36 players, nine galaxies on a ring linked by
wormholes, every contested star equidistant from the two players contesting it. Run it with
`--render` for the annotated figures, or `--galaxies 2` for an 8-player cut.

## Commands

| | |
| --- | --- |
| `python -m solarismap validate <map>` | Solaris-parity validation. Exit 1 if it would be rejected. |
| `python -m solarismap inspect <map>` | balance, spacing, reachability, scanning, terrain. `--json` for machines. |
| `python -m solarismap render <map>` | SVG using the game's art. `--labels`, `--scan`, `--focus X,Y,R`. |
| `python -m solarismap rules` | constants, formulas, hard limits, specialists. `--json` for machines. |
| `python -m solarismap sync-specialists <path>` | regenerate the specialist table from an editor checkout. |
| `python tests/test_solarismap.py` | 110 checks over the rules math and the validator. |
| `python docs/publish.py` | copy built figures into the site. `--check` exits 1 if it is stale. |

## Two different questions

`validate` answers *will Solaris load this file*. It says nothing about whether the map is
worth playing. `inspect` — and the invariants each builder checks for itself — answer *is this
the map I meant*: are the players balanced, is anything marooned, is the contested ground
genuinely contested. A map needs both, and they fail in different ways.

## The package

`solarismap/` — `rules` (ranges, terraforming, dead stars, the limits Solaris enforces),
`geometry` (points, spacing, reachability, scan queries), `model` (star/player/carrier
factories and the writer), `validate`, `inspect`, `render`, and `specialists`.

`solarismap/specialists.json` is generated from the editor's store, never hand-edited. The art
in `solarismap/assets/` is vendored from the same place — see
[ATTRIBUTION.md](solarismap/assets/ATTRIBUTION.md), which carries the game-icons.net credits
the icon license requires.

## The site

`docs/` is the write-up site GitHub Pages serves: `index.html` (a single file — no build step,
no dependencies), `maps.json` as its catalogue, one Markdown file per map under `content/`, and
generated figures in `assets/`.

The builders and the site are deliberately kept apart, and the arrow points one way:

```text
maps/spy_v_spy.py --render   →   out/spy_v_spy.svg          builders name things their way
                                 out/spy_v_spy_targets.json
docs/publish.py              →   docs/assets/spy-v-spy-map.svg    the site names things its way
                                 docs/assets/spy-v-spy-map.json
```

A builder never writes into `docs/`, and the site never reaches into `out/`. `docs/publish.py`
is the only thing that spans them; it reads the `figure` key in `maps.json` to know which built
figure belongs to which page. Everything in `docs/assets/` is generated — edit the builder and
re-publish, never the asset.

Adding a map to the site is a catalogue entry plus a Markdown file: give it a `slug`, point
`content` at the write-up, point `figure` at the basename the builder wrote in `out/`, then
embed the figure with `![zoom:](assets/<slug>-map.svg)`. The `zoom:` prefix is what turns a
plain image into the pan/zoom viewer; the `-map.json` sidecar next to it supplies the per-galaxy
jump buttons, and the viewer works without it if a map has none.

```sh
python maps/spy_v_spy.py --render   # build the map and its figures
python docs/publish.py              # carry them into the site
python -m http.server -d docs       # preview on localhost:8000
```

Preview over HTTP rather than opening `index.html` directly — the page uses `fetch()`, which
browsers block on `file://` URLs.

## Rules worth knowing before you design

Full table from `python -m solarismap rules`; the ones that shape a design:

- **1500 stars maximum**, and player count is *not* a setting — Solaris counts stars with
  `homeStar: true` and derives `starsPerPlayer` from that. 36 players caps at 41 stars each.
- **One light year is 50 world units.** A carrier at hyperspace *h* jumps `(h + 1.5) × 50`;
  a star at scanning *s* sees `(s + 1) × 50`.
- **Dead stars** — resources summing to zero — may not hold infrastructure, a specialist or a
  warp gate. **Unowned stars must have no ships.**
- **Specialists must be flagged `active.custom`**; all 18 star specialists are.
- **Colour and shape are cosmetic.** Solaris reassigns them.

## Working with agents

`.claude/` carries a `solaris-map` skill, `/newmap` and `/checkmap` commands, and two hooks:
a map JSON written or edited directly is validated immediately, and a turn cannot end with an
invalid map in `out/`.

## Licence

GPL-3.0, as a derivative of Solaris and of the
[custom galaxy editor](https://github.com/IHateAttackMaps/solaris-custom-galaxy-editor) this
repository was forked from. See [LICENSE](LICENSE).
