# The generators

All six take the same call and return a `Layout`, so a builder can swap one for another by name.

```python
from solarismap import generate

layout = generate.generate("irregular", player_count=12, stars_per_player=30,
                           seed="anything", starting_stars=4, hyperspace=2,
                           separation=50.0)
layout.points        # list[(x, y)] - every star
layout.homes         # list[int] - index into points, one capital per player
layout.starting      # list[list[int]] - per player, their non-capital starting stars
layout.owners()      # {point index: player index} for everything anyone starts on
layout.seed          # the seed used, including one chosen for you
```

Unknown keyword arguments are swallowed (`**_`), so passing `spread=1.6` to `circular` is
harmless. That is what lets a builder offer `--generator` over all six without special-casing.

## Shared arguments

| Argument | Default | Effect |
| --- | --- | --- |
| `player_count` | - | capitals, and therefore Solaris's `playerLimit` |
| `stars_per_player` | - | total stars is the product of the two |
| `seed` | random | any string; recorded on the Layout either way |
| `starting_stars` | 1 | stars per player *including* the capital |
| `hyperspace` | 1 | the opening jump; drives step 9 and capital seating |
| `separation` | `rules.MIN_STAR_SEPARATION` (50) | the spacing floor |

## Lattice generators: `irregular`, `irregular_n_limit`

| Argument | Default | Effect |
| --- | --- | --- |
| `spread` | `None` | lattice pitch as a multiple of `separation * 0.75`. **The important one** - see the SKILL's "one number". `None` fits it to the opening jump via `fit_spread`; a float overrides. Lower means denser and better connected, higher means sparser and more void |
| `overshoot` | 1.3 | how many more stars the lattice makes than are kept. Below ~1.15 the noise prune has nothing to choose from and the voids disappear |
| `falloff` | 8.0 | metaball edge sharpness. Lower spreads the galaxy into a soft cloud; higher gives a hard outline with a bulge where capitals cluster |
| `min_neighbours` / `max_neighbours` | 3 / 5 | `irregular_n_limit` only: how many rivals a capital may be lattice-adjacent to |

`noise_spread(stars_per_player)` sets the feature size of the void field and scales with density
so a 40-stars-per-player map does not come out as lace. Override it by editing the call, not by
a parameter - it is upstream's formula and worth keeping as one.

**On `spread` and `EDITOR_SPREAD`.** Upstream has no configurable spread at all: `irregular.ts`
hardcodes `const SPREAD = 2.5` inside `generateLocations`, and uses it at every hyperspace level.
That is the one upstream constant not carried over as a default, because it is the difference
between a playable map and an unplayable one - at hyperspace 1 or 2 it leaves some capitals with
*zero* neutral stars in their opening jump. `EDITOR_SPREAD` keeps the value for anyone who wants
the upstream layout; `fit_spread(hyperspace, separation)` derives the usable one, and that is
what `None` selects. `fit_spread`'s `headroom` argument (0.8) is the discount for ring-2 slots
the noise prune deletes, measured at the default `overshoot`; if you prune harder, lower it.

**`irregular_n_limit` vs `irregular`.** Free growth can seat a player with one lattice neighbour
or with five, and a one-neighbour player has a much quieter opening. N-limit carves capitals out
of a hex grid instead, culling most of each capital's neighbours so the count stays in the band.
Two fix-up rounds swap stragglers into culled holes. When the queue dries up it restarts from a
cell *touching the existing cluster*, reviving a culled one if it must - restarting from the
nearest free cell anywhere seats one player in exile across a gap.

## Field generators: `circular`, `doughnut`

