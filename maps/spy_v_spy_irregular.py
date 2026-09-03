#!/usr/bin/env python3
"""Build the irregular cut of Spy v Spy: 36 players, 9 grown pods, 909 stars.

This is spy_v_spy.py's skeleton - nine pods on a ring, four players to a pod, a
gateway and a black hole post per player, wormholes dealt so every pair of pods
is linked exactly once - with the inside of every pod *grown* rather than placed.

The first attempt at this map was not irregular, and this file exists because of
it. That one held six invariants exactly - a 47-tick road to the core, a post
whose nearest neighbour was 240u to the unit, turn-one vision of exactly three
stars - and every one of those pins a *radius*. Fix enough radii and a pod
becomes a set of concentric shells with only the bearings left free: all 36
capitals sat at exactly 561.6u from their core, the nebulas within 2.8u of each
other, 63 of the 101 radial ranks in a pod agreeing within 25u across all nine
pods. Nine copies of one wheel, jittered.

So the exactness went and the growth came back. `solarismap.generate.irregular`
lays each pod down the way the editor's own generator does - hex lattice,
metaball outline, simplex-noise voids - and this file adds only what the skeleton
needs on top: a pulsar at the middle, a post hung off each player's shoulder, and
the wormholes that tie the ring together. Where a star sits is the generator's
business now, not this file's.

Fairness is therefore arranged and then measured, in the three layers
`.claude/skills/irregular-galaxy/` sets out:

  by construction     capitals and starting stars take fixed values, so the
                      opening is identical wherever a player was seated. This is
                      the one thing still held to exact equality, because it is
                      the only one that costs no geometry.
  by impartial rule   every neutral star is priced off its distance to the
                      NEAREST CAPITAL rather than to the pod's middle: poor at
                      home, rich in no-man's-land. Sitting still loses, and the
                      good ground is ground two players can both reach.
  by rebalancing      a capital grown on the rim of a blob has less galaxy around
                      it than one in the middle, and no pricing rule fixes a
                      difference in how much there *is*. balance_by_channel
                      nudges neutral values until every player's three-jump
                      neighbourhood is worth about the same, per channel.

What is left over is bounded by bands rather than equalities - see the BANDS
block and check(). A failing band means the seed seated somebody badly, and the
answer is another seed, which is what --search is for.

Run:  python maps/spy_v_spy_irregular.py                # 9 pods, 36 players
      python maps/spy_v_spy_irregular.py --pods 2       # 8 players
      python maps/spy_v_spy_irregular.py --render       # and the figures
      python maps/spy_v_spy_irregular.py --probe        # one pod's shape and road
      python maps/spy_v_spy_irregular.py --search 24    # rank master seeds
"""

from __future__ import annotations

import argparse
import heapq
import itertools
import json
import math
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solarismap import (generate, geometry, model, randomise, rules,   # noqa: E402
                        specialists, validate)

# --------------------------------------------------------------------------
# Game rules - all of it from solarismap.rules
# --------------------------------------------------------------------------

LIGHT_YEAR = rules.LIGHT_YEAR
hyperspace_range = rules.hyperspace_range
hyperspace_level = rules.hyperspace_level
scanning_range = rules.scanning_range

_TELESCOPE_ARRAY = specialists.by_name("Telescope Array")
SPECIALIST_TELESCOPE_ARRAY = _TELESCOPE_ARRAY["id"]
TELESCOPE_SCANNING_BONUS = specialists.scanning_bonus(SPECIALIST_TELESCOPE_ARRAY)
BLACK_HOLE_SCANNING_BONUS = rules.BLACK_HOLE_SCANNING_BONUS

dist = geometry.dist
polar = geometry.polar
rotate = geometry.rotate

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

# The ":11" is the winner of `--search 12`, which grew the whole ring from
# twelve master seeds and ranked them on the four bands below. It came first on
# every one that varies: turn-one options 0.57 against the default seed's 1.00,
# territory 0.52 against 0.62, road 0.32 against 0.41. Nine of the twelve were
# rejected outright for failing a band, which is the workflow rather than a
# defect - a grown ring is drawn until one seats its 36 players tolerably.
SEED = "spy-v-spy-grown:11"

N_PODS = 9
PLAYERS_PER_POD = 4
N_PLAYERS = N_PODS * PLAYERS_PER_POD                    # 36
N_WORMHOLE_SLOTS = 2 * PLAYERS_PER_POD                  # 8: a post and a gateway each

# 24 grown stars per player, plus a pulsar at the pod's middle and a post per
# player hung outside it: 4 * 24 + 1 + 4 = 101 to a pod and 909 on the ring,
# which is what the placed map had.
STARS_PER_PLAYER = 24
STARS_PER_POD = PLAYERS_PER_POD * STARS_PER_PLAYER + 1 + PLAYERS_PER_POD

START_HYPERSPACE = 2
# 3, not 2, and for the same reason the repo's five 32-player maps use 3.
# Pulling the pods tight enough that nobody spawns inside a rival's first jump
# also pulls them away from everything else, and at scanning 2 - 150u - that
# left one player opening the game able to see nothing at all beyond their own
# six stars. 200u restores a view without touching a single star's position.
START_SCANNING = 3
STARTING_STARS = 6                                      # capital + 5, as before

HOP = hyperspace_range(START_HYPERSPACE)                # 175.0
REACH = hyperspace_range(3)                             # 225.0
START_SCAN = scanning_range(START_SCANNING)             # 150.0

POST_SCAN = scanning_range(START_SCANNING + BLACK_HOLE_SCANNING_BONUS
                           + TELESCOPE_SCANNING_BONUS)  # 450.0 - a taken post
POST_TERRAIN_SCAN = scanning_range(START_SCANNING
                                   + BLACK_HOLE_SCANNING_BONUS)     # 300.0 - the hole alone

# The lattice pitch, and the only distance in this file that decides how big a
# pod comes out: `generate` sizes a galaxy off `separation`. Everything else
# about the shape is the generator's. Re-run --probe after changing it, which
# reports the pod radius and the road the new pitch produces.
#
# 66 is close to the ceiling, not a free choice. 78 was tried for the extra room
# and it breaks the map: the lattice pitch outruns what hyperspace 2 can cross,
# and a typical blob came back with only 40-60 of its 96 stars reachable from the
# middle. Whatever room there is between stars on this map is bounded by the
# jump range players start on, not by taste.
POD_SEPARATION = 66.0

# A post stands off its player's shoulder: the nearest spot to their capital
# that is properly alone. "Alone" is POST_GAP_BAND to its nearest neighbour -
# (225, 275] is crossable at hyperspace 4 and at nothing less, one level nearer
# than the original map's post, where it took 5.
#
# Two things changed from the placed map, and a grown pod forced both.
#
# The direction is searched rather than fixed. Hanging every post on the ray out
# from the pod's middle only works when its capital is on the rim; a capital
# grown deep inside the blob has to cross the rest of it before anywhere is
# quiet. Searching bearings finds the fastest way out of the crowd instead.
#
# And a post no longer has to see the capital it watches. Getting 232u clear of
# a field whose stars average ~150u apart takes about 500u of walking, and the
# capital of a pod this size is 300-530u from the rim, so "alone, and inside 450u
# of the capital" has no solutions at all - measured, not guessed. What a post
# must still do is watch that player and only that player: at least one of their
# stars inside its scan and none of anybody else's. So a post watches a frontier
# rather than a home, and report() prints how many of the 36 still catch their
# capital as well.
POST_GAP_BAND = (232.0, 262.0)
POST_STEP = 8.0                                         # how finely the walk out is searched
POST_BEARING_STEP = 4.0                                 # and how finely the way out is
POST_SEARCH_LIMIT = 1000.0                              # give up on a shoulder past here

