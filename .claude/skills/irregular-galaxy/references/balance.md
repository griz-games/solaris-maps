# Balancing a galaxy that has no symmetry

On a symmetric map fairness is a *proof*: every player's start is congruent to every other, so
there is nothing to measure. Delete the symmetry and that proof is gone, and nothing replaces
it. Balance becomes something you build in and then bound.

The mistake to avoid is treating the generated layout as the finished map and then arguing about
whether it is fair enough. It will not be. Grown layouts are unfair in specific, predictable
ways, and each one has a specific answer.

## The three imbalances, and what fixes each

### 1. Unequal openings — fix by construction

Nothing about a player's first few turns should depend on where the generator seated them.
Capitals and starting stars get **fixed values**, not values read off the layout:

```python
model.set_resources(capital, CAPITAL_NR)          # same for every player
model.make_home_star(capital, pid, ships=CAPITAL_SHIPS, **CAPITAL_INFRASTRUCTURE)
```

Then assert it, because it is the load-bearing half of the fairness story and a change to the
neutral resource curve can break it without breaking anything else:

```python
openings = {pid: (sum(...naturalResources...), sum(...shipsActual...))
            for pid, mine in owned.items()}
assert len(set(openings.values())) == 1
```

### 2. Rich and poor neighbourhoods — fix with one impartial rule

Price every neutral star by the same function of its position. `maps/irregular.py` passes the
capitals to `randomise.randomise_resources` as `anchors` with a negative `RADIUS_WEIGHT`, so the
roll is biased by distance to the *nearest* capital — poor at a capital's doorstep, rich far from
one, normalised against the furthest any star sits from its nearest anchor so the weight means
the same thing at any galaxy size.

The shape is a design decision, not a formality. Poor at home and rich in no-man's-land means
sitting still loses and the good ground is ground two players can both reach. Invert it — a
positive weight — and you get turtling. Set it to zero and position stops mattering.

### 3. Rim versus centre — fix by rebalancing

This is the one with no impartial answer. A capital on the rim of the blob has **less galaxy
around it** than one in the middle. No pricing rule fixes a difference in how much there *is*,
and on a grown map it is the dominant imbalance. On the default 12-player map the best-placed
player starts with about 60% more wealth within three jumps than the worst — a 0.46 spread.

`randomise.balance_by_channel` nudges neutral stars up or down until every player's three-jump
neighbourhood is worth about the same. Per channel, not on the sum: once the channels are split,
equal totals stop being enough, because a player whose neighbourhood is all industry and no
science is behind on research however healthy the sum looks.

```text
for each channel, for a few dozen rounds:
    totals[p] = sum of neutral values within horizon of capital p
    target    = mean(totals)
    for each neutral star:
        pulling = the capitals that can reach it
        factor  = geometric mean over pulling of (target / totals[p])
        value  *= 1 + (factor - 1) * 0.5           # damped
        clamp value to [NR_MIN, NR_MAX]
```

Three details carry the weight:

- **Geometric mean, not arithmetic.** A star inside several players' horizons is pulled by all
  of them; the geometric mean settles a star contested by a poor player and a rich one somewhere
  sensible instead of oscillating.
- **Damping at 0.5.** Undamped, one very poor player slams every shared star to the ceiling in a
  single pass and the next pass slams them back.
- **Clamping to `NR_MIN..NR_MAX`.** A badly enough seated player cannot be compensated all the
  way, and that residue is real. `check` bounds it rather than hiding it; if the band fails, the
  seat is bad and the answer is a different seed.

It converges in well under the round budget. Only neutral stars move, so run it *after*
players are assigned and the fixed opening survives untouched.


## The bands

Every band is a spread across players expressed as a fraction of the mean, and every one is a
judgement call rather than a rule of the game.

| Metric | What a bad value means | Default |
| --- | --- | --- |
| opening options | boxed in by their own pod; unrecoverable | min 2, spread ≤ 1.00 |
| reachable wealth (3 jumps) | rim seating not fully compensated | spread ≤ 0.45 |
| capital isolation | forced early war, or a free build-up | spread ≤ 0.90 |
| joins up by | a sealed pocket, dead weight in the star budget | hyperspace 6 |
| nearest-neighbour gap | stars overlapping on screen | ≥ 30u |

Set them where the intended configuration clears them with room to spare. **A failing band is
the map telling you the seed seated somebody badly — change the seed.** Widen a band only when
you have decided that kind of imbalance belongs in the map you are making. About 9 seeds in 10
pass on the default configuration (22 of 24 measured); that is the workflow, not a defect.

## What is *not* worth asserting

- **Full connectivity at the opening jump.** A grown galaxy is not one piece at the opening jump
  and is not meant to be — the voids are the point, and a map that were connected would have had
  them filled in. Assert instead that everything opens up by some modest level.
- **Equal star counts per player beyond the start.** Nobody owns anything but their pod at
  tick 0. What matters is what is *reachable*, which is the wealth band.
- **Capital isolation on `irregular`.** Capitals sit on a perfect triangular lattice, so the
  spread is exactly 0.00. The check earns its keep on the other generators and on the N-limit
  restart path; leave it in, but do not read anything into it passing.

## Diagnosing a failure

| Message | Means | Try |
| --- | --- | --- |
| `a player has only N neutral stars in their first jump` | ring 2 is outside the opening jump | you have hardcoded `spread` - drop it and let `fit_spread` track `hyperspace`, or lower it by hand |
| `galaxy is still in pieces at hyperspace 6` | the noise prune severed it | another seed; or lower `spread`, or raise `overshoot` |
| `reachable wealth spread is …` | rim seating beyond what clamping can fix | another seed; or widen `NR_MAX` so there is headroom to compensate |
| `capital isolation spread is …` | capitals unevenly spaced | a field generator without `reach` passed to `place_homes`, or an N-limit restart |
| `closest two stars are …` | jitter or the pull pass overlapped a pair | `relax_separation` with the pods pinned |
| `players do not have identical openings` | the resource curve leaked into owned stars | rebalance neutrals only, after assignment |

## Reading the map, not the numbers

Every check above is necessary and none is sufficient. They prove a galaxy is not obviously
unfair; they say nothing about whether it is any good. Render it and look at it:

```sh
python maps/irregular.py --render
python -m solarismap render out/irregular.json -o out/look.svg --labels --scan
```

Things only the picture shows: a chokepoint every route funnels through, two players sharing a
frontier with a third who has none, a void that splits the map into halves that never
meaningfully interact, a rich cluster that decides the game for whoever is nearest.