Rejection sampling - throw a dart, keep it if it clears `separation`. Uniform in expectation and
**lumpy in fact**: without help, roughly one map in three seats somebody in a sparse patch. That
is what `place_homes(..., reach=...)` exists for; see below. `_STAR_DENSITY` (1.3e-4, upstream's)
fixes the radius for a given star count so galaxies of different sizes feel equally crowded.

`circular`'s radius sampler is `max_radius * u ** 0.5`. The exponent is inferred from upstream's
default offset of 0.5 - the value that makes area density uniform - rather than read off the
source. Below 0.5 crowds the middle.

## `spiral`

| Argument | Default | Effect |
| --- | --- | --- |
| `arms` | 2 | more arms means more, thinner corridors |

Pipeline is spiral → simplex roughening → **scale → relax**, in that order. Scaling sets the
mean gap and relaxing enforces the floor; done the other way round the scale-down undoes the
relax and stars end up inside the floor again. Radius grows as `sqrt(index)` so stars do not
bunch at the hub. `_SPIRAL_ANGLE_STEP` is one turn per ~28 stars - not upstream, which exposes a
distance and an angle factor.

## `circular_balanced`

The only symmetric generator here. Places one star per sector of angle `TAU / player_count` and
copies it into every other sector, so each player faces an exact rotation of what their
neighbours face. Capitals are the same slot in every sector, which is why `_balanced_homes`
snaps to a rotation boundary.

Reach for it when you want guaranteed fairness with no design. Reach for `irregular` when you
want a galaxy with places in it.

## Capital placement: `place_homes`

`circular`, `doughnut` and `spiral` produce no capitals - upstream applies its
`playerDistribution` setting afterwards, and `place_homes` is that step plus two fixes upstream
does not have.

- `circular` spaces ideal capitals evenly around a ring and snaps each onto a real star.
- `random` picks at random, never closer than the ring would have put them.

The ring radius is the **median** star radius from the centroid, not half the outer radius. On a
disc the two are close; on a doughnut half the outer radius is inside the hole, and every
capital snaps onto whatever scraps of inner rim are nearest.

Given a `reach`, each capital is chosen from the `shortlist` (12) stars nearest the ideal point,
preferring the one with the most neighbours within one jump - trading a little ring regularity
for an opening every player can use. A minimum separation of 0.6 × the ring chord is enforced
throughout: two capitals drifting together is worse than a thin patch, because the pair fight
each other from turn one while everybody else builds.

## Reusable pieces

Useful on their own, including in a hand-placed map:

| Function | Does |
| --- | --- |
| `Rng(seed)` | deterministic stream; `random`, `integer`, `between`, `angle`, `shuffle` |
| `noise2d(rng)` | 2D simplex field, roughly [-1, 1] |
| `hex_rings(base, rings, distance)` | concentric hex rings on a triangular grid |
| `metaball_field(p, centres, radius, falloff)` | blob field strength; ≥ 1.0 is inside |
| `jitter(points, threshold, rng)` | knock points off a lattice |
| `prune_by_noise(points, keep, noise, spread)` | keep the lowest, carving connected voids |
| `relax_separation(points, sep, pinned, rounds)` | push overlaps apart, best effort |
| `claim_starting_stars` / `pull_into_range` | the pod assignment, usable standalone |

## Porting notes

Line-by-line ports: `circular`, `doughnut`, `circular_balanced`, `irregular`, and the shared
tail (`claim_starting_stars`, `pull_into_range`, `_towards`, the hex-ring and ring-count
arithmetic).

Re-derived from structure and comments rather than transcribed: `spiral`'s stage parameters, and
`irregular_n_limit`'s capital selection.

Not reproduced, deliberately:

- `helper.getClosestLocations` excludes candidates sharing *either* coordinate with the
  reference (`a.x !== loc.x && a.y !== loc.y`) rather than excluding the reference itself.
  Mostly latent upstream, since jitter runs first and exact float equality is unlikely.
- `irregular.ts::_generateHomeLocations` evaluates its noise rejection inside the loop over
  existing capitals, so it cannot fire for the first one and consumes an attempt per capital
  examined.
- The metaball prune can leave fewer points than the noise prune needs, and upstream silently
  ships a smaller galaxy. Here the strongest-field points are put back until the count is met.
