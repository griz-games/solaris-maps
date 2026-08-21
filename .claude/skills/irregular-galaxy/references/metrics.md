# Measuring a map, and comparing generators

`solarismap.metrics` scores a finished map JSON on eleven statistics: six of fairness, two of
compactness, three of novelty. [METRICS.md](../../../../METRICS.md) is the full reference — what
each one counts and how to read its value. This is the working guide.

The distinction that matters against the rest of the toolkit:

| tool | question | answer shape |
| --- | --- | --- |
| `validate` | will Solaris load this file | binary, no judgement |
| `inspect` | is this the map I meant | a report a person reads |
| `metrics` | is it fair, compact, interesting | numbers a script compares across 100 maps |
| a builder's `check()` | is *this* map's imbalance inside *this* map's bands | an assertion that fails the build |

`metrics` does not replace a builder's `check()`. `check()` encodes the bands a particular map
has decided on and fails the build; `metrics` is impartial and never fails anything.

## The loop

```sh
python -m solarismap metrics out/irregular.json          # one map
python figures/montecarlo.py --generator irregular --draws 100   # a distribution
python figures/montecarlo.py --builder maps.irregular:build --draws 100 \
    --param players=10 --param stars_per_player=20 --param generator=irregular --figures
python figures/metric_figures.py out/*.json              # draw a set of maps
```

```python
from solarismap import metrics

reading = metrics.read(galaxy)                 # one expensive pass, everything caches on it
metrics.spread(metrics.contested_resources(reading))     # 0 = every player got the same
metrics.band(metrics.contested_resources(reading))       # (worst, typical, best)
```

## Three rules for reading the numbers

**1. One map is a draw, not a property of the generator.** Seed-to-seed CV runs 19–29% on most of
these statistics, which is larger than nearly every difference between generators. A number off a
single map tells you about that map. Use `montecarlo.py` before concluding anything about a
generator, and read the `seed-to-seed CV` table it prints before the medians.

**2. Read `band` before `spread`.** A spread cannot distinguish "the worst-off player has a
little" from "the worst-off player has nothing", and the difference between 0 contested resources
and 560 is the single most consequential thing the study found. `python -m solarismap metrics`
prints them side by side for this reason.

**3. `prob_better` before any percentage change.** 0.50 means indistinguishable on a single draw.
A median that moved 10% with P = 0.48 did not move.

## Fairness is a floor, not a goal

The three novelty statistics exist because a perfectly fair map can be perfectly dull, and the
easiest way to score well on all six spreads is to build something with no places in it. A
rotationally symmetric galaxy scores 0 on every spread and 0 on `situation_divergence` — perfect
fairness, no design. Watch `chokepoints_per_star` in particular: it is the statistic that falls
when a generator is made rounder and denser, and it is what a map loses when fairness is bought
carelessly.

Compactness is neither — `ticks_between_capitals` and `roundness` have no good direction and are
deliberately absent from `LOWER_IS_BETTER`, so `prob_better` will not rank conditions on them.
They are there to explain *why* the timing statistics moved.

## Unreachable stars

A grown galaxy is not one piece at the opening jump, and it is not meant to be. That would
produce infinite travel distances, and dropping them scores a badly connected map as a **fairer**
one, because the players who could not reach anything stop counting.

`read()` measures travel at `connect_level` — the lowest hyperspace level at which the galaxy is
one piece — and structure (`chokepoints_per_star`) at the opening jump. Hyperspace is the first
thing anybody researches, so a star nobody can reach on tick 0 is far away, not marooned.

This is not a way to hide a severed map. Check `connected_at_start`, `connect_level` and
`marooned` in the output; a galaxy that never joins up by hyperspace 8 is reported as `SEVERED`.
That is the same failure `maps/irregular.py`'s `MAX_CONNECT_HYPERSPACE` band asserts on, and the
answer is the same — another seed.

## What to do with a bad result

| Result | Means | Try |
| --- | --- | --- |
| `contested NR` band starts at 0 | somebody has no contested ground at all | a fairness pass over the neutrals, or another seed |
| `fronts` spread high | somebody borders five rivals and somebody borders one | `randomise.front_plan` with a `target_open`, walled with `corridor_bias` |
| `chokepoints per star` near 0 | dense relative to the jump range; every route is redundant | a wider lattice pitch, or a lower starting hyperspace |
| `starting vision` spread high | one pod sits next to a black hole and another does not | `randomise.balance_vision` |
| high CV on everything | the generator is inconsistent, not bad | a rejection sampler: generate, measure, discard the bad draws |

That last row is the study's own conclusion. For five of six fairness constraints, picking a good
seed mattered more than picking a generator — which makes "generate 20 and keep the best by
`metrics.summary`" a bigger lever than another balancing pass.
