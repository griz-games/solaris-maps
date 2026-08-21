---
name: irregular-galaxy
description: Grow an irregular or asymmetric Solaris galaxy with solarismap.generate instead of placing stars by hand. Use when a map should have no rotational symmetry - organic blobs, voids, spiral arms, uneven neighbourhoods - when working with the six ported generators (circular, doughnut, circular_balanced, spiral, irregular, irregular_n_limit), when a grown map needs balancing or checking without congruence to lean on, or when tuning seeds, lattice pitch, noise spread or metaball falloff.
---

# Growing an irregular galaxy

The `solaris-map` skill covers maps whose stars are *placed*: a wedge is built once, rotated
per player, and fairness follows from congruence. This one covers maps that are *grown*. The
star field has no symmetry, so no two players face the same galaxy and congruence is not
available as an argument. Fairness has to be arranged and then measured.

Use `solarismap.generate` (six generators ported from the editor's `src/scripts/generators/`)
and `maps/irregular.py` as the worked example. Everything in the `solaris-map` skill still
applies - the validator rules, the star cap, `model.new_star`, never hand-editing a map JSON.

## The loop

```sh
python maps/irregular.py                                   # build, check, validate, write
python maps/irregular.py --seed foo --generator spiral     # a different galaxy
python maps/irregular.py --players 20 --stars-per-player 40 --render
python -m solarismap inspect out/irregular.json
python -m solarismap metrics out/irregular.json           # fairness/compactness/novelty
python figures/montecarlo.py --generator irregular --draws 100    # over many seeds
```

A seed reproduces a galaxy exactly. **It does not reproduce the editor's galaxy for the same
seed** - the two npm dependencies (`simplex-noise`, `random-seed`) are reimplemented rather
than bit-ported, which was a deliberate choice. Reproducibility is within this repo.

## Choosing a generator

| Generator | Symmetric? | Character | Reach for it when |
| --- | --- | --- | --- |
| `irregular` | no | hex lattice, metaball outline, noise voids | the default. Organic, has places in it |
| `irregular_n_limit` | no | same, capitals bounded to 3-5 neighbours | nobody should get a quiet corner |
| `spiral` | no | arms with real chokepoints | crossing between arms should be a decision |
| `circular` | no | uniform disc, locally lumpy | a plain backdrop; least designed |
| `doughnut` | no | annulus, hollow middle | no single dominant central position |
| `circular_balanced` | **yes** | one sector rotated N times | guaranteed fairness, no design |

`circular_balanced` is the odd one out and is structurally what `maps/spy_v_spy.py` does by
hand - except a hand-built map chooses *what* sits on each midline and this cannot. If you
want symmetry, hand-place it; this module is for when you do not.

## What `irregular` actually does

Nine steps, and the order matters:

1. size the hex lattice so it overshoots the target star count by `overshoot` (1.3)
2. grow capitals outwards on a triangular lattice, rejecting spots where the noise is high
3. add supplementary lattice centres *between* capitals - this is what populates contested ground
4. fill concentric hex rings around every centre
5. **metaball prune** - drops points outside `sum((radius/d) ** falloff)`, giving the galaxy an outline
6. **jitter** every star off the lattice by 0.75-1.0x the dislocation threshold
7. **noise prune** - keeps the lowest `starCount - playerCount` in a simplex field, carving voids
8. hand each capital its `starting_stars - 1` nearest unclaimed neighbours, round robin
9. pull those stars in until each player's pod is connected at the opening jump

Steps 5 and 7 do different jobs and you need both. The metaball decides the galaxy's **shape**;
the noise decides its **texture**. Drop 5 and you get a hexagon. Drop 7 and you get an even
field with no places in it.

## The one number that decides whether it is playable

**The opening jump must cover two lattice rings.** A capital's own starting stars claim most of
ring 1, so the neutral stars it can actually open on are in ring 2, at twice the pitch. Get this
wrong and some players start boxed in by their own pod with nowhere to go on turn one.

This is handled for you: `spread` defaults to `None`, and the lattice generators call
`generate.fit_spread(hyperspace, separation)`, which solves the constraint

```text
worst-case ring-2 star = L * (2.5 * spread - 0.5)    where L = separation * 0.75
                       <= rules.hyperspace_range(hyperspace)
```

then discounts the result by 20% for the ring-2 slots the noise prune deletes. At the standard
50u separation it yields ~1.23 at hyperspace 1, 1.65 at 2, 2.08 at 3, and clamps to 2.5 from 4 up.

**The editor hardcodes `SPREAD = 2.5`** inside `generateLocations` in `irregular.ts` - not a
setting, not exposed in the Generate menu, not a parameter. It is the only value it ever uses, at
any hyperspace level, and it is why `EDITOR_SPREAD` is a documented constant here rather than a
default worth keeping. Measured over ten seeds, the fewest neutral stars any capital can reach on
turn one:

| starting hyperspace | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| `fit_spread` (default) | 4 | 6 | 7 | 5 |
| `EDITOR_SPREAD` (2.5) | **0** | **0** | 2 | 5 |

Pass `spread=generate.EDITOR_SPREAD` to reproduce the upstream layout, or any float to override.
If you hardcode one, it stops tracking `hyperspace` - which is how a map ends up validating,
rendering, and being unplayable.

## Fairness without symmetry

Three mechanisms, in the order they matter. `maps/irregular.py` implements all three.

1. **Make the opening identical by construction.** Capitals and starting stars get fixed values,
   not values read off the layout, so the first turns are exactly equal wherever a player was
   seated. Assert it - it is load bearing and a change to the resource curve can break it
   silently.
2. **Price neutral stars by one impartial rule.** Resources as a function of distance to the
   nearest capital: poor at home, rich in no-man's-land. Nobody is handed a rich neighbourhood,
   and sitting still loses.
3. **Rebalance what impartiality cannot fix.** A capital seated on the rim of the blob has less
   galaxy around it than one in the middle, and even-handed pricing does not fix a difference in
   how much *there is*. Nudge neutral values until every player's three-jump neighbourhood is
   worth about the same. On the default map this takes the wealth spread from 0.46 to 0.22.

What is left asymmetric after all three is the interesting part: where the good ground is, who
your neighbours are, where the chokepoints fall.

## What to check instead of congruence

Bands, not equalities. `check()` in `maps/irregular.py` asserts these and fails the build:

| Check | Why | Default band |
| --- | --- | --- |
| identical openings | the fairness floor | exact equality |
| every pod connected at start | a player must be able to use their own stars | hard |
| galaxy joins up by hyperspace 4 | voids are fine, sealed pockets are not | hard |
| opening options (neutrals in first jump) | boxed-in is unrecoverable | min 4, spread ≤ 0.90 |
| reachable wealth (3 jumps) | rim vs centre seating | spread ≤ 0.45 |
| capital isolation (nearest rival) | forced early war vs free build-up | spread ≤ 0.90 |
| nearest-neighbour gap | stars overlapping on screen | ≥ 30u hard floor |

**A failing band means the seed seated somebody badly. Change the seed, not the band.** Widen a
band only when you have decided that kind of imbalance belongs in the map. About 9 seeds in 10
pass on the default configuration; that is the workflow, not a defect.

Note the galaxy is *not* expected to be fully connected at the opening jump. Voids are the
point. What must not exist is a pocket that stays sealed however far players research.
`solarismap.metrics` takes the same view: it measures travel at the level where the galaxy
becomes one piece and reports that level, rather than handing back infinite distances that then
have to be dropped - dropping them scores a badly connected map as a *fairer* one.

## Gotchas

- **Step 9 ignores the rest of the galaxy.** Pulling a pod in can crowd a neutral neighbour.
  Follow it with `generate.relax_separation(points, sep, pinned=list(layout.owners()))` - pinning
  keeps the pods where reachability put them and moves the neutrals aside.
- **The lattice floor is `separation * 0.75`, upstream's choice.** Some pairs land under the
  editor's 50u guideline; that is cosmetic, not a validator rule. `inspect` counts them.
- **`relax_separation` is O(n²) per round** - the slow step past ~1000 stars.
- **Capitals in `irregular` sit on a perfect lattice**, so capital isolation spread is 0.00.
  Non-zero spread there means a different generator, or the N-limit restart path.
- **`Layout` is not a map.** It is points plus an assignment. `model` turns it into stars; the
  builder picks the resource curve. Do not put Solaris fields in a generator.
- Star cap is still 1500 and `player_count * stars_per_player` must respect it.

## References

- [references/generators.md](references/generators.md) - every generator's parameters, what each
  knob does, and how they were ported.
- [references/balance.md](references/balance.md) - the balancing method in full: the rebalancing
  algorithm, choosing bands, and diagnosing a map that fails one.
- [references/metrics.md](references/metrics.md) - scoring a finished map and comparing
  generators over many seeds, with the three rules for reading the numbers.
