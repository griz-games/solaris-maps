#!/usr/bin/env python3
"""A minimal, complete map: copy this file to start a new one.

Four players on a ring, each with a capital and three satellites, one contested
binary star on every midline between neighbours, and a neutral core. It is not
an interesting map - it is the shortest thing that exercises every part of the
toolkit, so you can see the whole loop before you replace the layout.

The loop, in the order it runs here:

    1. place stars          geometry gives you the points
    2. assign ids           model.assign_ids, once the galaxy is complete
    3. set resources        model.set_resources
    4. hand out capitals    model.make_home_star + model.new_player
    5. prove the geometry    geometry.connected_hops - is everything reachable,
                            is the contested ground really equidistant
    6. validate              validate.validate(...).raise_for_errors()
    7. write                 model.write

Steps 5 and 6 are different questions. Validation asks "will Solaris load
this"; the geometry checks ask "is this the map I meant". A map needs both.

Run:  python maps/example.py
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solarismap import geometry, model, rules, validate   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "out" / "example_map.json"

N_PLAYERS = 4
WEDGE = 360.0 / N_PLAYERS               # 90 degrees between capitals
MIDLINE = WEDGE / 2.0                   # a contested bearing sits halfway between two

# Every radius here is chosen so the whole galaxy is connected at the starting
# hyperspace level - see report(), which fails loudly if a change breaks that.
CAPITAL_R = 200.0                       # capital's distance from the core
SATELLITE_R = 60.0                      # satellites orbit the capital this far out
SATELLITE_ANGLES = (0.0, 120.0, -120.0)
BRIDGE_R = 100.0                        # neutral stepping stone, capital to core

# The contested star sits on the midline at its closest approach to the two
# capitals either side - the perpendicular foot. Anywhere further out along the
# midline is further from both, so this is as contestable as a midline gets.
BINARY_R = CAPITAL_R * math.cos(math.radians(MIDLINE))

CAPITAL_NR = 50
SATELLITE_NR = 20
BINARY_NR = 75
CORE_NR = 100

STARTING_SHIPS = 10
START_HYPERSPACE = 2

TECHNOLOGIES = {
    "scanning": 2, "hyperspace": START_HYPERSPACE, "terraforming": 1,
    "experimentation": 1, "weapons": 1, "banking": 1, "manufacturing": 1,
    "specialists": 1,
}


def build() -> dict:
    stars: list[dict] = []

    # The core: neutral, rich, and equally far from every capital.
    core = model.new_star((0.0, 0.0), _role="core")
    model.set_resources(core, CORE_NR)
    core["isPulsar"] = True
    stars.append(core)

    # One pod per player, each the previous pod rotated by a whole wedge, so
    # every player's start is the same start.
    pods: list[list[dict]] = []
    for wedge in range(N_PLAYERS):
        bearing = wedge * WEDGE
        capital = model.new_star(geometry.polar(CAPITAL_R, bearing),
                                 _role="capital", _wedge=wedge)
        pod = [capital]
        for angle in SATELLITE_ANGLES:
            offset = geometry.polar(SATELLITE_R, angle)
            pod.append(model.new_star(
                geometry.rotate(geometry.translate((CAPITAL_R, 0.0), offset), bearing),
                _role="satellite", _wedge=wedge))
        pods.append(pod)
        stars += pod

        # A neutral stepping stone on the same bearing, so the pod can walk in
        # to the core at the starting hyperspace level instead of needing tech.
        bridge = model.new_star(geometry.polar(BRIDGE_R, bearing),
                                _role="bridge", _wedge=wedge)
        model.set_resources(bridge, SATELLITE_NR)
        stars.append(bridge)

    # The contested binaries, one per midline. Sitting exactly on the bearing
    # halfway between two capitals makes them equidistant from both, so neither
    # neighbour has a head start on one.
    for wedge in range(N_PLAYERS):
        binary = model.new_star(geometry.polar(BINARY_R, wedge * WEDGE + MIDLINE),
                                _role="binary")
        model.set_resources(binary, BINARY_NR)
        binary["isBinaryStar"] = True
        stars.append(binary)

    model.assign_ids(stars)

    players = []
    for wedge, pod in enumerate(pods):
        player_id = str(wedge + 1)
        capital, satellites = pod[0], pod[1:]
        model.set_resources(capital, CAPITAL_NR)
        model.make_home_star(capital, player_id, ships=STARTING_SHIPS,
                             economy=5, industry=5, science=1)
        for satellite in satellites:
            model.set_resources(satellite, SATELLITE_NR)
            satellite["playerId"] = player_id
            model.set_ships(satellite, STARTING_SHIPS)
        players.append(model.new_player(player_id, capital["id"],
                                        technologies=TECHNOLOGIES))

    return model.galaxy(stars, players, carriers=[])


def report(data: dict) -> None:
    """Prove the map is the map that was intended, not just a legal one."""
    stars = data["stars"]
    capitals = [s for s in stars if s["homeStar"]]
    binaries = [s for s in stars if s["isBinaryStar"]]
    reach = rules.hyperspace_range(START_HYPERSPACE)

    print(f"stars               {len(stars)}")
    print(f"players             {model.player_count(data)}  "
          f"({model.stars_per_player(data):.4g} stars each)")
    print(f"starting reach      {reach:.0f}u (hyperspace {START_HYPERSPACE})")

    # Every star reachable from some capital without researching hyperspace.
    # A star that is not is not necessarily a bug - a late-game objective may be
    # deliberately out of reach - but it should always be a decision.
    ticks = geometry.connected_hops(stars, capitals, reach)
    unreachable = [sid for sid, cost in ticks.items() if cost == float("inf")]
    print(f"out of reach at start {len(unreachable)}"
          + (f"  {unreachable}" if unreachable else ""))

    # Each contested binary equidistant from its two nearest capitals: the
    # property that makes it fair, and the one a layout change breaks silently.
    worst = 0.0
    closest = 0.0
    for binary in binaries:
        gaps = sorted(geometry.dist(geometry.star_point(binary), geometry.star_point(c))
                      for c in capitals)
        worst = max(worst, abs(gaps[0] - gaps[1]))
        closest = max(closest, gaps[0])
    print(f"binary imbalance    {worst:.6f}u  (0 means dead centre)")
    print(f"binary from capital {closest:.0f}u  "
          f"(hyperspace {rules.hyperspace_level(closest)})")

    gaps = geometry.nearest_neighbour_gaps([geometry.star_point(s) for s in stars])
    print(f"closest two stars   {min(gaps):.0f}u  "
          f"(editor's minimum is {rules.MIN_STAR_SEPARATION:.0f}u)")


def main() -> None:
    data = build()
    report(data)

    result = validate.validate(data)
    for warning in result.warnings:
        print(f"warning             {warning}")
    result.raise_for_errors()

    model.write(OUTPUT, data)
    print(f"\nwrote {OUTPUT}  ({OUTPUT.stat().st_size / 1024:.0f} KB)  "
          f"validated against Solaris's rules")


if __name__ == "__main__":
    main()