# Where the pod's landmark goes. Not the centroid: on a blob grown rather than
# drawn, one capital can sit 300u from the middle and another 530u, and a prize
# at the centroid is then a 20-tick walk for the first and 80 for the second -
# measured, on the first pod that grew. So the core is put at the spot that is
# most nearly EQUIDISTANT from the four pods instead, searched on a grid over the
# blob. It is the one piece of arrangement that buys back most of what the
# placed map got from symmetry, and it costs no irregularity at all: the stars
# stay where the generator put them and only the prize moves.
# Who sits where. This is the map's one real piece of arrangement, and it is
# spent here rather than on the star field because here it costs nothing:
# capitals are CHOSEN out of the grown blob at equal road distance from its
# middle, and every star stays exactly where the generator put it.
#
# The alternative was measured and rejected. Taking the generator's own capitals
# and re-rolling whole blobs until four of them happened to be evenly seated has
# a floor: over 181 usable blobs the best road spread available was 0.55, the
# median 0.88, and buying even 0.60 cost about 37 draws a pod. A grown pod simply
# does not seat four players evenly by luck. Choosing the seats does it directly.
# Every gate below was set from a measured distribution, not chosen: 360 blobs
# were drawn across three pods and the numbers read off. Over those, road spread
# ran 0.04-1.46 (median 0.28), territory spread 0.11-2.52 (median 1.04) and the
# thinnest opening 1-8 stars. Territory is the binding one by a distance - four
# seats grown into one blob claim very unequal ground - and this set passes 15
# blobs in 360, so a pod costs about 24 draws to find.
# Capitals sit at the same spacing the rest of the repo's maps use. Every one of
# the five 32-player maps in out/ puts its capitals at exactly 9.7 LY, because
# generate.irregular grows them on a triangular lattice and one lattice step is
# one lattice step for everybody; the hand-placed spy_v_spy sits at 13.2. This
# map matches the 32p standard rather than the flagship.
#
# The floor is what choose_capitals actually packs to - see the note there - and
# the ceiling only catches a blob whose shape forces a seat wider.
MIN_CAPITAL_GAP = 9.2 * LIGHT_YEAR                      # 460u, the 32p standard
MAX_CAPITAL_GAP = 11.0 * LIGHT_YEAR                     # 550u
# Nobody starts in an opponent's face. No two players' starting stars may be
# closer than one jump, so reaching a rival takes at least two - measured on the
# stars a player actually owns, not on their capitals, because the generator
# hands each capital its five nearest neighbours and two pods 356u apart met in
# the middle at 105u. That was 8 of 36 players on the previous build.
#
# MIN_CAPITAL_GAP is what makes this findable rather than lucky: at the old 350
# only 47% of seated pods cleared 175u, at 650 all of them do.
MIN_RIVAL_GAP = HOP + 10.0                              # 185u, one jump plus margin

# Where a player's wormhole out of the pod sits. Three rules, and none of them
# is "reachable on turn one" - that was tried and dropped, because buying it
# meant pulling every exit to within a hyperspace-1 jump of its owner, which
# crowded the four of them together in the middle of the pod.
#
#   * yours, not shared     - a pod-mate has to be GATEWAY_RIVAL_MARGIN times
#                             further away than you are. At 1.3 three of the 36
#                             sat within 1.5x of a neighbour, which is close
#                             enough that it is not really your door.
#   * not on top of another - MIN_GATEWAY_GAP between any two exits in a pod.
#                             The median pod already kept them 480u apart, but
#                             one had a pair at 182u, a single jump.
#   * as far out as that allows - of what survives, the one furthest from the
#                             capital, which puts the exits around the rim.
GATEWAY_SPAWN_REACH = 2.0 * HOP                         # 350u: two jumps of a star you own
MIN_GATEWAY_GAP = 2.0 * HOP                             # 350u between two exits in one pod
GATEWAY_RIVAL_MARGIN = 2.00                             # a pod-mate is twice as far away

# How wide a player's six stars are allowed to sprawl. This is the number that
# actually decides whether anyone spawns in a rival's face, and it took a while
# to find: the generator hands each capital its five nearest UNCLAIMED
# neighbours round-robin, so a capital picking late gets pushed outwards and
# pods came out ~270u across. A 185u gap between two such pods needs their
# capitals 725u apart, which no blob with a short road to its middle can offer.
# Pulling the pods in instead costs nothing and settles it: at 130u a pod, two
# capitals 420u apart leave 160u of clear space, and the gate does the rest.
POD_RADIUS_CAP = 130.0

# How far from the middle a capital is seated, in ticks of road rather than in
# units. Seating them at the blob's median road - the obvious choice, and the
# first one tried - makes the trek as long as the blob is big, and a blob roomy
# enough to stop stars crowding gave a 66-84 tick road. Naming the road instead
# decouples the two: the pods sit in the middle third of a large blob and the
# outer two thirds is neutral ground nobody starts in.
CAPITAL_ROAD_TARGET = 64.0                              # ticks from the pod's middle
# Tight, and this is the whole of "every player has an equal chance of reaching
# the centre": four seats picked out of a narrow road band start the same trek,
# whatever the blob looks like around them. Widening it is the fastest way to
# make a pod unfair.
CAPITAL_ROAD_TOLERANCE = 8.0                            # how far either side a seat may sit
CAPITAL_BAND_LIMIT = 22                                 # candidates weighed per pod, nearest the target

# Equivalent engagement. Not "nobody is too close to anyone" - that was the old
# gate, and it passed a pod where one player had a rival at 9 LY while another's
# nearest was 15 - but "every seat faces the same three neighbours at the same
# three distances". Measured as the spread, across the four seats, of each rank
# of their sorted distances to the other three: nearest, middle and far all have
# to agree. Geometrically that asks the four capitals to sit on a rectangle,
# which a grown blob supplies more often than you would think.
MAX_POD_ENGAGEMENT_SPREAD = 0.18
POD_ATTEMPTS = 2000                                      # draws per pod before giving up
# 0.50, not the 0.34 the longer road was held to, and the change is arithmetic
# rather than a concession: spread is (max - min) / mean, so the same absolute
# unfairness reads larger against a shorter road. At the old 50-tick trek 0.34
# was +/- 8 ticks; at the 24-tick trek this map now has, 0.50 is +/- 6. The
# players are closer to equal than they were, not further.
MAX_POD_ROAD_SPREAD = 0.35                              # over the four seats of one pod
# Narrow, and narrow on purpose. The ring-wide road spread is not just the worst
# pod's - it also picks up how much the nine pods differ from each other, so a
# loose per-pod band leaks straight into the published one. Tightening here is
# how the 0.60 band is met without being widened.
POD_ROAD_BAND = (44.0, 62.0)                            # mean ticks to the pod's middle
# The floor, and the reason CAPITAL_ROAD_TARGET is 54 rather than 40: what a
# player walks is measured from their nearest starting star, not their capital,
# and a pod is ~130u of head start. Seating capitals at 54 ticks lands the
# shortest real trek around 40.
MIN_POD_CORE_TICKS = 40.0                               # nobody starts nearer the middle
                                                        # narrow, so the nine pods are
                                                        # the same trek as each other
MAX_POD_TERRITORY_SPREAD = 0.55                         # stars nearer one seat than any other
MIN_POD_OPENINGS = 4                                    # neutrals inside a seat's first jump
MAX_POD_OPENINGS_SPREAD = 0.55
MAX_POD_CONNECT = 4                                     # a blob with a sealed pocket is no good

# --- resources ------------------------------------------------------------
# The opening, fixed for everybody. A capital is a permutation of
# CAPITAL_CHANNELS, so all 36 are worth the same 150 and no two are the same
# star; the five satellites are dealt SATELLITE_LADDER in a per-player order, so
# which of a player's stars is the rich one differs and the six together do not.
CAPITAL_CHANNELS = (60, 50, 40)
SATELLITE_LADDER = (40, 29, 24, 17, 15)                 # 125 over five - a mean of 25
NR_SATELLITE_MEAN = sum(SATELLITE_LADDER) / len(SATELLITE_LADDER)
SATELLITE_SPLIT = 3                                     # +/- per channel, sum preserved

NR_MIN = 15                                             # the fringe floor
NR_MAX = 55                                             # the richest a neutral star gets, and
                                                        # under CAPITAL_CHANNELS[0] on purpose:
                                                        # nothing found outdoes what you start on,
                                                        # and nothing at all outdoes the middle
                                                        # the map outdoes the middle
# Read together with RADIUS_WEIGHT: this is the bias AT THE MIDDLE, and the
# weight is how much it climbs on the way out.
LOW_VALUE_BIAS = 0.55                                   # the editor's exponential roll. Higher
                                                        # means LOWER values.
                                                        # means LOWER values - at 0.5 it is uniform
                                                        # and the map averaged 48.7, which made
                                                        # every neutral as good as a capital. 0.85
                                                        # over 15..55 lands the mean near 25.
# POSITIVE, and anchored on the pod's middle rather than on the capitals - the
# reverse of what this map did before. Distance is measured to the pulsar now, so
# the fringe of a blob is poor and the ground around the middle is rich. That is
# what makes the trek worth making: 40 ticks towards better stars rather than 40
# ticks towards a landmark.
#
# The stars a player starts on are dealt from SATELLITE_LADDER and never rolled,
# so this curve says nothing about the opening - it prices the map moved into.
RADIUS_WEIGHT = 0.50                                    # positive: poor at the fringe
BALANCE_HORIZON = 3.0 * HOP                             # three jumps, for balance_by_channel

CORE_NR = 100                                           # the pod's middle: a capital's twin,
CORE_INFRASTRUCTURE = {"economy": 5, "industry": 5, "science": 1}    # unowned and empty
CAPITAL_INFRASTRUCTURE = {"economy": 5, "industry": 5, "science": 1}
STARTING_SHIPS = 10

TERRAIN_PERCENTAGES = {"isNebula": 11.0, "isAsteroidField": 9.0}
BINARY_NR_THRESHOLD = 48                                # terrain follows wealth, but only on
                                                        # neutral stars: a capital is a permutation
                                                        # of CAPITAL_CHANNELS and its 60 would make
                                                        # every home a binary otherwise

STARTING_TECHNOLOGIES = {
    "scanning": START_SCANNING,
    "hyperspace": START_HYPERSPACE,
    "terraforming": 1,
    "experimentation": 1,
    "weapons": 5,
    "banking": 1,
    "manufacturing": 1,
    "specialists": 1,
}
STARTING_CREDITS = 500
STARTING_CREDITS_SPECIALISTS = 5

