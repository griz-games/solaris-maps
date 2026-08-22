# solaris-map

A command-line toolkit for building custom galaxy maps for
[Solaris](https://github.com/solaris-games/solaris), and drawing them with the game's own art.

Maps are Python scripts. The toolkit gives them Solaris's rules and measurements, factories
that emit the exact JSON the game accepts, generators that grow a galaxy when you would rather
not place one, validation that says whether it will actually load, statistics that say whether
it is any good, and a renderer for looking at the result.

Python 3.10+, standard library only. Nothing to install.

## The loop

```sh
python maps/spy_v_spy.py                            # build (validates as it writes)
python -m solarismap validate out/spy_v_spy.json    # will Solaris load it?
python -m solarismap inspect  out/spy_v_spy.json    # is it the map you meant?
python -m solarismap metrics  out/spy_v_spy.json    # is it fair, compact, interesting?
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

## Placed maps and grown ones

Both maps above are *placed*: a wedge is built once and rotated, so every player's start is the
same start by construction, and fairness is inherited rather than arranged. That is the safe
way, and it costs a map its landmarks — a rotationally symmetric galaxy has no unique place in
it, because every place exists N times.

`solarismap.generate` is the other half — the editor's six generators (`circular`, `doughnut`,
`circular_balanced`, `spiral`, `irregular`, `irregular_n_limit`) ported to Python, which grow a
star field with no symmetry at all. `solarismap.randomise` then decides what each star *is*:
resources, terrain in regions rather than salt-and-pepper, wormholes. Fairness on a grown map
has to be arranged and then measured, and `maps/irregular.py` is the worked example — 200 stars,
10 players, identical openings by construction, neutral stars priced by distance from the
nearest capital, and a `check()` that bounds distributions because it has no congruence to
assert.

```sh
python maps/irregular.py [--seed S] [--generator NAME] [--players N] [--render]
```

A seed reproduces *this* toolkit's galaxy, not the editor's: the two npm dependencies with no
standard library equivalent are reimplemented faithfully but not bit-compatibly.

## Commands

| | |
| --- | --- |
| `python -m solarismap validate <map>` | Solaris-parity validation. Exit 1 if it would be rejected. |
| `python -m solarismap inspect <map>` | balance, spacing, reachability, scanning, terrain. `--json` for machines. |
| `python -m solarismap metrics <map>` | eleven fairness, compactness and novelty statistics. `--json` for machines. |
| `python -m solarismap render <map>` | SVG using the game's art. `--labels`, `--scan`, `--focus X,Y,R`. |
| `python -m solarismap rules` | constants, formulas, hard limits, specialists. `--json` for machines. |
| `python -m solarismap sync-specialists <path>` | regenerate the specialist table from an editor checkout. |
| `python tests/test_solarismap.py` | 164 checks over the rules math, the validator and the statistics. |
| `python docs/publish.py` | copy built figures into the site. `--check` exits 1 if it is stale. |

## Three different questions

`validate` answers *will Solaris load this file*. It says nothing about whether the map is
worth playing. `inspect` — and the invariants each builder checks for itself — answer *is this
the map I meant*: are the players balanced, is anything marooned, is the contested ground
genuinely contested. A map needs both, and they fail in different ways.

`metrics` answers a third, impartial question — *is it fair, compact, interesting* — with
eleven statistics that score any map without knowing what it was meant to be, and that never
fail anything. [METRICS.md](METRICS.md) explains what each one measures and how to read it.
The short version: a statistic off one map is a draw, not a property of the generator that
made it, so a claim about a generator needs a distribution.

## The package

`solarismap/` — `rules` (ranges, terraforming, dead stars, the limits Solaris enforces),
`geometry` (points, spacing, reachability, scan queries), `model` (star/player/carrier
factories and the writer), `generate` (the six layout generators), `randomise` (resources,
terrain, wormholes), `metrics`, `validate`, `inspect`, `render`, and `specialists`.

`solarismap/specialists.json` is generated from the editor's store, never hand-edited. The art
in `solarismap/assets/` is vendored from the same place — see
[ATTRIBUTION.md](solarismap/assets/ATTRIBUTION.md), which carries the game-icons.net credits
the icon license requires.

## The studies

`figures/` runs the statistics over many maps instead of one, and writes up what comes back.
[FRONTS.md](FRONTS.md) is the finished one: 8,000 thirty-two-player irregular galaxies built
the way the live game builds them, split into three arms — the status quo, the same generator
with the maps picked for fewest fronts, and the `irregular_n_limit` redesign that caps how many
neighbours a capital may have — and measured against all eleven statistics. Its headline is
that drawing two galaxies and keeping the fairer beats redesigning the generator, and drawing
twenty gets you five times as far.

```sh
python figures/fronts_study.py --pilot 240              # acceptance rate first
python figures/fronts_study.py --target 1000            # → out/fronts_study.ndjson
python figures/fronts_md.py                             # → FRONTS.md and its figures
python figures/fronts_report.py                         # → out/fronts_report.html, all eleven
```

The study deliberately does *not* use `maps/irregular.py`'s pipeline, which adds a fairness
layer the game does not have. The question it asks is what the game itself produces.

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

`.claude/` carries two skills — `solaris-map` for maps that are placed, `irregular-galaxy` for
maps that are grown — `/newmap` and `/checkmap` commands, and two hooks: a map JSON written or
edited directly is validated immediately, and a turn cannot end with an invalid map in `out/`.

## Licence

GPL-3.0, as a derivative of Solaris and of the
[custom galaxy editor](https://github.com/IHateAttackMaps/solaris-custom-galaxy-editor) this
repository was forked from. See [LICENSE](LICENSE).
