#!/usr/bin/env python3
"""Monte Carlo over the 32-player irregular galaxy, as the live game generates it.

Three arms, one sampling stream:

    A  status quo      irregular, unconstrained
    B  fronts-banded   irregular, kept only when every player has 2..9 fronts
    C  n-limit         irregular_n_limit(2,4), unconstrained

B is A conditioned on the band rather than a separate generator, so every
difference between them is attributable to the selection and to nothing else.
The acceptance rate is reported over the whole stream.

**This does not use `maps/irregular.py`'s pipeline.** That builder adds a
fairness layer the game does not have - it relaxes separation, prices neutral
stars by distance from the nearest capital, rebalances wealth per channel,
evens out terrain, and reassigns which stars each player opens with. Every one
of those changes the numbers being measured here. The question this study asks
is what the *game* produces, so the build below applies only what the game
applies, and applies it in the game's order. Provenance for each step is in the
comment beside it, naming the upstream file.

Settings come from `server/config/game/settings/official/32player_experimental.json`
and its capital-elimination twin, which are identical in every field this study
touches.

Run:  python figures/fronts_study.py --pilot 240        # measure acceptance
      python figures/fronts_study.py --target 1000      # the full run
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from solarismap import (generate, metrics, model, randomise,  # noqa: E402
                        rules, validate)

# --------------------------------------------------------------------------
# The game's own 32-player configuration
#
# Both official 32-player templates - 32player_capital_elimination.json and
# 32player_experimental.json - carry these values identically. They differ only
# in `darkGalaxy`, which no statistic here reads.
# --------------------------------------------------------------------------

PLAYERS = 32
STARS_PER_PLAYER = 20                    # galaxy.starsPerPlayer -> 640 stars
STARTING_STARS = 6                       # player.startingStars
START_HYPERSPACE = 2                     # technology.startingTechnologyLevel
START_SCANNING = 3
STARTING_SHIPS = 10                      # player.startingShips
STARTING_INFRASTRUCTURE = {"economy": 5, "industry": 5, "science": 2}
STARTING_CREDITS = 1000
STARTING_CREDITS_SPECIALISTS = 10

TECHNOLOGIES = {"terraforming": 1, "experimentation": 1, "scanning": START_SCANNING,
                "hyperspace": START_HYPERSPACE, "manufacturing": 1, "banking": 1,
                "weapons": 1, "specialists": 1}

# specialGalaxy.random* - percentages of stars, which is how the game states them.
TERRAIN_PERCENTAGES = {"isNebula": 15.0, "isAsteroidField": 10.0,
                       "isBinaryStar": 10.0, "isBlackHole": 5.0,
                       "isPulsar": 1.0, "warpGate": 10.0}
WORMHOLE_PERCENTAGE = 3.0                # specialGalaxy.randomWormHoles

# game.constants.star.resources, server/db/models/schemas/game.ts defaults.
NR_MIN = 10
NR_MAX = 50

# resource.ts::_setResources takes EXP = 0.5 on the random path, which is
# uniform. And `distribute` forces the random path for irregular regardless of
# the resourceDistribution setting:
#     const forcedRandom = ["doughnut", "irregular"].includes(galaxyType)
# so there is no radius weighting in a live irregular galaxy at all. This is the
# single largest departure from `maps/irregular.py`, which uses -0.35.
LOW_VALUE_BIAS = 0.5
RADIUS_WEIGHT = 0.0
SPLIT_RESOURCES = True                   # specialGalaxy.splitResources: enabled

# star.ts::setupHomeStar pins the capital at maxNaturalResources on all three
# channels. It is the only star the game special-cases; the five other starting
# stars keep whatever `distribute` rolled for them, which is why openings in a
# live game are *not* identical across players.
CAPITAL_NR = NR_MAX

# The target band for arm B, on metrics.fronts.
#
# Changing this does NOT require re-running the sweep: every draw stores its
# full per-player fronts, and `fronts_report.load` recomputes band membership
# from that. The values recorded here are a convenience for a single-draw read.
#
# A hard filter on the band is not reachable at any tight setting - with fronts
# measured correctly the median seat borders 5 rivals - so the acceptance rate
# is reported rather than assumed, and arm B is built by *ranking* draws on how
# far they sit from the band.
FRONTS_BAND = (2, 5)

GENERATOR = "irregular"
N_LIMIT_KWARGS = {"min_neighbours": 2, "max_neighbours": 4}


# --------------------------------------------------------------------------
# Build - the game's pipeline and nothing else
# --------------------------------------------------------------------------


def build(seed: str, generator: str = GENERATOR, **generator_kwargs) -> dict:
    """One galaxy, built the way `IrregularMapService.generateLocations` builds it.

    `spread` is left at the generator default, which is `generate.GAME_SPREAD`
    (2.5). That is `const SPREAD = 2.5` in irregular.ts - hardcoded upstream, not
    a setting, and not scaled to the hyperspace level. `generate.fit_spread`
    would give a more playable galaxy and a different one, so it stays off.
    """
    layout = generate.generate(
        generator, PLAYERS, STARS_PER_PLAYER,
        seed=seed,
        starting_stars=STARTING_STARS,
        hyperspace=START_HYPERSPACE,
        separation=rules.MIN_STAR_SEPARATION,
        **generator_kwargs,
    )

    # No relax_separation here. That is a `maps/irregular.py` addition; the game
    # ships whatever the pull-into-range pass leaves behind, overlaps included.

    properties = generate.Rng(f"{layout.seed}:properties")
    owners = layout.owners()
    capitals = {index: player for player, index in enumerate(layout.homes)}

    stars = [model.new_star(point, _player=owners.get(index))
             for index, point in enumerate(layout.points)]

    # resource.ts::distribute runs over every location, capitals included, with
    # no positional term. Uniform in [10, 50], three channels rolled
    # independently because splitResources is enabled.
    randomise.randomise_resources(stars, properties,
                                  minimum=NR_MIN, maximum=NR_MAX,
                                  low_value_bias=LOW_VALUE_BIAS,
                                  radius_weight=RADIUS_WEIGHT,
                                  anchors=None, split=SPLIT_RESOURCES)

    model.assign_ids(stars)

    players: list[dict] = []
    for player, home_index in enumerate(layout.homes):
        player_id = str(player + 1)
        # setupHomeStar: capital pinned to max resources, seeded with the
        # settings' infrastructure and ships. It overwrites whatever distribute
        # rolled, which is why this runs after randomise_resources.
        model.set_resources(stars[home_index], CAPITAL_NR)
        model.make_home_star(stars[home_index], player_id, ships=STARTING_SHIPS,
                             **STARTING_INFRASTRUCTURE)
        for star_index in layout.starting[player]:
            # Owned from tick 0, but only the capital is given ships - nothing
            # in star.ts assigns shipsActual to a linked star.
            stars[star_index]["playerId"] = player_id
        players.append(model.new_player(
            player_id, stars[home_index]["id"], technologies=TECHNOLOGIES,
            credits=STARTING_CREDITS,
            credits_specialists=STARTING_CREDITS_SPECIALISTS))

    # Scattered uniformly, one star at a time, and never rebalanced. That is
    # what the editor's Randomise menu does and what the game does; the
    # balance_terrain pass in maps/irregular.py is this repo's own.
    #
    # Wormholes first, because that is the order generateStars uses: wormholes,
    # then nebulas, asteroid fields, binaries, black holes, pulsars.
    randomise.link_wormholes(stars, properties, WORMHOLE_PERCENTAGE)
    randomise.randomise_terrain(stars, properties, **TERRAIN_PERCENTAGES)
    # And the half that was missing: map.ts does not merely flag a special star,
    # it overwrites the star's resources - science for a nebula, economy for an
    # asteroid field, industry for a binary, and a fifth of everything for a
    # black hole. Without it the special stars are ordinary stars wearing a
    # costume, and `contested_resources` is measuring the wrong galaxy.
    randomise.apply_terrain_resources(stars, properties, maximum=NR_MAX,
                                      split=SPLIT_RESOURCES)

    # No balance_by_channel, no balance_terrain, no balance_openings.
    return model.galaxy(stars, players, carriers=[])


# --------------------------------------------------------------------------
# Measure
# --------------------------------------------------------------------------


def capital_degrees(galaxy: dict) -> list[int]:
    """Lattice neighbours per capital - what arm C constrains, for contrast."""
    from solarismap import geometry
    capitals = [s for s in galaxy["stars"] if s.get("homeStar")]
    points = [geometry.star_point(c) for c in capitals]
    degrees = [0] * len(points)
    for i, j in randomise.capital_graph(points):
        degrees[i] += 1
        degrees[j] += 1
    return degrees


def _clean(value):
    """JSON cannot hold inf or nan; the statistics can produce both."""
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return None
    return value


def measure(seed: str, galaxy: dict) -> dict:
    """Every statistic for one draw, flattened for a JSON line."""
    summary = metrics.summary(galaxy)
    record: dict = {"seed": seed}

    for name in metrics.ALL:
        record[name] = _clean(summary[name])
    for name in metrics.FAIRNESS:
        record[f"raw_{name}"] = [_clean(v) for v in summary["raw"][name]]
        band = summary["band"][name]
        record[f"band_{name}"] = [_clean(v) for v in band] if band else None
        record[f"ratio_{name}"] = _clean(summary["ratio"][name])

    record["descriptor"] = [_clean(v) for v in summary["descriptor"]]
    record["capital_degree"] = capital_degrees(galaxy)

    context = summary["context"]
    record["connect_level"] = context["connect_level"]
    record["connected_at_start"] = context["connected_at_start"]
    record["marooned"] = context["marooned"]
    record["stars"] = context["stars"]

    # The galaxy must at least be loadable by Solaris. No check() here - that is
    # a maps/irregular.py band, and the game applies nothing of the kind.
    result = validate.validate(galaxy)
    record["validation_errors"] = list(result.errors)

    fronts = summary["raw"]["fronts"]
    low, high = FRONTS_BAND
    record["fronts_min"] = min(fronts)
    record["fronts_max"] = max(fronts)
    record["in_band"] = bool(min(fronts) >= low and max(fronts) <= high)
    # How far this map sits from the band, for ranking: how many players are
    # outside it, then by how much in total. Zero on a map that satisfies it.
    record["out_of_band"] = sum(1 for v in fronts if v < low or v > high)
    record["band_deviation"] = sum(max(low - v, 0) + max(v - high, 0)
                                   for v in fronts)
    return record


def draw(job: tuple[str, str, dict]) -> dict:
    seed, generator, generator_kwargs = job
    record = measure(seed, build(seed, generator, **generator_kwargs))
    record["generator"] = generator
    record["arm"] = "C" if generator != GENERATOR else "AB"
    return record


# --------------------------------------------------------------------------


def run(jobs, workers: int, label: str) -> list[dict]:
    from multiprocessing import Pool
    started = time.time()
    out: list[dict] = []
    with Pool(workers) as pool:
        for n, record in enumerate(pool.imap_unordered(draw, jobs, chunksize=4), 1):
            out.append(record)
            if n % 200 == 0:
                rate = n / (time.time() - started)
                print(f"  {label}: {n} draws, {rate:.1f}/s", flush=True)
    print(f"  {label}: {len(out)} draws in {time.time() - started:.0f}s", flush=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pilot", type=int, default=0,
                        help="draw N of each arm and report acceptance only")
    parser.add_argument("--target", type=int, default=1000,
                        help="accepted draws wanted in each arm")
    parser.add_argument("--workers", type=int, default=14)
    parser.add_argument("--out", default=None,
                        help="where to write the NDJSON records")
    args = parser.parse_args()

    if args.pilot:
        rows = run([(f"pilot-{i}", GENERATOR, {}) for i in range(args.pilot)],
                   args.workers, "pilot A/B")
        accepted = sum(r["in_band"] for r in rows)
        print(f"\nacceptance in {FRONTS_BAND}: {accepted}/{len(rows)} "
              f"= {100 * accepted / len(rows):.1f}%")
        print(f"projected stream for {args.target} accepted: "
              f"{args.target * len(rows) / max(accepted, 1):.0f} draws")
        rows_c = run([(f"pilot-{i}", "irregular_n_limit", N_LIMIT_KWARGS)
                      for i in range(args.pilot)], args.workers, "pilot C")
        acc_c = sum(r["in_band"] for r in rows_c)
        print(f"n_limit acceptance: {acc_c}/{len(rows_c)} "
              f"= {100 * acc_c / len(rows_c):.1f}%")
        return

    out_path = Path(args.out) if args.out else ROOT / "out" / "fronts_study.ndjson"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Arm C is a fixed 1000 draws. Arms A and B come out of one stream: A is the
    # first `target` draws of it, B is the first `target` that clear the band.
    # Sized off the pilot's ~21% acceptance, with room to spare. `--pilot`
    # reports the rate and the stream this implies before committing to a run.
    stream_size = int(args.target * 8)
    print(f"stream for A/B: up to {stream_size} draws; arm C: {args.target}")

    rows = run([(f"study-{i}", GENERATOR, {}) for i in range(stream_size)],
               args.workers, "A/B stream")
    rows.sort(key=lambda r: int(r["seed"].split("-")[1]))
    rows_c = run([(f"study-{i}", "irregular_n_limit", N_LIMIT_KWARGS)
                  for i in range(args.target)], args.workers, "C")
    rows_c.sort(key=lambda r: int(r["seed"].split("-")[1]))

    with out_path.open("w", encoding="utf-8") as handle:
        for record in rows + rows_c:
            handle.write(json.dumps(record) + "\n")

    accepted = sum(r["in_band"] for r in rows)
    print(f"\nwrote {out_path}  ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")
    print(f"A/B stream {len(rows)} draws, {accepted} in band "
          f"({100 * accepted / len(rows):.1f}%)")
    print(f"arm C {len(rows_c)} draws")


if __name__ == "__main__":
    main()