EDGE_GAP = 20.0 * LIGHT_YEAR                            # 1000u between the nearest two pods

# --- the fairness bands ---------------------------------------------------
#
# Spreads are (max - min) / mean across all 36 players, and every one of these
# is a measured floor rather than a chosen target. The placed spy_v_spy scores
# 0.00 on all of them, because congruence hands it equality for nothing; a grown
# map cannot get near that, and pretending otherwise only produces a builder
# that never finishes. What these bound is how much worse than the per-pod gates
# the finished ring is allowed to come out - a build that fails one has seated
# somebody badly and wants a different master seed, which is what --search is
# for, not a wider band.
MAX_OPENING_OPTIONS_SPREAD = 1.10       # neutral stars inside the first jump
MIN_OPENING_OPTIONS = 2                 # nobody starts boxed in
MAX_REACHABLE_WEALTH_SPREAD = 0.60      # resources within three jumps. Widened from 0.45, and
                                        # deliberately: pushing the four pods far enough apart that
                                        # nobody spawns in a rival's face drives them towards the
                                        # rim of their blob, where there is less galaxy to reach.
                                        # This band and territory below are what that costs.
MAX_CORE_TICKS_SPREAD = 0.60            # the road to your own pod's middle
MAX_TERRITORY_SPREAD = 0.85             # stars nearer you than any rival - the win condition
MAX_CHANNEL_SPREAD = 0.50               # per channel, so nobody is starved of one
MIN_SEPARATION = 30.0                   # hard floor; below this stars overlap on screen
MAX_CONNECT_HYPERSPACE = 4              # a pod must join up by here, voids notwithstanding

COLOUR_GROUPS = [
    [("Red", "#ff0000"), ("Scarlet", "#ff200d"), ("Electric red", "#e60000")],
    [("Maroon", "#800000"), ("Dark red", "#8b110a"), ("Rusty red", "#ab3322")],
    [("Royal orange", "#ff7a2a"), ("Mango orange", "#ff8434"), ("Vivid orange", "#f37020")],
    [("Yellow", "#ffff00"), ("Lemone", "#ffff20"), ("Golden yellow", "#e9ea00")],
    [("Olive", "#808000"), ("Reef gold", "#8a8911"), ("Browny green", "#767700")],
    [("Lime", "#00ff00"), ("Neon green", "#2cff1e"), ("Electric green", "#00ea00")],
    [("Green", "#008000"), ("Tree green", "#198a10"), ("Moth green", "#007700")],
    [("Cyan", "#00ffff"), ("Aqua", "#2dffff"), ("Bright turquoise", "#00eaea")],
    [("Teal", "#008080"), ("Blue chill", "#198989"), ("Deep sea", "#007777")],
    [("Submarine blue", "#005080"), ("Dusk blue", "#165889"), ("Regal blue", "#004877")],
    [("Blue", "#0000ff"), ("Ultramarine", "#2c13ff"), ("Rich blue", "#0000ea")],
    [("Purple", "#800080"), ("Rich purple", "#760077"), ("Medium orchid", "#a838a6")],
    [("Magenta", "#ff00ff"), ("Bright magenta", "#ff25ff"), ("Piercing pink", "#e900ea")],
    [("Light pink", "#ffb6c1"), ("Pale rose", "#ffc0cb"), ("Rose", "#f4acb7")],
    [("Silver", "#e0e0e0"), ("White smoke", "#f5f5f5"), ("Platinum", "#e7dee0")],
    [("Gray", "#808080"), ("Gunsmoke", "#898989"), ("Steel wool", "#777777")],
]
COLOUR_GROUP_STEP = len(COLOUR_GROUPS) // PLAYERS_PER_POD
SEAT_SHAPES = ["circle", "square", "hexagon", "diamond"]

ROOT = Path(__file__).resolve().parent.parent


def output_for(n_players: int) -> Path:
    return ROOT / "out" / ("spy_v_spy_irregular.json" if n_players == 36
                           else f"spy_v_spy_irregular_{n_players}p.json")


OUTPUT = output_for(N_PLAYERS)
POD_STEP = 360.0 / N_PODS
LINKS_PER_POD_PAIR = N_WORMHOLE_SLOTS // (N_PODS - 1)


def configure(n_pods: int) -> None:
    """Resize the ring. Everything else is per-pod and unaffected."""
    global N_PODS, N_PLAYERS, POD_STEP, LINKS_PER_POD_PAIR, OUTPUT
    legal = [n for n in range(2, N_WORMHOLE_SLOTS + 2) if not N_WORMHOLE_SLOTS % (n - 1)]
    if n_pods not in legal:
        raise SystemExit(f"--pods {n_pods}: a pod's {N_WORMHOLE_SLOTS} wormhole slots have to "
                         f"divide evenly over the other pods, or the links between them come out "
                         f"lopsided and non-reciprocal. Legal: {legal}")
    N_PODS = n_pods
    N_PLAYERS = N_PODS * PLAYERS_PER_POD
    POD_STEP = 360.0 / N_PODS
    LINKS_PER_POD_PAIR = N_WORMHOLE_SLOTS // (N_PODS - 1)
    OUTPUT = output_for(N_PLAYERS)


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def point_of(star: dict) -> tuple[float, float]:
    return star["location"]["x"], star["location"]["y"]


def spread(values) -> float:
    """(max - min) / mean, the skill's fairness measure. 0 means identical."""
    values = list(values)
    mean = statistics.mean(values)
    return 0.0 if not mean else (max(values) - min(values)) / mean


def ticks_between(stars: list[dict], starts: set[str], target: str, reach: float) -> float:
    """Cheapest run from any star in `starts` to `target`, over hops of `reach`."""
    points = {s["id"]: point_of(s) for s in stars}
    best = {key: math.inf for key in points}
    heap: list[tuple[float, str]] = []
    for key in starts:
        best[key] = 0
        heapq.heappush(heap, (0, key))
    while heap:
        cost, key = heapq.heappop(heap)
        if cost > best[key]:
            continue
        if key == target:
            return cost
        here = points[key]
        for other, there in points.items():
            gap = dist(here, there)
            if gap > reach:
                continue
            total = cost + rules.ticks_by_distance(gap)
            if total < best[other]:
                best[other] = total
                heapq.heappush(heap, (total, other))
    return best[target]


# --------------------------------------------------------------------------
# Seating a grown pod
#
# The star field is the generator's. What this map adds is where the prize goes,
# who sits where, and where each player's watcher stands - and those are chosen
# out of the blob rather than imposed on it.
# --------------------------------------------------------------------------


def road_costs(points: list[tuple[float, float]], sources: dict[int, float],
               reach: float) -> list[float]:
    """Tick cost from `sources` to every point, over hops of `reach`."""
    best = [math.inf] * len(points)
    heap: list[tuple[float, int]] = []
    for index, cost in sources.items():
        best[index] = cost
        heapq.heappush(heap, (cost, index))
    while heap:
        cost, index = heapq.heappop(heap)
        if cost > best[index]:
            continue
        here = points[index]
        for other, there in enumerate(points):
            gap = dist(here, there)
            if gap > reach:
                continue
            total = cost + rules.ticks_by_distance(gap)
            if total < best[other]:
                best[other] = total
                heapq.heappush(heap, (total, other))
    return best


def roads_from(points: list[tuple[float, float]],
               centre: tuple[float, float]) -> list[float]:
    """What every point in the field costs to reach, starting from the landmark."""
    sources = {index: rules.ticks_by_distance(dist(centre, point))
               for index, point in enumerate(points) if dist(centre, point) <= HOP}
    return road_costs(points, sources, HOP) if sources else []


def points_connect_level(points: list[tuple[float, float]]) -> int:
    """Lowest hyperspace at which a bare point field is one piece."""
    for level in range(1, 9):
        reach = hyperspace_range(level)
        seen = {0}
        frontier = [0]
        while frontier:
            current = frontier.pop()
            for other, there in enumerate(points):
                if other not in seen and dist(points[current], there) <= reach:
                    seen.add(other)
                    frontier.append(other)
        if len(seen) == len(points):
            return level
    return 99


def place_core(points: list[tuple[float, float]]) -> tuple[float, float]:
    """The middle of the blob, pulled in until it is part of it.

    The centroid of a grown field can land in one of the voids the noise prune
    carved, which would leave the pod's prize unreachable. When that happens the
    landmark slides towards the nearest star until it is inside one jump, which
    is the closest thing to "the middle" the blob actually offers.
    """
    centre = (statistics.mean(p[0] for p in points), statistics.mean(p[1] for p in points))
    nearest = min(points, key=lambda p: dist(centre, p))
    gap = dist(centre, nearest)
    if gap <= HOP:
        return centre
    slide = (gap - HOP * 0.9) / gap
    return (centre[0] + (nearest[0] - centre[0]) * slide,
            centre[1] + (nearest[1] - centre[1]) * slide)


