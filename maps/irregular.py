#!/usr/bin/env python3
"""A grown galaxy: irregular, asymmetric, and fair anyway.

The counterpart to `example.py` and `spy_v_spy.py`, which both make a map fair by
making it congruent - build one wedge, rotate it, and every player's start is the
same start by construction. That is the safe way and it costs the map its
character: a rotationally symmetric galaxy has no landmarks, because every place
in it exists N times.

This one gives that up. `solarismap.generate` grows a star field with no symmetry
at all, so no two players face the same galaxy, and fairness has to be *arranged*
and then *measured* rather than inherited. Two rules do the arranging:

    1. Every player's opening is identical by construction. Capitals and starting
       stars get fixed values, not values read off the layout, so the first few
       turns are exactly equal no matter where a player was seated.
    2. Every neutral star's worth is a function of how far it is from the nearest
       capital - poor near home, rich in no-man's-land. The same rule everywhere,
       so nobody is handed a rich neighbourhood; what varies is how much
       contested space each player sits near, and that is what `check` bounds.

What `check` cannot do is assert congruence, because there is none. It asserts
distributions instead: opening options, contested frontage, reachable wealth and
capital isolation all have to land inside a band across every player. That band
is the whole design - widen it and the map gets more interesting and less fair.

Run:  python maps/irregular.py [--players N] [--stars-per-player N]
                               [--seed S] [--generator NAME] [--render]
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solarismap import (generate, geometry, model, randomise, render,   # noqa: E402
                        rules, validate)

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "out" / "irregular.json"
FIGURE = ROOT / "out" / "irregular.svg"

# Defaults sized to be worth looking at and quick to build: 360 stars is a real
# galaxy, well under the 1500 cap, and rebuilds in about a second.
PLAYERS = 10
STARS_PER_PLAYER = 20
SEED = "irregular-1"
GENERATOR = "irregular"

# These match server/config/game/settings/official/standard.json exactly:
# galaxy type irregular, 10 players, 20 stars each, 6 starting stars, and
# starting hyperspace and scanning both at 1. A map builder that departs from the
# game's own configuration is measuring something nobody plays.
STARTING_STARS = 6
START_HYPERSPACE = 1
START_SCANNING = 1

# The lattice pitch is left at the generator's default, which is the game's own
# hardcoded SPREAD of 2.5. `generate.fit_spread(START_HYPERSPACE)` gives a denser
# galaxy with more opening choices and better connectivity, but that is a
# different map rather than a fixed one - see its docstring.

# Fixed opening. Identical for every player, deliberately - see rule 1 above.
CAPITAL_NR = 50
CAPITAL_SHIPS = 10
CAPITAL_INFRASTRUCTURE = {"economy": 5, "industry": 5, "science": 1}
STARTING_NR = 25
STARTING_SHIPS = 10

# The neutral curve. The band is the editor's own randomiser default
# (settings.random.minEconomyResources / max..., storage.ts): 10 to 50.
NR_MIN = 10
NR_MAX = 50
# randomIntBetweenExp's shape parameter. 0.5 is uniform; higher skews low.
LOW_VALUE_BIAS = 0.5
# How hard value rises with distance from the nearest capital. Negative means
# far-from-home is richer, which is the shape that makes the map play: safe
# ground poor, contested ground rich. Zero would make position irrelevant and
# positive would reward turtling.
RADIUS_WEIGHT = -0.35

# Terrain as a percentage of stars, taken from the high end of a noise field
# (positive) or the low end (negative), so the two land in separate regions
# rather than interleaved. Thresholds are solved per map by quantile_bands.
# Special features are **scattered**, not belted. Solaris places them one star at
# a time, and that is the right shape for them: a nebula is a landmark you route
# around, and forty of them in a row is a wall, which the map already has plenty
# of in its voids. The noise goes into the star *layout* instead, where structure
# is wanted. Percentages, as the editor's Randomise menu takes them.
TERRAIN_PERCENTAGES = {"isNebula": 12.0, "isAsteroidField": 9.0,
                       "isBinaryStar": 6.0, "isBlackHole": 2.5}
WORMHOLE_PERCENTAGE = 5.0

TECHNOLOGIES = {
    "scanning": START_SCANNING, "hyperspace": START_HYPERSPACE, "terraforming": 1,
    "experimentation": 1, "weapons": 1, "banking": 1, "manufacturing": 1,
    "specialists": 1,
}

# --- the fairness bands ---------------------------------------------------
#
# Every one of these is a spread across players, expressed as a fraction of the
# mean, and every one is a judgement call rather than a rule of the game. They
# are set where the default configuration clears them with room to spare; a seed
# that fails one is telling you it seated somebody badly, and the fix is a new
# seed, not a wider band. Widen a band only when you have decided that kind of
# imbalance is acceptable in the map you are making.

MAX_OPENING_OPTIONS_SPREAD = 1.00   # neutral stars inside the first jump, from the whole pod
MAX_REACHABLE_WEALTH_SPREAD = 0.45  # resources within three jumps
MAX_ISOLATION_SPREAD = 0.90         # distance to the nearest rival capital
MIN_OPENING_OPTIONS = 2             # nobody may start boxed in
MIN_SEPARATION = 30.0               # hard floor; below this stars overlap on screen

# A grown galaxy is not one connected piece at the opening jump and is not meant
# to be - the voids the noise prune carves are what give it places. What matters
# is that the whole map opens up eventually rather than containing a pocket
# nobody can ever enter. At the game's own lattice pitch this typically lands at
# hyperspace 5, so the band is set where the game actually sits rather than where
# a denser variant would.
MAX_CONNECT_HYPERSPACE = 6

# Split channels bring their own fairness problem: equal totals are no longer
# enough if one player's neighbourhood is all industry. Checked per channel.
MAX_CHANNEL_SPREAD = 0.50
# And terrain is worth having only if everyone gets some. A nebula belt entirely
# inside one player's ground is an advantage nobody voted for.
MAX_TERRAIN_SPREAD = 1.40
MIN_TERRAIN_NEARBY = 1


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------


def build(players: int, stars_per_player: int, seed: str,
          generator: str) -> tuple[dict, generate.Layout]:
    layout = generate.generate(
        generator, players, stars_per_player,
        seed=seed,
        starting_stars=STARTING_STARS,
        hyperspace=START_HYPERSPACE,
        separation=rules.MIN_STAR_SEPARATION,
    )

    # The pull-into-range pass inside the generator drags each player's starting
    # stars towards their capital and knows nothing about the rest of the galaxy,
    # so it can leave them crowding a neutral neighbour. Relax the field with
    # every pod pinned: the pods stay exactly where reachability put them and the
    # neutrals move aside. O(n^2) per round, so it is the slow step at 1000+ stars.
    pinned = list(layout.owners())
    points = generate.relax_separation(layout.points, rules.MIN_STAR_SEPARATION,
                                       pinned=pinned)

    # A separate stream from the one that placed the stars, so re-rolling the
    # terrain does not move a single star and vice versa. The editor keeps
    # Generate and Randomise apart for the same reason.
    properties = generate.Rng(f"{layout.seed}:properties")

    owners = layout.owners()
    capitals = {index: player for player, index in enumerate(layout.homes)}
    home_points = [points[i] for i in layout.homes]

    stars: list[dict] = []
    for index, point in enumerate(points):
        star = model.new_star(point, _player=owners.get(index))
        if index in capitals:
            star["_role"] = "capital"
            model.set_resources(star, CAPITAL_NR)
        elif index in owners:
            star["_role"] = "starting"
            model.set_resources(star, STARTING_NR)
        else:
            star["_role"] = "neutral"        # resources come later, in one pass
        stars.append(star)

    # Neutral stars get the editor's own randomiser rather than a hand-rolled
    # curve: randomIntBetweenExp over NR_MIN..NR_MAX, three channels rolled
    # independently. Two departures from upstream, both deliberate.
    #
    # The radius term is measured from the *nearest capital* instead of from the
    # centre of the galaxy, because a grown galaxy has no meaningful centre and
    # keying off one hands rim players a different game for no reason they can
    # see. Negative weight means value rises with distance from home, which is
    # the shape that makes the map play: safe ground is poor, contested ground
    # is rich, sitting still loses.
    #
    # Splitting the channels is what turns Solaris's splitResources on, and it
    # is the whole point - it makes a star qualitatively rather than merely
    # quantitatively different. A science world is worth taking for different
    # reasons than an industry one.
    neutrals = [s for s in stars if s["_role"] == "neutral"]
    randomise.randomise_resources(neutrals, properties,
                                  minimum=NR_MIN, maximum=NR_MAX,
                                  low_value_bias=LOW_VALUE_BIAS,
                                  radius_weight=RADIUS_WEIGHT,
                                  anchors=home_points, split=True)

    model.assign_ids(stars)

    player_list = []
    for player, home_index in enumerate(layout.homes):
        player_id = str(player + 1)
        model.make_home_star(stars[home_index], player_id, ships=CAPITAL_SHIPS,
                             **CAPITAL_INFRASTRUCTURE)
        for star_index in layout.starting[player]:
            stars[star_index]["playerId"] = player_id
            model.set_ships(stars[star_index], STARTING_SHIPS)
        player_list.append(model.new_player(player_id, stars[home_index]["id"],
                                            technologies=TECHNOLOGIES))

    # Balance per channel, not on the sum. Once the channels are split, equal
    # totals stop being enough: a player whose neighbourhood is all industry and
    # no science is behind on research however healthy the sum looks. Runs after
    # assignment so only neutral stars move and the fixed opening survives.
    capital_stars = [stars[i] for i in layout.homes]
    randomise.balance_by_channel(stars, capital_stars,
                                 3.0 * rules.hyperspace_range(START_HYPERSPACE),
                                 minimum=NR_MIN, maximum=NR_MAX)

    # Features scattered the way the game scatters them, then evened out. Uniform
    # placement is already close to fair, so the balancing here is a light touch
    # - and it preserves scatter rather than belts, breaking up whichever clumps
    # the shuffle happened to produce instead of growing them.
    randomise.randomise_terrain(stars, properties, **TERRAIN_PERCENTAGES)
    randomise.link_wormholes(stars, properties, WORMHOLE_PERCENTAGE)
    horizon = 3.0 * rules.hyperspace_range(START_HYPERSPACE)
    for field_name in TERRAIN_PERCENTAGES:
        randomise.balance_terrain(stars, capital_stars, horizon, field_name,
                                  tolerance=MAX_TERRAIN_SPREAD * 0.8,
                                  preserve="scatter")

    # Even out the opening frontier by choosing which stars each player starts
    # with. At the game's own lattice pitch this runs 2 to 9 stars across
    # players untouched - the single largest unfairness left once wealth and
    # terrain are handled, and the only one whose lever costs nothing: no star
    # moves, the pods stay connected, only ownership changes.
    randomise.balance_openings(stars, capital_stars,
                               rules.hyperspace_range(START_HYPERSPACE),
                               tolerance=MAX_OPENING_OPTIONS_SPREAD * 0.75)

    layout.points = points
    return model.galaxy(stars, player_list, carriers=[]), layout


# --------------------------------------------------------------------------
# Checks
#
# Not "will Solaris load this" - `validate` answers that. These answer "is this
# galaxy playable and is it fair", which for an asymmetric map is a question
# about distributions rather than about congruence.
# --------------------------------------------------------------------------


def spread(values: list[float]) -> float:
    """Range across players as a fraction of the mean. 0 is perfect parity."""
    if not values:
        return 0.0
    mean = statistics.mean(values)
    return (max(values) - min(values)) / mean if mean else 0.0


def check(data: dict, layout: generate.Layout) -> None:
    """Fail the build if the galaxy is unplayable or the imbalance is out of band."""
    stars = data["stars"]
    by_id = {s["id"]: s for s in stars}
    capitals = [s for s in stars if s["homeStar"]]
    reach = rules.hyperspace_range(START_HYPERSPACE)
    scan = rules.scanning_range(START_SCANNING)
    points = [geometry.star_point(s) for s in stars]

    owned: dict[str, list[dict]] = {}
    for star in stars:
        if star["playerId"] is not None:
            owned.setdefault(star["playerId"], []).append(star)

    # --- structure ---------------------------------------------------------
    assert len(stars) <= rules.MAX_STARS, f"{len(stars)} stars is over the cap"
    assert len(capitals) == layout.player_count, "one capital per player"
    assert len(data["players"]) == layout.player_count, "one player per capital"
    assert len({s["playerId"] for s in capitals}) == layout.player_count, \
        "two players share a capital"
    for player_id, mine in owned.items():
        assert len(mine) == STARTING_STARS, \
            f"player {player_id} starts with {len(mine)} stars, not {STARTING_STARS}"
    for star in stars:
        if star["playerId"] is None:
            assert star["shipsActual"] == 0, f"unowned star {star['id']} has ships"

    # --- the opening is identical for everybody ----------------------------
    # Guaranteed by construction, asserted because it is the load-bearing half
    # of this map's fairness and a change to the resource curve could break it
    # without breaking anything else.
    openings = {
        player_id: (sum(sum(s["naturalResources"].values()) for s in mine),
                    sum(s["shipsActual"] for s in mine))
        for player_id, mine in owned.items()
    }
    assert len(set(openings.values())) == 1, \
        f"players do not have identical openings: {sorted(set(openings.values()))}"

    # --- every pod is usable on turn one -----------------------------------
    # The generator's pull pass connects each pod as a *chain*, not a star: a
    # player may have to hop through one of their own stars to reach another.
    for player_id, mine in owned.items():
        ticks = geometry.connected_hops(mine, [s for s in mine if s["homeStar"]], reach)
        stranded = [sid for sid, cost in ticks.items() if cost == math.inf]
        assert not stranded, \
            f"player {player_id} cannot reach their own stars {stranded} at " \
            f"hyperspace {START_HYPERSPACE}"

    # --- the galaxy opens up -----------------------------------------------
    # Not "connected at the opening jump" - a grown galaxy is not, and a map that
    # were would have had its voids filled in. What must not exist is a pocket
    # that stays sealed however far the players research.
    level = connect_level(stars, capitals)
    assert level is not None and level <= MAX_CONNECT_HYPERSPACE, (
        f"galaxy is still in pieces at hyperspace {MAX_CONNECT_HYPERSPACE} "
        f"({'never connects' if level is None else f'needs {level}'}) - "
        f"the noise prune cut it in two, try another seed")

    # --- spacing -----------------------------------------------------------
    gaps = geometry.nearest_neighbour_gaps(points)
    assert min(gaps) >= MIN_SEPARATION, \
        f"closest two stars are {min(gaps):.1f}u apart, floor is {MIN_SEPARATION:.0f}u"

    # --- the fairness bands ------------------------------------------------
    options, wealth, isolation = [], [], []
    for capital in capitals:
        here = geometry.star_point(capital)
        mine = {s["id"] for s in owned[capital["playerId"]]}

        # Neutral stars a player can take on their first jump, counted from
        # their WHOLE starting pod - a player may launch a carrier from any star
        # they own, and the generator deliberately strings the pod into a chain
        # whose far end is most of their opening frontier. Measuring from the
        # capital alone understates this so badly it reports every player as
        # stranded on maps the game plays perfectly well.
        pod = [s for s in stars if s["playerId"] == capital["playerId"]]
        options.append(sum(1 for s in geometry.reachable_from_any(pod, stars, reach)
                           if s["playerId"] is None))

        # Resources within three jumps, weighted by nobody - just what is there
        # to be had in the opening game.
        wealth.append(sum(sum(s["naturalResources"].values()) for s in stars
                          if s["playerId"] is None
                          and ticks_from(here, s) <= 3.0 * reach))

        # How far the nearest rival capital is. Low means an early war whether
        # you wanted one or not; high means a free build-up.
        isolation.append(min(geometry.dist(here, geometry.star_point(c))
                             for c in capitals if c["id"] != capital["id"]))

    assert min(options) >= MIN_OPENING_OPTIONS, \
        f"a player has only {min(options)} neutral stars in their first jump"
    # Per channel, not just on the sum. Splitting the resources means a player
    # can be handed a neighbourhood that is rich overall and has no science in
    # it, which the total hides completely.
    for channel in rules.RESOURCE_CHANNELS:
        per_player = [
            sum((s["naturalResources"] or {}).get(channel, 0) for s in stars
                if s["playerId"] is None
                and ticks_from(geometry.star_point(c), s) <= 3.0 * reach)
            for c in capitals]
        actual = spread(per_player)
        assert actual <= MAX_CHANNEL_SPREAD, (
            f"{channel} within three jumps has spread {actual:.2f}, band is "
            f"{MAX_CHANNEL_SPREAD:.2f} (min {min(per_player)}, "
            f"max {max(per_player)}) - try another seed")

    # Terrain is only worth having if everybody gets some. A nebula belt sitting
    # entirely inside one player's ground is an advantage nobody voted for, and
    # it is exactly what a noise field will do if left unchecked.
    for field_name in ("isNebula", "isAsteroidField"):
        nearby = [sum(1 for s in stars
                      if s.get(field_name)
                      and ticks_from(geometry.star_point(c), s) <= 3.0 * reach)
                  for c in capitals]
        if not any(nearby):
            continue                    # this terrain was not requested
        assert min(nearby) >= MIN_TERRAIN_NEARBY,             f"a player has no {field_name} within three jumps"
        actual = spread(nearby)
        assert actual <= MAX_TERRAIN_SPREAD, (
            f"{field_name} within three jumps has spread {actual:.2f}, band is "
            f"{MAX_TERRAIN_SPREAD:.2f} (min {min(nearby)}, max {max(nearby)}) "
            f"- try another seed")

    for label, values, limit in (
        ("opening options", options, MAX_OPENING_OPTIONS_SPREAD),
        ("reachable wealth", wealth, MAX_REACHABLE_WEALTH_SPREAD),
        ("capital isolation", isolation, MAX_ISOLATION_SPREAD),
    ):
        actual = spread(values)
        assert actual <= limit, (
            f"{label} spread is {actual:.2f}, band is {limit:.2f} "
            f"(min {min(values):.0f}, max {max(values):.0f}) - try another seed")

    # Nothing above proves the map is *good*, only that it is not obviously
    # unfair. Render it and look at it.
    return None


def ticks_from(here: tuple[float, float], star: dict) -> float:
    return geometry.dist(here, geometry.star_point(star))


def connect_level(stars: list[dict], capitals: list[dict],
                  ceiling: int = 8) -> int | None:
    """Lowest hyperspace level at which every star is reachable from some capital.

    None if the galaxy never joins up inside `ceiling` - which means the noise
    prune severed it, not that the players need more research.
    """
    for level in range(START_HYPERSPACE, ceiling + 1):
        ticks = geometry.connected_hops(stars, capitals, rules.hyperspace_range(level))
        if not any(cost == math.inf for cost in ticks.values()):
            return level
    return None


def report(data: dict, layout: generate.Layout) -> None:
    stars = data["stars"]
    capitals = [s for s in stars if s["homeStar"]]
    reach = rules.hyperspace_range(START_HYPERSPACE)
    gaps = geometry.nearest_neighbour_gaps([geometry.star_point(s) for s in stars])

    options, wealth, isolation = [], [], []
    for capital in capitals:
        here = geometry.star_point(capital)
        pod = [s for s in stars if s["playerId"] == capital["playerId"]]
        options.append(sum(1 for s in geometry.reachable_from_any(pod, stars, reach)
                           if s["playerId"] is None))
        wealth.append(sum(sum(s["naturalResources"].values()) for s in stars
                          if s["playerId"] is None
                          and ticks_from(here, s) <= 3.0 * reach))
        isolation.append(min(geometry.dist(here, geometry.star_point(c))
                             for c in capitals if c["id"] != capital["id"]))

    print(f"generator           {layout.generator}  seed {layout.seed}")
    print(f"stars               {len(stars)}")
    print(f"players             {model.player_count(data)}  "
          f"({model.stars_per_player(data):.4g} stars each)")
    print(f"starting reach      {reach:.0f}u (hyperspace {START_HYPERSPACE})")
    level = connect_level(stars, capitals)
    print(f"galaxy joins up at  hyperspace {level if level else '>8'}  "
          f"(band is {MAX_CONNECT_HYPERSPACE})")
    print(f"closest two stars   {min(gaps):.0f}u  "
          f"(editor's minimum is {rules.MIN_STAR_SEPARATION:.0f}u, "
          f"{sum(1 for g in gaps if g < rules.MIN_STAR_SEPARATION)} below it)")
    print(f"split resources     {model.split_resources(data)}")
    terrain = {k: sum(1 for s in stars if s.get(k))
               for k in ("isNebula", "isAsteroidField", "isBinaryStar",
                         "isBlackHole", "isPulsar", "warpGate")}
    print("terrain             " + ("  ".join(f"{k[2:] if k.startswith('is') else k}"
                                              f" {v}" for k, v in terrain.items() if v)
                                    or "none"))
    print()
    print("                     min     max    mean   spread   band")
    for label, values, limit in (
        ("opening options", options, MAX_OPENING_OPTIONS_SPREAD),
        ("reachable wealth", wealth, MAX_REACHABLE_WEALTH_SPREAD),
        ("capital isolation", isolation, MAX_ISOLATION_SPREAD),
    ):
        print(f"{label:20s}{min(values):6.0f}  {max(values):6.0f}  "
              f"{statistics.mean(values):6.0f}   {spread(values):5.2f}   "
              f"{limit:5.2f}")


# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--players", type=int, default=PLAYERS)
    parser.add_argument("--stars-per-player", type=int, default=STARS_PER_PLAYER)
    parser.add_argument("--seed", default=SEED,
                        help="any string; the same seed rebuilds the same galaxy")
    parser.add_argument("--generator", default=GENERATOR,
                        choices=sorted(generate.GENERATORS),
                        help="all six of the editor's generators are available")
    parser.add_argument("--render", action="store_true",
                        help=f"also draw {FIGURE.name}")
    args = parser.parse_args()

    data, layout = build(args.players, args.stars_per_player, args.seed,
                         args.generator)
    report(data, layout)
    check(data, layout)

    result = validate.validate(data)
    for warning in result.warnings:
        print(f"warning             {warning}")
    result.raise_for_errors()

    model.write(OUTPUT, data)
    print(f"\nwrote {OUTPUT}  ({OUTPUT.stat().st_size / 1024:.0f} KB)  "
          f"checked and validated")

    if args.render:
        FIGURE.write_text(render.draw(data), encoding="utf-8")
        print(f"wrote {FIGURE}  ({FIGURE.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