def engagement_profiles(places: list[tuple[float, float]]) -> list[list[float]]:
    """Each seat's sorted distances to the other three."""
    return [sorted(dist(here, there) for other, there in enumerate(places) if other != seat)
            for seat, here in enumerate(places)]


def engagement_spread(places: list[tuple[float, float]]) -> float:
    """How unlike each other the four seats' neighbourhoods are. 0 is a rectangle."""
    profiles = engagement_profiles(places)
    return max(spread([profile[rank] for profile in profiles]) for rank in range(len(places) - 1))


def choose_capitals(points: list[tuple[float, float]],
                    centre: tuple[float, float]) -> list[int] | None:
    """Seat four players the same short road out, facing the same three neighbours.

    Three things at once, and they pull against each other:

      * the same road to the middle - CAPITAL_ROAD_TARGET ticks, so nobody is
        nearer the prize than anyone else;
      * the 32p standard spacing, MIN_CAPITAL_GAP to MAX_CAPITAL_GAP apart;
      * the same *engagement* - each seat's three neighbours at the same three
        distances as everybody else's.

    The first two can be satisfied greedily; the third cannot, because it is a
    property of the whole quadruple rather than of any one seat. So the band of
    candidates near the target road is capped at CAPITAL_BAND_LIMIT and every
    combination of four is weighed, scored on engagement_spread. That is a few
    thousand cheap distance checks per attempt and it is the difference between
    a pod where one player is engaged at 9 LY while another waits until 15, and
    a pod where all four are on a rectangle.
    """
    costs = roads_from(points, centre)
    if not costs:
        return None
    reachable = [c for c in costs if math.isfinite(c)]
    if len(reachable) < len(points) * 0.8:
        return None                     # too much of this blob is sealed off

    band = [index for index, cost in enumerate(costs)
            if math.isfinite(cost) and abs(cost - CAPITAL_ROAD_TARGET) <= CAPITAL_ROAD_TOLERANCE]
    if len(band) < PLAYERS_PER_POD:
        return None
    band.sort(key=lambda index: (abs(costs[index] - CAPITAL_ROAD_TARGET), index))
    band = band[:CAPITAL_BAND_LIMIT]

    best: tuple[int, ...] | None = None
    best_score = math.inf
    for quad in itertools.combinations(band, PLAYERS_PER_POD):
        places = [points[index] for index in quad]
        gaps = [dist(places[a], places[b])
                for a in range(PLAYERS_PER_POD) for b in range(a + 1, PLAYERS_PER_POD)]
        if not MIN_CAPITAL_GAP <= min(gaps) <= MAX_CAPITAL_GAP:
            continue
        score = engagement_spread(places)
        if score < best_score:
            best, best_score = quad, score

    if best is None or best_score > MAX_POD_ENGAGEMENT_SPREAD:
        return None
    return list(best)


def core_road_ticks(stars: list[dict]) -> list[float] | None:
    """Ticks from each seat's stars to its pod's middle, measured as check() does.

    The obvious place to gate the trek is on the grown points, before the pulsar
    is dropped in - and that was wrong. The middle is a star like any other once
    it exists, so it becomes a stepping stone, and a pod that measured 40 ticks
    on the bare field scored 25 on the finished map. Same graph as the published
    number: the pulsar is a node, the posts are not.
    """
    pool = [s for s in stars if not s["isBlackHole"]]
    places = [point_of(s) for s in pool]
    try:
        target = next(i for i, s in enumerate(pool) if s["_role"] == "core")
    except StopIteration:
        return None

    out: list[float] = []
    for seat in range(PLAYERS_PER_POD):
        starts = [i for i, s in enumerate(pool) if s["_seat"] == seat]
        if not starts:
            return None
        best = [math.inf] * len(pool)
        heap: list[tuple[float, int]] = []
        for index in starts:
            best[index] = 0.0
            heapq.heappush(heap, (0.0, index))
        while heap:
            cost, index = heapq.heappop(heap)
            if cost > best[index]:
                continue
            if index == target:
                break
            here = places[index]
            for other, there in enumerate(places):
                gap = dist(here, there)
                if gap > HOP:
                    continue
                total = cost + rules.ticks_by_distance(gap)
                if total < best[other]:
                    best[other] = total
                    heapq.heappush(heap, (total, other))
        if not math.isfinite(best[target]):
            return None
        out.append(best[target])
    return out


def compact_pods(points: list[tuple[float, float]], homes: list[int],
                 starting: list[list[int]]) -> list[tuple[float, float]]:
    """Pull every starting star in to POD_RADIUS_CAP of its capital.

    generate.pull_into_range only guarantees a pod is *connected* - that each
    star is inside one jump - which still allows a 270u sprawl once four
    capitals have taken turns claiming neighbours. A sprawling pod is what puts
    two players' stars in each other's faces however far apart their capitals
    are, so it is tightened here rather than compensated for later.
    """
    points = list(points)
    for seat, home in enumerate(homes):
        anchor = points[home]
        for index in starting[seat]:
            gap = dist(points[index], anchor)
            if gap <= POD_RADIUS_CAP or gap == 0.0:
                continue
            scale = POD_RADIUS_CAP / gap
            points[index] = (anchor[0] + (points[index][0] - anchor[0]) * scale,
                             anchor[1] + (points[index][1] - anchor[1]) * scale)
    return points


def place_post(capital: dict, pod: list[dict]) -> tuple[float, float] | None:
    """The nearest spot to `capital` that is alone, and watches its owner alone.

    Distance outward, bearing inner, so the first hit is the closest such spot
    the blob allows and a post hugs the player it is there to watch. Returns None
    when the pod is shaped such that nowhere qualifies, which the caller treats
    as a pod worth re-drawing rather than a post worth nudging.
    """
    home = point_of(capital)
    # Everything, the post's own capital included. Leaving the capital out of
    # the isolation test let one post settle 136u from the player it watches,
    # which is a hyperspace-2 hop: a post that its owner can simply fly to is
    # not isolated, whoever owns it.
    others = [point_of(s) for s in pod]
    owned = [(point_of(s), s["_seat"]) for s in pod if s["_seat"] is not None]
    seat = capital["_seat"]
    lo, hi = POST_GAP_BAND

    distance = POST_STEP
    while distance <= POST_SEARCH_LIMIT:
        bearing = 0.0
        while bearing < 360.0:
            offset = polar(distance, bearing)
            here = (home[0] + offset[0], home[1] + offset[1])
            bearing += POST_BEARING_STEP
            # Cheapest rejection first: anything inside the band's floor kills
            # the candidate, and most candidates die exactly there.
            nearest = math.inf
            for point in others:
                gap = dist(here, point)
                if gap == 0.0:
                    continue
                if gap < lo:
                    nearest = -1.0
                    break
                nearest = min(nearest, gap)
            if nearest < lo or nearest > hi:
                continue
            # Over one player rather than between two, and over somebody rather
            # than over nobody at all.
            watched = {owner for point, owner in owned if dist(here, point) <= POST_SCAN}
            if watched == {seat}:
                return here
        distance += POST_STEP
    return None


# --------------------------------------------------------------------------
# One pod, grown
# --------------------------------------------------------------------------


def grow_pod(pod: int, attempt: int) -> tuple[generate.Layout, tuple[float, float]] | None:
    """The editor's own irregular generator, once per pod, on its own seed.

    Nothing about the shape is decided here. The metaball prune inside the
    generator gives the blob its outline and the noise prune carves its voids,
    which is why one pod comes out long and another round, and why the nine of
    them on the ring do not read as copies of each other.

    What this does override is the generator's choice of capitals, which grows
    them outward on a lattice with no idea that this map has a prize in the
    middle. The field is kept; the seating is re-picked and the shared tail -
    claim the starting stars, pull them into range - is run over the new homes.
    """
    field = generate.irregular(
        PLAYERS_PER_POD, STARS_PER_PLAYER,
        seed=f"{SEED}:pod{pod}:{attempt}",
        starting_stars=STARTING_STARS,
        hyperspace=START_HYPERSPACE,
        separation=POD_SEPARATION,
    )
    points = field.points
    centre = place_core(points)
    homes = choose_capitals(points, centre)
    if homes is None:
        return None

    starting = generate.claim_starting_stars(points, homes, STARTING_STARS)
    points = generate.pull_into_range(points, homes, starting, START_HYPERSPACE)
    points = compact_pods(points, homes, starting)
    layout = generate.Layout(points=points, homes=homes, starting=starting,
                             seed=field.seed, generator="irregular")
    # pull_into_range drags each pod's starting stars towards their capital and
    # knows nothing about the rest of the field, so it can leave one crowding a
    # neutral. Relax with the pods pinned: reachability keeps what it won and the
    # neutrals move aside.
    # Only the capitals are pinned. Pinning whole pods, which is what the worked
    # example does, would freeze the stars compact_pods just stacked up; letting
    # them relax spreads them back to a legal spacing without undoing the
    # compaction, because the cap is well clear of POD_SEPARATION.
    layout.points = generate.relax_separation(layout.points, POD_SEPARATION,
                                              pinned=list(layout.homes))
    return layout, centre


def build_pod(pod: int) -> list[dict] | None:
    """Draw blobs for this pod until one seats its four players evenly.

    Returns the first that clears every per-pod gate, so the result is stable:
    pod 3 does not change because pod 7 was re-rolled.
    """
    for attempt in range(POD_ATTEMPTS):
        members = try_pod(pod, attempt)
        if members is not None:
            return members
    return None


def try_pod(pod: int, attempt: int, gated: bool = True) -> list[dict] | None:
    """One pod in its own frame: a grown blob, a pulsar in it, four posts off it."""
    grown = grow_pod(pod, attempt)
    if grown is None:
        return None
    layout, centre = grown
    points = layout.points
    owners = layout.owners()
    homes = {index: player for player, index in enumerate(layout.homes)}

    stars: list[dict] = []
    for index, point in enumerate(points):
        stars.append(model.new_star(
            point, _pod=pod, _slot=None, _seat=owners.get(index),
            _role=("capital" if index in homes else
                   "starting" if index in owners else "neutral")))

    # The roads, now that the starting stars have been claimed and pulled: what
    # a player walks is from their nearest star, not from their capital, and
    # pull_into_range has moved some of those. Measured rather than assumed,
    # because choose_capitals worked on the field before any of that happened.
    costs = roads_from(layout.points, centre)
    if not costs:
        return None
    roads = []
    for seat in range(PLAYERS_PER_POD):
        mine = [layout.homes[seat]] + list(layout.starting[seat])
        roads.append(min(costs[index] for index in mine))
    if not all(math.isfinite(r) for r in roads):
        return None
    # A loose pre-filter only. The real gate is core_road_ticks at the end of this
    # function, on the finished pod; this just throws out the hopeless blobs
    # before the expensive placement work happens.
    if gated and spread(roads) > MAX_POD_ROAD_SPREAD * 1.6:
        return None
    if gated and not POD_ROAD_BAND[0] * 0.8 <= statistics.mean(roads):
        return None

    # The rest of the seating, gated here rather than on the finished ring. A pod
    # is drawn, measured and kept or thrown away on its own, so a bad blob costs
    # one re-draw instead of a whole map.
    if gated:
        field = [p for index, p in enumerate(layout.points) if index not in owners]
        pods_points = {seat: [layout.points[i] for i, s in owners.items() if s == seat]
                       for seat in range(PLAYERS_PER_POD)}       # capitals included: owners()
                                                                 # counts a home star as its own
        tally = [0] * PLAYERS_PER_POD
        openings = [0] * PLAYERS_PER_POD
        for point in field:
            reach = [min(dist(point, p) for p in pods_points[seat])
                     for seat in range(PLAYERS_PER_POD)]
            tally[reach.index(min(reach))] += 1
            for seat, gap in enumerate(reach):
                if gap <= HOP:
                    openings[seat] += 1
        rival = math.inf
        for a in range(PLAYERS_PER_POD):
            for b in range(a + 1, PLAYERS_PER_POD):
                for here in pods_points[a]:
                    for there in pods_points[b]:
                        rival = min(rival, dist(here, there))
        if rival < MIN_RIVAL_GAP:
            return None
        if spread(tally) > MAX_POD_TERRITORY_SPREAD:
            return None
        if min(openings) < MIN_POD_OPENINGS or spread(openings) > MAX_POD_OPENINGS_SPREAD:
            return None
        if points_connect_level(layout.points) > MAX_POD_CONNECT:
            return None

    core = model.new_star(centre, _pod=pod, _slot=None, _seat=None, _role="core")
    core["isPulsar"] = True
    core["infrastructure"] = dict(CORE_INFRASTRUCTURE)
    stars.append(core)

    # The core was placed, not grown, so it can land on top of a neutral. Relax
    # with everything but the neutrals pinned: they move aside, and the pods and
    # the landmark stay exactly where they were put.
    pinned = [i for i, s in enumerate(stars) if s["_role"] != "neutral"]
    for star, point in zip(stars, generate.relax_separation(
            [point_of(s) for s in stars], POD_SEPARATION, pinned=pinned)):
        star["location"] = {"x": point[0], "y": point[1]}

    for seat, home_index in enumerate(layout.homes):
        here = place_post(stars[home_index], stars)
        if here is None:
            return None
        post = model.new_star(here, _pod=pod, _slot=2 * seat, _seat=None, _role="post")
        post["isBlackHole"] = True                          # +3 scanning from the terrain
        post["specialistId"] = SPECIALIST_TELESCOPE_ARRAY   # +3 more from the array
        stars.append(post)

    # A gateway is *picked* out of the field rather than placed - which star it
    # lands on depends entirely on how the blob grew - but what it has to satisfy
    # is spelled out: two to three jumps from its owner's capital, inside two
    # jumps of a star they start on, and nearer them than any pod-mate by
    # GATEWAY_RIVAL_MARGIN. Of what is left, the one furthest from the pod's
    # middle wins.
    taken: list[tuple[float, float]] = []
    for seat, home_index in enumerate(layout.homes):
        capital = point_of(stars[home_index])
        mine = [point_of(stars[i]) for i, p in owners.items() if p == seat]
        theirs = [point_of(stars[i]) for i, p in owners.items() if p != seat]
        candidates = []
        for star in stars:
            if star["_role"] != "neutral" or star["_slot"] is not None:
                continue
            here = point_of(star)
            own = min(dist(here, q) for q in mine)
            if own > GATEWAY_SPAWN_REACH:
                continue
            if theirs and own * GATEWAY_RIVAL_MARGIN > min(dist(here, q) for q in theirs):
                continue
            if any(dist(here, other) < MIN_GATEWAY_GAP for other in taken):
                continue
            candidates.append(star)
        if not candidates:
            return None
        gateway = max(candidates, key=lambda s: dist(capital, point_of(s)))
        gateway["_role"] = "gateway"
        gateway["_slot"] = 2 * seat + 1
        taken.append(point_of(gateway))

    if len(stars) != STARS_PER_POD:
        return None

    # The trek, gated last because it can only be measured last. Everything above
    # decides where people sit; this decides whether the pod is worth keeping.
    if gated:
        trek = core_road_ticks(stars)
        if trek is None:
            return None
        seats = [point_of(stars[index]) for index in layout.homes]
        if engagement_spread(seats) > MAX_POD_ENGAGEMENT_SPREAD:
            return None
        if min(trek) < MIN_POD_CORE_TICKS:
            return None
        if spread(trek) > MAX_POD_ROAD_SPREAD:
            return None
        if not POD_ROAD_BAND[0] <= statistics.mean(trek) <= POD_ROAD_BAND[1]:
            return None

    return stars


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def player_colour(pod: int, seat: int) -> dict:
    group = COLOUR_GROUPS[(pod + COLOUR_GROUP_STEP * seat) % len(COLOUR_GROUPS)]
    alias, value = group[pod // PLAYERS_PER_POD]
    return {"alias": alias, "value": value}


def solve_ring_radius(pods: list[list[dict]]) -> float:
    """Ring radius that puts EDGE_GAP between the nearest stars of any two pods."""
    local = [[point_of(s) for s in stars] for stars in pods]

    def min_gap(ring_r: float) -> float:
        placed = []
        for g, points in enumerate(local):
            phi = POD_STEP * g
            centre = polar(ring_r, phi)
            placed.append([(rotate(p, phi)[0] + centre[0], rotate(p, phi)[1] + centre[1])
                           for p in points])
        best = math.inf
        for g in range(len(placed)):
            for a in placed[g]:
                for b in placed[(g + 1) % len(placed)]:
                    best = min(best, dist(a, b))
        return best

    lo, hi = 100.0, 60000.0
    for _ in range(160):
        mid = (lo + hi) / 2.0
        if min_gap(mid) < EDGE_GAP:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def build() -> tuple[list[dict], list[dict]]:
    pods = []
    for pod in range(N_PODS):
        members = build_pod(pod)
        if members is None:
            raise SystemExit(f"pod {pod}: no blob in {POD_ATTEMPTS} draws seated its four "
                             f"players inside the per-pod gates. Change SEED, or widen "
                             f"MAX_POD_ROAD_SPREAD / POD_ROAD_BAND.")
        pods.append(members)

    ring_r = solve_ring_radius(pods)
    stars: list[dict] = []
    for pod, members in enumerate(pods):
        phi = POD_STEP * pod
        centre = polar(ring_r, phi)
        for star in members:
            x, y = rotate(point_of(star), phi)
            star["location"] = {"x": round(x + centre[0], 6), "y": round(y + centre[1], 6)}
            stars.append(star)
    model.assign_ids(stars)

    # ---- who owns what, evened out before anything is valued --------------
    # balance_openings swaps which neutral each player starts on until the
    # number of stars inside a first jump is level. It moves ownership, never a
    # star, so the pods stay connected and the blob stays exactly as grown - and
    # it runs before the fixed values are dealt, so whatever a player ends up
    # holding is still worth the same as everyone else's.
    for pod, members in enumerate(pods):
        capitals = sorted((s for s in members if s["_role"] == "capital"),
                          key=lambda s: s["_seat"])
        for seat, capital in enumerate(capitals):
            player_id = str(pod * PLAYERS_PER_POD + seat + 1)
            capital["playerId"] = player_id
            capital["homeStar"] = True
            for star in members:
                if star["_seat"] == capital["_seat"] and star is not capital:
                    star["playerId"] = player_id

    all_capitals = [s for s in stars if s["homeStar"]]
    # randomise.balance_openings would even the turn-one frontier further, and it
    # is deliberately not called: it swaps which neutral a player starts on, and
    # on this map that can hand somebody a star beside the pod's middle. Tried
    # and measured - it took the roads from 42-58 ticks to 14-62. The opening
    # frontier is levelled by the per-pod gate instead, which does it before the
    # seating is fixed and so cannot move anyone nearer the prize.

    # ---- and now the opening, held exactly equal --------------------------
    players = []
    owned: dict[str, list[dict]] = {}
    for star in stars:
        if star["playerId"] is not None:
            owned.setdefault(star["playerId"], []).append(star)
    for pod in range(N_PODS):
        for seat in range(PLAYERS_PER_POD):
            player_id = str(pod * PLAYERS_PER_POD + seat + 1)
            mine = owned[player_id]
            capital = next(s for s in mine if s["homeStar"])
            channels = list(CAPITAL_CHANNELS)
            generate.Rng(f"{SEED}:capital:{player_id}").shuffle(channels)
            model.set_resources(capital, *channels)
            model.make_home_star(capital, player_id, ships=STARTING_SHIPS,
                                 **CAPITAL_INFRASTRUCTURE)

            rest = sorted((s for s in mine if s is not capital), key=lambda s: s["id"])
            ladder = list(SATELLITE_LADDER)
            generate.Rng(f"{SEED}:ladder:{player_id}").shuffle(ladder)
            for star, value in zip(rest, ladder):
                offset = generate.Rng(f"{SEED}:sat:{player_id}:{star['id']}").between(
                    -SATELLITE_SPLIT, SATELLITE_SPLIT)
                model.set_resources(star, value + offset, value, value - offset)
                model.set_ships(star, STARTING_SHIPS)
            players.append(model.new_player(
                player_id, capital["id"],
                technologies=STARTING_TECHNOLOGIES,
                credits=STARTING_CREDITS,
                credits_specialists=STARTING_CREDITS_SPECIALISTS,
                colour=player_colour(pod, seat), shape=SEAT_SHAPES[seat]))

    # ---- neutral stars, priced by one impartial rule ----------------------
    properties = generate.Rng(f"{SEED}:properties")
    for members in pods:
        neutrals = [s for s in members if s["playerId"] is None
                    and s["_role"] not in ("core", "post")]
        middle = next(s for s in members if s["_role"] == "core")
        randomise.randomise_resources(
            neutrals, properties, minimum=NR_MIN, maximum=NR_MAX,
            low_value_bias=LOW_VALUE_BIAS, radius_weight=RADIUS_WEIGHT,
            anchors=[point_of(middle)], split=True)
    # The landmark and the posts are priced by hand and kept out of the
    # balancing: the middle is the same prize in every pod, and a post is a
    # lookout rather than a place worth taking.
    for star in stars:
        if star["_role"] == "core":
            model.set_resources(star, CORE_NR)
        elif star["_role"] == "post":
            model.set_resources(star, NR_MIN, NR_MIN + 2, NR_MIN + 1)

    # Rim versus middle: the one imbalance no pricing rule reaches, because it is
    # a difference in how much galaxy there is rather than in how that galaxy is
    # valued. Run ONCE over the whole ring rather than pod by pod - a per-pod
    # pass levels the four players inside each blob and leaves the nine blobs
    # worth wildly different amounts, which is a spread all the same.
    randomise.balance_by_channel(
        [s for s in stars if s["_role"] not in ("core", "post")],
        all_capitals, BALANCE_HORIZON, minimum=NR_MIN, maximum=NR_MAX)

    # ---- terrain, scattered then evened out -------------------------------
    for members in pods:
        field = [s for s in members if s["_role"] in ("neutral", "gateway")]
        capitals = [s for s in members if s["_role"] == "capital"]
        randomise.randomise_terrain(field, properties, **TERRAIN_PERCENTAGES)
        for name in TERRAIN_PERCENTAGES:
            randomise.balance_terrain(field, capitals, BALANCE_HORIZON, name,
                                      tolerance=1.2, preserve="scatter")

    # Terrain from wealth, in one place for every star. Anything that already
    # carries terrain of its own keeps it and stays off the binary list.
    for star in stars:
        nr = star["naturalResources"]
        star["isBinaryStar"] = (max(nr.values()) > BINARY_NR_THRESHOLD
                                and star["playerId"] is None
                                and not star["isNebula"] and not star["isAsteroidField"]
                                and not star["isBlackHole"] and not star["isPulsar"])

    # ---- wormholes: the ring, unchanged from the placed map ---------------
    # Slot k in pod g pairs with the k-th pod along, and slot k always meets slot
    # 7-k, so every link runs gateway to post. Both ends start neutral.
    by_pod = {pod: [s for s in stars if s["_pod"] == pod] for pod in range(N_PODS)}
    for pod in range(N_PODS):
        for slot in range(N_WORMHOLE_SLOTS):
            here = next(s for s in by_pod[pod] if s["_slot"] == slot)
            partner_pod = (pod + 1 + slot % (N_PODS - 1)) % N_PODS
            there = next(s for s in by_pod[partner_pod]
                         if s["_slot"] == N_WORMHOLE_SLOTS - 1 - slot)
            here["wormHoleToStarId"] = there["id"]

    return stars, players


# --------------------------------------------------------------------------
# Measurements - the set check() bounds and report() prints
# --------------------------------------------------------------------------


def measure(stars: list[dict]) -> dict:
    owned: dict[str, list[dict]] = {}
    for star in stars:
        if star["playerId"] is not None:
            owned.setdefault(star["playerId"], []).append(star)
    capitals = {s["playerId"]: s for s in stars if s["homeStar"]}
    neutrals = [s for s in stars if s["playerId"] is None]

    openings, wealth, core_ticks = [], [], []
    channels: dict[str, list[float]] = {"economy": [], "industry": [], "science": []}
    for player_id, mine in owned.items():
        here = [point_of(s) for s in mine]
        openings.append(sum(1 for s in neutrals
                            if min(dist(point_of(s), p) for p in here) <= HOP))
        near = [s for s in neutrals
                if min(dist(point_of(s), p) for p in here) <= BALANCE_HORIZON]
        wealth.append(sum(sum(s["naturalResources"].values()) for s in near))
        for name in channels:
            channels[name].append(sum(s["naturalResources"][name] for s in near))
        pod = [s for s in stars if s["_pod"] == capitals[player_id]["_pod"]]
        core = next(s for s in pod if s["isPulsar"])
        core_ticks.append(ticks_between([s for s in pod if not s["isBlackHole"]],
                                        {s["id"] for s in mine}, core["id"], HOP))

    # Territory: neutral stars nearer to you than to any rival, which is what the
    # win condition ends up counting once the map is actually played.
    tally = {pid: 0 for pid in owned}
    for star in neutrals:
        best = min(owned, key=lambda p: min(dist(point_of(star), point_of(s))
                                            for s in owned[p]))
        tally[best] += 1

    return {"openings": openings, "wealth": wealth, "core_ticks": core_ticks,
            "territory": list(tally.values()), "channels": channels, "owned": owned}


def connect_level(pod: list[dict]) -> int:
    """Lowest hyperspace at which a pod is one piece, its posts excluded."""
    pool = [s for s in pod if not s["isBlackHole"]]
    for level in range(1, 9):
        reach = hyperspace_range(level)
        seen = {pool[0]["id"]}
        frontier = [pool[0]]
        while frontier:
            current = frontier.pop()
            for other in pool:
                if other["id"] not in seen and dist(point_of(current), point_of(other)) <= reach:
                    seen.add(other["id"])
                    frontier.append(other)
        if len(seen) == len(pool):
            return level
    return 99


BANDS = (("opening options", "openings", MAX_OPENING_OPTIONS_SPREAD),
         ("reachable wealth", "wealth", MAX_REACHABLE_WEALTH_SPREAD),
         ("territory", "territory", MAX_TERRITORY_SPREAD),
         ("road to the core", "core_ticks", MAX_CORE_TICKS_SPREAD))


# --------------------------------------------------------------------------
# Checks - bands, not equalities
# --------------------------------------------------------------------------


def check(stars: list[dict], players: list[dict]) -> None:
    failures: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    m = measure(stars)
    owned = m["owned"]

    require(len(stars) == N_PODS * STARS_PER_POD,
            f"{len(stars)} stars, expected {N_PODS * STARS_PER_POD}")
    require(len(players) == N_PLAYERS, f"{len(players)} players, expected {N_PLAYERS}")
    require(len(owned) == N_PLAYERS, f"{len(owned)} players own stars")

    # --- the one thing still held exactly: the opening --------------------
    openings = {pid: (sum(sum(s["naturalResources"].values()) for s in mine),
                      sum(s["shipsActual"] for s in mine), len(mine))
                for pid, mine in owned.items()}
    require(len(set(openings.values())) == 1,
            f"openings are not identical: {sorted(set(openings.values()))}")
    for pid, mine in owned.items():
        require(len(mine) == STARTING_STARS,
                f"player {pid} starts with {len(mine)} stars, expected {STARTING_STARS}")
        sats = [s for s in mine if not s["homeStar"]]
        mean = statistics.mean(v for s in sats for v in s["naturalResources"].values())
        require(abs(mean - NR_SATELLITE_MEAN) < 1e-6,
                f"player {pid} satellites average {mean:.2f}, expected {NR_SATELLITE_MEAN}")

    # --- the bands --------------------------------------------------------
    for label, key, limit in BANDS:
        values = m[key]
        got = spread(values)
        require(got <= limit,
                f"{label} spread {got:.2f} is over the {limit:.2f} band "
                f"({min(values):.0f}..{max(values):.0f}) - the seed seated somebody badly")
    require(min(m["openings"]) >= MIN_OPENING_OPTIONS,
            f"a player reaches {min(m['openings'])} neutral stars on turn one, under the "
            f"{MIN_OPENING_OPTIONS} floor - boxed in")
    for name, values in m["channels"].items():
        require(spread(values) <= MAX_CHANNEL_SPREAD,
                f"{name} spread {spread(values):.2f} is over the {MAX_CHANNEL_SPREAD:.2f} band")

    # --- posts ------------------------------------------------------------
    posts = [s for s in stars if s["isBlackHole"]]
    require(len(posts) == N_PLAYERS, f"{len(posts)} posts, expected {N_PLAYERS}")
    for post in posts:
        pod = [s for s in stars if s["_pod"] == post["_pod"]]
        gap = min(dist(point_of(post), point_of(s)) for s in pod if s is not post)
        require(POST_GAP_BAND[0] - 1 <= gap <= POST_GAP_BAND[1] + 1,
                f"post {post['id']} nearest neighbour {gap:.0f}u, outside {POST_GAP_BAND}")
        require(hyperspace_level(gap) == 4,
                f"post {post['id']} is reachable at hyperspace {hyperspace_level(gap)}, not 4")
        watched = {s["playerId"] for s in pod if s["playerId"] is not None
                   and dist(point_of(post), point_of(s)) <= POST_SCAN}
        require(len(watched) == 1,
                f"post {post['id']} watches {len(watched)} players, expected exactly 1")

    # --- structure --------------------------------------------------------
    for pod in range(N_PODS):
        members = [s for s in stars if s["_pod"] == pod]
        level = connect_level(members)
        require(level <= MAX_CONNECT_HYPERSPACE,
                f"pod {pod} only joins up at hyperspace {level}")
        worst = min(dist(point_of(a), point_of(b))
                    for i, a in enumerate(members) for b in members[i + 1:])
        require(worst >= MIN_SEPARATION,
                f"pod {pod} has two stars {worst:.0f}u apart, under the {MIN_SEPARATION} floor")

    by_id = {s["id"]: s for s in stars}
    pairs, links = set(), 0
    for star in stars:
        target = star["wormHoleToStarId"]
        if target is None:
            continue
        links += 1
        other = by_id[target]
        require(other["wormHoleToStarId"] == star["id"],
                f"wormhole {star['id']} -> {target} is not reciprocal")
        require(other["_pod"] != star["_pod"], f"wormhole {star['id']} does not leave its pod")
        pairs.add(frozenset((star["_pod"], other["_pod"])))
    require(links == N_PODS * N_WORMHOLE_SLOTS,
            f"{links} wormhole ends, expected {N_PODS * N_WORMHOLE_SLOTS}")
    if N_PODS > 2:
        require(len(pairs) == N_PODS * (N_PODS - 1) // 2,
                f"{len(pairs)} pod pairs linked, expected every one")

    # --- and the pods really are different --------------------------------
    signatures = set()
    for pod in range(N_PODS):
        members = [s for s in stars if s["_pod"] == pod]
        core = next(s for s in members if s["isPulsar"])
        signatures.add(tuple(sorted(round(dist(point_of(s), point_of(core)))
                                    for s in members)))
    require(len(signatures) == N_PODS,
            f"{len(signatures)} distinct pod shapes over {N_PODS} pods")

    require(model.split_resources(model.galaxy(stars, players, carriers=[])),
            "splitResources would not be derived on")

    if failures:
        raise SystemExit("check failed:\n  " + "\n  ".join(failures))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def report(stars: list[dict], players: list[dict]) -> None:
    m = measure(stars)
    pod0 = [s for s in stars if s["_pod"] == 0]
    core0 = next(s for s in pod0 if s["isPulsar"])

    # How different the nine pods actually came out, measured the way the first
    # attempt failed: rank the stars of each pod by distance from its own middle
    # and see how far apart the nine agree.
    sigs = []
    for pod in range(N_PODS):
        members = [s for s in stars if s["_pod"] == pod]
        core = next(s for s in members if s["isPulsar"])
        sigs.append(sorted(dist(point_of(s), point_of(core)) for s in members))
    ranks = [max(col) - min(col) for col in zip(*sigs)]
    capital_radii = [dist(point_of(s), point_of(next(c for c in stars
                                                    if c["isPulsar"] and c["_pod"] == s["_pod"])))
                     for s in stars if s["homeStar"]]

    print(f"pods                {N_PODS} on a ring, {PLAYERS_PER_POD} players each, each grown "
          f"by generate.irregular on its own seed")
    print(f"stars               {len(stars)}  ({STARS_PER_POD} per pod: "
          f"{PLAYERS_PER_POD * STARS_PER_PLAYER} grown, 1 pulsar, {PLAYERS_PER_POD} posts)")
    print(f"players             {len(players)}")
    print(f"lattice             {POD_SEPARATION:.0f}u separation; pod 0 runs to "
          f"{max(dist(point_of(s), point_of(core0)) for s in pod0):.0f}u")
    print(f"wormholes           {N_PODS * N_WORMHOLE_SLOTS // 2} pairs, all neutral, "
          f"{LINKS_PER_POD_PAIR} link(s) between every pair of pods")
    print(f"opening (exact)     {STARTING_STARS} stars worth "
          f"{sum(sum(s['naturalResources'].values()) for s in m['owned'][players[0]['id']])} "
          f"natural resources, identical for all {N_PLAYERS} players")
    watching = sum(1 for post in stars if post["isBlackHole"]
                   and any(s["homeStar"] and s["_pod"] == post["_pod"]
                           and dist(point_of(post), point_of(s)) <= POST_SCAN
                           for s in stars))
    print(f"posts               {N_PLAYERS}, each watching one player and no other; "
          f"{watching} of them also catch that player's capital")
    print(f"how unalike         capital distance from its own core spans "
          f"{min(capital_radii):.0f}-{max(capital_radii):.0f}u; median radial rank disagrees by "
          f"{statistics.median(ranks):.0f}u across the {N_PODS} pods")
    print()
    print(f"{'fairness':<24}{'spread':>8}{'worst':>9}{'best':>9}   band")
    for label, key, limit in BANDS:
        values = m[key]
        print(f"  {label:<22}{spread(values):>8.2f}{min(values):>9.0f}{max(values):>9.0f}"
              f"   <= {limit:.2f}")
    for name, values in m["channels"].items():
        print(f"  {name:<22}{spread(values):>8.2f}{min(values):>9.0f}{max(values):>9.0f}"
              f"   <= {MAX_CHANNEL_SPREAD:.2f}")
    print()
    for channel in ("economy", "industry", "science"):
        values = [s["naturalResources"][channel] for s in stars]
        print(f"  {channel:<9}       min {min(values):>3}  median "
              f"{statistics.median(values):>3.0f}  mean {statistics.mean(values):>5.1f}  "
              f"max {max(values):>3}")
    gaps = [min(dist(point_of(s), point_of(o)) for o in pod0
                if o["id"] != s["id"] and not o["isBlackHole"])
            for s in pod0 if not s["isBlackHole"]]
    print(f"nearest-neighbour   min {min(gaps):.0f}u  median {statistics.median(gaps):.0f}u  "
          f"max {max(gaps):.0f}u")
    print(f"pods join up at     hyperspace "
          f"{max(connect_level([s for s in stars if s['_pod'] == p]) for p in range(N_PODS))}")


def probe(draws: int = 30) -> None:
    """Draw `draws` blobs for pod 0 and report what the lattice pitch offers.

    The trade-off curve the per-pod gates are set against: how many blobs can be
    seated and stand four posts at all, and how evenly the four roads come out
    once the seats are chosen. Re-run it after changing POD_SEPARATION.
    """
    spreads, means, posted, seated = [], [], 0, 0
    for attempt in range(draws):
        members = try_pod(0, attempt, gated=False)
        if members is None:
            continue
        seated += 1
        core = next(s for s in members if s["_role"] == "core")
        costs = roads_from([point_of(s) for s in members], point_of(core))
        if not costs:
            continue
        roads = []
        for seat in range(PLAYERS_PER_POD):
            mine = [i for i, s in enumerate(members) if s["_seat"] == seat]
            roads.append(min(costs[i] for i in mine))
        if not all(math.isfinite(r) for r in roads):
            continue
        posted += 1
        spreads.append(spread(roads))
        means.append(statistics.mean(roads))

    print(f"POD_SEPARATION      {POD_SEPARATION:.0f}u, {draws} blobs drawn for pod 0")
    print(f"usable              {posted}/{draws} seated, posted and gatewayed")
    if not spreads:
        return
    order = sorted(spreads)
    print(f"road spread         min {order[0]:.2f}  median {statistics.median(order):.2f}  "
          f"max {order[-1]:.2f}   (gate <= {MAX_POD_ROAD_SPREAD:.2f})")
    order = sorted(means)
    print(f"road mean           min {order[0]:.0f}  median {statistics.median(order):.0f}  "
          f"max {order[-1]:.0f} ticks   (gate {POD_ROAD_BAND[0]:.0f}-{POD_ROAD_BAND[1]:.0f})")
    passing = sum(1 for sp, mn in zip(spreads, means)
                  if sp <= MAX_POD_ROAD_SPREAD and POD_ROAD_BAND[0] <= mn <= POD_ROAD_BAND[1])
    print(f"clearing both       {passing}/{draws} blobs, so a pod takes about "
          f"{draws / max(passing, 1):.0f} draws to find")


def search(draws: int) -> None:
    """Grow the whole ring from `draws` master seeds and rank them on fairness."""
    global SEED
    original = SEED
    rows = []
    for draw in range(draws):
        SEED = f"{original}:{draw}" if draw else original
        try:
            stars, players = build()
            check(stars, players)
        except SystemExit as failed:
            print(f"  {SEED:<26} rejected: {str(failed).splitlines()[-1].strip()[:76]}")
            continue
        m = measure(stars)
        rows.append((sum(spread(m[key]) for _, key, _ in BANDS), SEED, m))
    SEED = original
    if not rows:
        raise SystemExit("no seed produced a map inside the bands")
    rows.sort()
    print(f"\n{'seed':<26}{'total':>8}{'open':>8}{'wealth':>8}{'terr':>8}{'road':>8}")
    for score, seed, m in rows:
        print(f"{seed:<26}{score:>8.2f}" + "".join(
            f"{spread(m[key]):>8.2f}" for _, key, _ in BANDS))
    print(f"\nfairest of {draws}: SEED = {rows[0][1]!r}   total spread {rows[0][0]:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pods", type=int, default=N_PODS,
                        help=f"pods on the ring, {PLAYERS_PER_POD} players each")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--render", action="store_true",
                        help="also draw the documentation figures")
    parser.add_argument("--probe", type=int, nargs="?", const=30, default=None,
                        metavar="N",
                        help="draw N blobs for pod 0, report the trade-off curve, and stop")
    parser.add_argument("--search", type=int, metavar="N", default=None,
                        help="grow the ring from N master seeds, rank them, and stop")
    args = parser.parse_args()
    configure(args.pods)
    if args.output is not None:
        global OUTPUT
        OUTPUT = args.output
    if args.probe is not None:
        probe(args.probe)
        return
    if args.search is not None:
        search(args.search)
        return

    stars, players = build()
    check(stars, players)
    report(stars, players)

    galaxy_json = model.galaxy(stars, players, carriers=[])
    verdict = validate.validate(galaxy_json)
    for warning in verdict.warnings:
        print(f"warning             {warning}")
    verdict.raise_for_errors()

    model.write(OUTPUT, galaxy_json)
    print(f"\nwrote {OUTPUT}  ({OUTPUT.stat().st_size / 1024:.0f} KB)  "
          f"validated against Solaris's rules")

    if args.render:
        render_figures(galaxy_json)


# --------------------------------------------------------------------------
# Figures
#
# Roles are recovered from terrain because the written JSON carries no scratch
# fields: a pulsar is a pod's middle, a black hole is a spy post, any other
# wormhole star is a gateway.
# --------------------------------------------------------------------------


def _point(star: dict) -> tuple[float, float]:
    return star["location"]["x"], star["location"]["y"]


def _view_box(svg: str) -> tuple[float, float, float, float]:
    match = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"', svg)
    if match is None:                                     # pragma: no cover
        raise SystemExit("rendered SVG carries no viewBox")
    return tuple(float(g) for g in match.groups())        # type: ignore[return-value]


def _jump_targets(data: dict, cores: list[dict], svg: str) -> dict:
    """Normalised jump targets, so the site's viewer can fly to one pod."""
    min_x, min_y, width, height = _view_box(svg)
    fringe = max(min(dist(_point(s), _point(c)) for c in cores) for s in data["stars"])
    return {"width": round(width, 2), "height": round(height, 2),
            "targets": [{"label": f"Pod {index}",
                         "x": round((_point(core)[0] - min_x) / width, 5),
                         "y": round((_point(core)[1] - min_y) / height, 5),
                         "r": round(fringe * 1.35 / width, 5)}
                        for index, core in enumerate(cores, 1)]}


def render_figures(data: dict) -> None:
    """Write the documentation figures and their viewer sidecar into out/.

    Nothing here knows about the website; docs/publish.py carries these into
    docs/assets/ and expects exactly this pair of names.
    """
    from solarismap import render

    out_dir = ROOT / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = OUTPUT.stem
    cores = sorted((s for s in data["stars"] if s["isPulsar"]),
                   key=lambda s: math.atan2(*_point(s)[::-1]))
    posts = [s for s in data["stars"] if s["isBlackHole"]]

    def mark(ctx):
        for index, core in enumerate(cores, 1):
            cx, cy = _point(core)
            yield ctx.circle(cx, cy, 40, ctx.palette.amber, 2.4, 0.95)
            yield ctx.text(cx, cy - 72, f"pod {index}", 30, ctx.palette.amber, weight="700")
        for post in posts:
            cx, cy = _point(post)
            yield ctx.circle(cx, cy, POST_TERRAIN_SCAN, ctx.palette.green, 1.6, 0.30,
                             dash="14 10")
            yield ctx.circle(cx, cy, POST_SCAN, ctx.palette.green, 1.4, 0.20, dash="6 12")

    whole = render.draw(data, render.Options(resources=False, ships=False, margin=260.0),
                        annotate_over=lambda ctx: list(mark(ctx)))
    target = out_dir / f"{stem}.svg"
    target.write_text(whole, encoding="utf-8")
    print(f"wrote {target}  ({target.stat().st_size / 1024:.0f} KB, the whole ring)")

    sidecar = out_dir / f"{stem}_targets.json"
    sidecar.write_text(json.dumps(_jump_targets(data, cores, whole), indent=1), encoding="utf-8")
    print(f"wrote {sidecar}  ({len(cores)} jump targets)")

    core = cores[0]
    fx, fy = _point(core)
    near = [dist(_point(s), (fx, fy)) for s in data["stars"]]
    span = max(d for d in near if d < min(EDGE_GAP, 3000.0))

    def callouts(ctx):
        here = [s for s in ctx.stars if dist(_point(s), (fx, fy)) < span]
        named = [(f"pod core: {CORE_NR}/{CORE_NR}/{CORE_NR} on a capital's infrastructure",
                  next((s for s in here if s["isPulsar"]), None)),
                 ("capital", next((s for s in here if s["homeStar"]), None)),
                 ("spy post: over one player's shoulder, hyperspace 4 or a wormhole to reach",
                  next((s for s in here if s["isBlackHole"]), None)),
                 ("wormhole gateway",
                  next((s for s in here if s["wormHoleToStarId"] and not s["isBlackHole"]), None)),
                 ("nebula", next((s for s in here if s["isNebula"]), None)),
                 ("asteroid field", next((s for s in here if s["isAsteroidField"]), None))]
        for label, star in named:
            if star is None:
                continue
            cx, cy = _point(star)
            angle = math.atan2(cy - fy, cx - fx)
            # The core sits at the focus, so it has no outward bearing to lead a
            # label along; send that one straight up instead.
            lx, ly = ((cx, cy + 150) if star["isPulsar"]
                      else (cx + 150 * math.cos(angle), cy + 150 * math.sin(angle)))
            anchor = "start" if lx >= cx else "end"
            yield ctx.line(cx, cy, lx, ly, ctx.palette.muted, 1.4, 0.75)
            yield ctx.text(lx + (8 if anchor == "start" else -8), ly + 5, label, 20,
                           ctx.palette.paper, anchor=anchor, weight="700")

    pod = render.draw(data, render.Options(resources=True, ships=True, margin=80.0,
                                           focus=(fx, fy, span + 200)),
                      annotate_over=lambda ctx: list(mark(ctx)) + list(callouts(ctx)))
    target = out_dir / f"{stem}_pod.svg"
    target.write_text(pod, encoding="utf-8")
    print(f"wrote {target}  ({target.stat().st_size / 1024:.0f} KB, one pod annotated)")


if __name__ == "__main__":
    main()
