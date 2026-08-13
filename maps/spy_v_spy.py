#!/usr/bin/env python3
"""Build a symmetric multi-galaxy custom map for Solaris.

Emits spy_v_spy.json in the editor's native 'editor_this' structure, which is
field-for-field Solaris's CustomGalaxy input format.

Layout: N galaxies on a ring, 4 player wedges each, so 4N players; 9 galaxies
and 36 players by default, --galaxies picks another size. Every galaxy carries
8 wormhole stars however many galaxies there are, dealt round-robin over the
others: at nine that is one link to each of the other eight, and every galaxy
pair is linked exactly once (C(9,2) = 36 wormholes); at two it is all eight
links running between the same two galaxies. Both ends of every wormhole start
neutral - each player begins with their 6 pod stars and nothing else.

Everything contested sits on a midline: the bearing exactly halfway between two
neighbouring wedges, across which the two players' starting pods are mirror
images, so nothing on it is nearer to one of them than the other. Each of the
four midlines in a galaxy carries, going outward: a wormhole gateway on the
capital ring, one hyperspace-3 hop from either neighbour and out of reach of
both at hyperspace 2; the 75-resource binary star; and a black hole post one
hyperspace-4 hop beyond that. The post's +3 scanning sees exactly that binary -
contested neutral ground - and nothing else, and it is unreachable at hyperspace
3, so the only way in is its wormhole.

Run:  python maps/spy_v_spy.py                 # 9 galaxies, 36 players
      python maps/spy_v_spy.py --galaxies 2    # 2 galaxies, 8 players
      python maps/spy_v_spy.py --render        # and the documentation figures
"""

import argparse
import heapq
import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solarismap import geometry, model, rules, specialists, validate   # noqa: E402

# --------------------------------------------------------------------------
# Game rules
#
# The scale, the ranges and the limits all come from solarismap.rules, which
# mirrors the editor and Solaris function for function. Nothing about the game
# is restated here.
# --------------------------------------------------------------------------

LIGHT_YEAR = rules.LIGHT_YEAR
MIN_STAR_SEPARATION = rules.MIN_STAR_SEPARATION

hyperspace_range = rules.hyperspace_range
hyperspace_level = rules.hyperspace_level
scanning_range = rules.scanning_range

# The only specialist on the map, and it stacks with the terrain under it: a
# black hole is worth +3 scanning by itself, the Telescope Array another +3, so
# a post that somebody has taken scans at hyperspace-8 range. The array also
# costs its star -3 weapons in combat, which is what stops a post being a free
# fortress.
_TELESCOPE_ARRAY = specialists.by_name("Telescope Array")
SPECIALIST_TELESCOPE_ARRAY = _TELESCOPE_ARRAY["id"]
TELESCOPE_SCANNING_BONUS = specialists.scanning_bonus(SPECIALIST_TELESCOPE_ARRAY)
BLACK_HOLE_SCANNING_BONUS = rules.BLACK_HOLE_SCANNING_BONUS


# --------------------------------------------------------------------------
# CONFIG - every tunable lives here
# --------------------------------------------------------------------------

N_GALAXIES = 9                                          # --galaxies overrides this; configure()
PLAYERS_PER_GALAXY = 4                                  # resets everything derived from it
N_PLAYERS = N_GALAXIES * PLAYERS_PER_GALAXY             # 36

# 8 wormhole stars per galaxy, whatever the galaxy count: a black hole post on
# each of the four midlines and a gateway on each of the four wedge bisectors.
# It is only at nine galaxies that this also happens to be one slot per other
# galaxy, which is what makes that ring a complete graph; at fewer galaxies the
# same eight slots are dealt round-robin over the others instead, so a
# two-galaxy build runs all eight of its links between the same two galaxies.
# Slot k always meets slot 7 - k, and that pairing is only reciprocal when
# N_GALAXIES - 1 divides the slot count: 2, 3, 5 and 9 galaxies are legal.
N_WORMHOLE_SLOTS = 2 * PLAYERS_PER_GALAXY               # 8

START_HYPERSPACE = 2                                    # player starting hyperspace tech
START_SCANNING = 2                                      # player starting scanning tech

HOP = hyperspace_range(START_HYPERSPACE)                # 175.0 - normal travel at game start
REACH = hyperspace_range(3)                             # 225.0 - the galaxy-wide connectivity floor

# What a post can see once taken, and what it could see on the black hole alone.
# Filler is kept out of POST_CLEARANCE, so the terrain by itself shows only the
# contested arc; the array's extra 150u is what buys a view of the approaches.
POST_SCAN = scanning_range(START_SCANNING + BLACK_HOLE_SCANNING_BONUS
                           + TELESCOPE_SCANNING_BONUS)  # 450.0
POST_CLEARANCE = scanning_range(START_SCANNING + BLACK_HOLE_SCANNING_BONUS)     # 300.0

# Isolation of every black hole post from the rest of the map. Anything under
# 225u would be reachable at hyperspace 3 and anything over 275u would need 5,
# so this has to sit inside that band; it sits above the middle of it because
# the post also has to stand far enough off that its 450u scan stops short of
# either neighbour's starting stars, which it clears by ~19u.
POST_ISOLATION = 265.0

# The galactic core must be an equal-length prize for all 36 players: reachable
# from a starting star on hyperspace-1 hops in about CORE_TICK_TARGET ticks, and
# in exactly the same number of ticks for everyone.
# helper.getTicksBetweenObjects charges ceil(distance / speed) per hop, so every
# hop on the chain is placed mid-bucket - at least CORE_TICK_MARGIN away from a
# multiple of CARRIER_SPEED. Land one on a bucket boundary and the ~1e-6 float
# noise from rotating each galaxy onto the ring flips some wedges up a whole
# tick, which silently breaks the symmetry.
CARRIER_SPEED = 10.0                                    # settings.carriers.baseCarrierSpeed,
                                                        # editor storage.ts (Standard, 0.2 ly/tick)
CORE_HOP = hyperspace_range(1)                          # 125.0
CORE_TICK_TARGET = 30
CORE_TICK_TOLERANCE = 0.10
CORE_TICK_MARGIN = 3.0

# Wedge layout, in the wedge's local frame (+x points radially outward).
#
# Every wedge is a mirror image of itself about its own bisector, which is what
# makes the whole galaxy symmetric about its midlines as well as under a quarter
# turn. Break that - put one feature off-axis - and every contested star on a
# midline ends up nearer one player's expansion than the other's, however
# equidistant it is from their starting stars.
CAPITAL_R = 409.0                                       # capital distance from the galactic core
SATELLITE_R = 120.0                                     # satellite ring around the capital
SATELLITE_ANGLES = (36.0, -36.0, 108.0, -108.0, 180.0)  # mirror-symmetric; 0 is left clear for
                                                        # the nebula, further out on the same ray
STARTING_STARS = 1 + len(SATELLITE_ANGLES)              # capital + satellites, and nothing else:
                                                        # every other star on the map starts neutral
FEATURE_R = 215.0                                       # nebula out beyond the satellites,
FEATURE_ANGLES = (0.0, 180.0)                           # asteroid field in towards the core,
FEATURE_NAMES = ("nebula", "asteroid")                  # both on the bisector, so both mirrored

# The player's own wormhole sits on the same bisector, just beyond the nebula:
# the first radius out there that no capital can reach even at hyperspace 4, so
# it is unmistakably one player's gateway without being a free starting asset.
# The 0.1u is the same float-noise guard used everywhere else in this file.
GATEWAY_FROM_CAPITAL = hyperspace_range(4) + 0.1        # 275.1

# Everything contested lives on a midline - the bearing halfway between two
# neighbouring wedges. Reflecting a galaxy in a midline maps one wedge onto the
# next exactly, stars, terrain and resources alike, so nothing on a midline is
# nearer to one of its two players than the other.
#
# Going outward: an inner-ring star level with the pods' asteroid fields, the
# binary, a fringe arc of FRINGE_COUNT stars, then the black hole post. The arc
# and the binary all sit at exactly POST_ISOLATION from the post, so the post
# sees all of them and can reach none of them under hyperspace 4; consecutive
# stars along the arc are one hyperspace-1 hop apart, so the arc is a connected
# fringe rather than a row of derelicts.
FRINGE_COUNT = 4                                        # two mirror pairs flanking the binary
FRINGE_HOP = 0.9 * hyperspace_range(1)                  # 112.5u - one hyperspace-1 hop, 10% margin

# The inner ring is the pods' four asteroid fields plus one more per midline at
# the same radius: eight stars evenly spaced around the core instead of four,
# which is what closes the gaps in the middle of a galaxy.
INNER_RING_R = CAPITAL_R - FEATURE_R                    # 194.0

# One filler star per wedge, halfway from the core out to the inward feature.
# That splits the run to the core into three hops of 95, 97 and 97 units - all
# inside hyperspace 1, all mid-bucket, 30 ticks end to end:
#   inner satellite (289) -> asteroid (194) -> bridge (97) -> core (0)
CORE_BRIDGE_R = (CAPITAL_R - FEATURE_R) / 2.0           # 97.0

# Filler: stochastic, but evaluated in wedge-local coordinates and stamped into
# all four wedges and both sides of each bisector, so the pockets are identical
# under a quarter turn and under reflection in any midline.
FILLER_PAIRS_PER_WEDGE = 4                              # each is a star and its mirror image; the
                                                        # core bridge star sits on the axis and is
                                                        # its own mirror, so 9 filler per wedge.
                                                        # 5 pairs will not fit: with the posts' scan
                                                        # bubbles walled off, the wedge runs out of
                                                        # admissible room at the local spacing.
FILLER_SEED = 20260810
FILLER_ATTEMPTS = 20000                                 # dart throws per placement
FILLER_INNER_R = 90.0
# Local spacing for the filler field, well above the editor's hard 50u floor.
# It came down from 85/150 when the inner ring went in: the middle of a galaxy
# is fuller now, and each throw is checked against all eight of its images, so
# at the old spacing there was one pocket left in the whole wedge.
SEPARATION_DENSE = 75.0                                 # min separation where the field is dense
SEPARATION_SPARSE = 130.0                               # min separation where the field is sparse

EDGE_GAP = 20.0 * LIGHT_YEAR                            # 1000u between adjacent galaxies

# Resource curve: NR = NR_MIN + NR_SPAN * (1 - r/R)^exponent, with the exponent
# solved at build time so the mean star lands on NR_MEAN_TARGET. Mean, not
# median: it is the total wealth on the map that the target is really about, and
# the median is blind to how much sits in the rich core.
NR_MIN = 10                                             # at the fringe
NR_MAX = 100                                            # at the galactic core
NR_SPAN = NR_MAX - NR_MIN
NR_MEAN_TARGET = 25                                     # averaged over every star and all three
NR_MEAN_TOLERANCE = 0.1                                 # channels; rounding to whole numbers means
                                                        # the solver can only get within ~1/(3n)

BINARY_NR = 75                                          # the contested midline binaries
FEATURE_MULTIPLIER = 3                                  # nebula science / asteroid economy

CORE_NR = 125                                           # the galactic core overrides the curve
CAPITAL_NR = 50                                         # so does every player's capital

# Terrain follows wealth: every star richer than this in any one channel is a
# binary, and no star at or under it is. That covers the core (125), the midline
# binaries (75) and the bridge stars, and leaves the capitals (exactly 50) out.
# Nebulas and asteroid fields are exempt whatever their multiplied channel comes
# to - they already carry terrain of their own, and stacking a second kind on
# top would only muddy what the star is.
BINARY_NR_THRESHOLD = 50
CORE_INFRASTRUCTURE = {"economy": 10, "industry": 10, "science": 5}
CAPITAL_INFRASTRUCTURE = {"economy": 5, "industry": 5, "science": 1}
STARTING_SHIPS = 10

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

# The editor's palette is 16 groups of 4 near-identical shades
# (editor stores/colours.ts), so what separates two players visually is their
# group, not their shade. Listed here in hue order - each group's first three
# shades, which is all the assignment below needs - so that groups a quarter of
# the list apart are a quarter of the colour wheel apart.
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
# Wedge w of galaxy g takes group (g + 4w), so the four players sharing a galaxy
# are always four groups - a quarter turn of the hue wheel - apart, and no two
# pods in the same galaxy read as the same colour. Nine galaxies over sixteen
# groups means the group sets repeat every fourth galaxy; those take the next
# shade instead, which keeps all 36 colours distinct.
COLOUR_GROUP_STEP = len(COLOUR_GROUPS) // PLAYERS_PER_GALAXY
WEDGE_SHAPES = ["circle", "square", "hexagon", "diamond"]

ROOT = Path(__file__).resolve().parent.parent


def output_for(n_players: int) -> Path:
    """The full ring keeps the plain name; every other size is suffixed by player count."""
    return ROOT / "out" / ("spy_v_spy.json" if n_players == 36
                           else f"spy_v_spy_{n_players}p.json")


OUTPUT = output_for(N_PLAYERS)

# --------------------------------------------------------------------------
# Derived geometry
# --------------------------------------------------------------------------


polar = geometry.polar
rotate = geometry.rotate
dist = geometry.dist


def ticks_for(distance: float) -> int:
    """rules.ticks_by_distance - helper.getTicksBetweenObjects, editor helper.ts"""
    return rules.ticks_by_distance(distance, CARRIER_SPEED)


def ticks_to_core(pool: list[dict], start: list[dict], core: dict,
                  pos: dict[str, tuple[float, float]]) -> float:
    """Cheapest run from any star in `start` to `core` over hyperspace-1 hops."""
    best = {s["id"]: math.inf for s in pool}
    heap: list[tuple[int, str]] = []
    for s in start:
        best[s["id"]] = 0
        heapq.heappush(heap, (0, s["id"]))
    while heap:
        cost, sid = heapq.heappop(heap)
        if cost > best[sid]:
            continue
        for other in pool:
            gap = dist(pos[sid], pos[other["id"]])
            if gap > CORE_HOP:
                continue
            total = cost + ticks_for(gap)
            if total < best[other["id"]]:
                best[other["id"]] = total
                heapq.heappush(heap, (total, other["id"]))
    return best[core["id"]]


WEDGE_STEP = 360.0 / PLAYERS_PER_GALAXY                 # 90 degrees
MIDLINE_OFFSET = WEDGE_STEP / 2.0                       # 45 degrees off a wedge bisector
GALAXY_STEP = 360.0 / N_GALAXIES                        # 40 degrees
LINKS_PER_GALAXY_PAIR = N_WORMHOLE_SLOTS // (N_GALAXIES - 1)    # 1


def configure(n_galaxies: int) -> None:
    """Resize the ring. Everything else on the map is per-galaxy and unaffected."""
    global N_GALAXIES, N_PLAYERS, GALAXY_STEP, LINKS_PER_GALAXY_PAIR, OUTPUT
    legal = [n for n in range(2, N_WORMHOLE_SLOTS + 2) if not N_WORMHOLE_SLOTS % (n - 1)]
    if n_galaxies not in legal:
        raise SystemExit(f"--galaxies {n_galaxies}: a galaxy's {N_WORMHOLE_SLOTS} wormhole "
                         f"slots have to divide evenly over the other galaxies, or the links "
                         f"between them come out lopsided and non-reciprocal. Legal: {legal}")
    N_GALAXIES = n_galaxies
    N_PLAYERS = N_GALAXIES * PLAYERS_PER_GALAXY
    GALAXY_STEP = 360.0 / N_GALAXIES
    LINKS_PER_GALAXY_PAIR = N_WORMHOLE_SLOTS // (N_GALAXIES - 1)
    OUTPUT = output_for(N_PLAYERS)

# Every player's own wormhole, on their bisector just past their nebula.
GATEWAY_R = CAPITAL_R + GATEWAY_FROM_CAPITAL            # 684.1

# The contested midline, going outward.
#
#   binary  on the same ring as the outermost starting stars, so the prize sits
#           exactly as deep into the map as either player's own frontier.
#   fringe  FRINGE_COUNT neutral stars, in mirror pairs, on the arc of radius
#           POST_ISOLATION about the post. FRINGE_STEP is the angle whose chord
#           on that arc is FRINGE_HOP, so the binary and the arc form a chain of
#           equal hyperspace-1 links either side of the midline.
#   post    POST_ISOLATION beyond the binary, so the binary and the whole arc lie
#           on its scan bubble's inner edge: five neutral stars in view, none of
#           them reachable from it under hyperspace 4. Filler is kept out of the
#           bubble, so that arc is the whole of what a post can ever see.
_OUTER_SATELLITE = polar(SATELLITE_R, SATELLITE_ANGLES[0])
BINARY_R = math.hypot(CAPITAL_R + _OUTER_SATELLITE[0], _OUTER_SATELLITE[1])      # 511.0
POST_R = BINARY_R + POST_ISOLATION                      # 761.0
FRINGE_STEP = math.degrees(2.0 * math.asin(FRINGE_HOP / (2.0 * POST_ISOLATION)))  # 26.0 degrees

# The posts are the outermost stars in a galaxy, so the resource curve bottoms
# out at NR_MIN exactly where they sit.
FRINGE_R = POST_R


def midline_bearing(midline: int) -> float:
    """Bearing of the contested lane between wedge `midline` and the next one."""
    return WEDGE_STEP * midline + MIDLINE_OFFSET


def density(pos: tuple[float, float]) -> float:
    """Smooth 0..1 field over one wedge - the pockets in the star spread.

    Deterministic and evaluated in wedge-local coordinates, so every wedge in
    every galaxy gets exactly the same dense and sparse regions.
    """
    r = math.hypot(*pos)
    theta = math.atan2(pos[1], pos[0])
    v = (0.45 * math.sin(r / 165.0 + 0.7)
         + 0.35 * math.cos(theta * 2.6 + 1.3)
         + 0.20 * math.sin(r / 95.0 + theta * 1.9))
    return min(1.0, max(0.0, 0.5 + 0.5 * v))


def separation_at(pos: tuple[float, float]) -> float:
    """Local minimum spacing - small in dense pockets, large in sparse ones."""
    return SEPARATION_SPARSE - (SEPARATION_SPARSE - SEPARATION_DENSE) * density(pos)


# --------------------------------------------------------------------------
# Star construction
# --------------------------------------------------------------------------


def new_star(pos: tuple[float, float]) -> dict:
    """A neutral star, plus this map's own scratch fields.

    model.new_star supplies every field Solaris requires (and `_radius`, the
    quantised distance from the origin that keeps mirror images in the same
    resource class). The rest is bookkeeping for the layout, stripped on write.
    """
    return model.new_star(
        pos,
        _role=None,
        _wedge=None,        # None for anything on a midline
        _midline=None,      # None for anything inside a wedge
        _slot=None,
    )


def wedge_local(role: str) -> tuple[float, float]:
    """Position of a named wedge object in the wedge's own frame."""
    if role == "capital":
        return (CAPITAL_R, 0.0)
    for angle in SATELLITE_ANGLES:
        if role == f"satellite{angle:+.0f}":
            offset = polar(SATELLITE_R, angle)
            return (CAPITAL_R + offset[0], offset[1])
    for angle, name in zip(FEATURE_ANGLES, FEATURE_NAMES):
        if role == name:
            offset = polar(FEATURE_R, angle)
            return (CAPITAL_R + offset[0], offset[1])
    raise KeyError(role)


def build_wedge(wedge: int) -> list[dict]:
    """Capital + 5 satellites + 2 feature stars, rotated onto wedge's bisector."""
    bisector = WEDGE_STEP * wedge
    stars = []

    def place(local: tuple[float, float], role: str) -> dict:
        star = new_star(rotate(local, bisector))
        star["_role"] = role
        star["_wedge"] = wedge
        stars.append(star)
        return star

    capital = place(wedge_local("capital"), "capital")
    capital["homeStar"] = True
    capital["infrastructure"] = dict(CAPITAL_INFRASTRUCTURE)

    for angle in SATELLITE_ANGLES:
        place(wedge_local(f"satellite{angle:+.0f}"), "satellite")

    for role in FEATURE_NAMES:
        star = place(wedge_local(role), role)
        star["isNebula"] = role == "nebula"
        star["isAsteroidField"] = role == "asteroid"

    return stars


def build_midlines() -> list[dict]:
    """The contested ground on each of a galaxy's four midlines.

    4 midlines to a galaxy, 90 degrees apart, each a mirror axis of the galaxy -
    so every star here is the same distance from either neighbouring player's
    whole pod, and neither of them has a shorter route to it than the other.
    Going outward: the inner-ring star, the 75-resource binary, the fringe arc.
    """
    stars = []
    for midline in range(PLAYERS_PER_GALAXY):
        bearing = midline_bearing(midline)

        def place(local: tuple[float, float], role: str) -> None:
            star = new_star(rotate(local, bearing))
            star["_role"] = role
            star["_midline"] = midline
            stars.append(star)

        place((INNER_RING_R, 0.0), "inner")
        place((BINARY_R, 0.0), "binary")
        # The arc, hung off the post's inner scan edge: step out along it in
        # FRINGE_HOP chords, alternating sides, so the binary stays its centre.
        for step in range(1, FRINGE_COUNT // 2 + 1):
            for side in (1.0, -1.0):
                offset = polar(POST_ISOLATION, 180.0 + side * step * FRINGE_STEP)
                place((POST_R + offset[0], offset[1]), "fringe")
    return stars


def build_wormholes() -> list[dict]:
    """8 wormhole stars: 4 black hole posts and 4 player gateways.

    Slot k of galaxy g pairs with galaxy g + 1 + (k mod N_GALAXIES - 1), which
    at nine galaxies is one slot to each of the other eight and at two is every
    slot to the one other galaxy. Even slots are the post, out on midline k // 2
    past the fringe arc; odd slots are wedge (k // 2)'s own gateway, on its
    bisector past its nebula. Slot k always meets slot 7 - k, which is of the
    opposite parity, so every wormhole runs gateway to post: one end a star that
    is plainly some player's, the other unclaimed deep space.
    """
    stars = []
    for slot in range(N_WORMHOLE_SLOTS):
        index = slot // 2
        if slot % 2 == 0:
            star = new_star(polar(POST_R, midline_bearing(index)))
            star["_role"] = "post"
            star["isBlackHole"] = True                  # +3 scanning from the terrain,
            star["specialistId"] = SPECIALIST_TELESCOPE_ARRAY   # +3 more from the array
            star["_midline"] = index
        else:
            star = new_star(polar(GATEWAY_R, WEDGE_STEP * index))
            star["_role"] = "gateway"
            star["_wedge"] = index
        star["_slot"] = slot
        stars.append(star)
    return stars


def images_of(local: tuple[float, float]) -> list[tuple[float, float]]:
    """A wedge-local point and every image of it under the galaxy's symmetry.

    Four quarter turns times the reflection in the wedge's own bisector - the
    dihedral group the whole galaxy is built to, which is what makes each
    midline a mirror axis and so keeps contested ground exactly even between the
    two players it separates. A point on the bisector is its own mirror image.
    """
    mirrored = [local] if abs(local[1]) < 1e-9 else [local, (local[0], -local[1])]
    return [rotate(p, WEDGE_STEP * w)
            for w in range(PLAYERS_PER_GALAXY) for p in mirrored]


def build_filler(seeded: list[dict], wormholes: list[dict]) -> list[dict]:
    """Neutral background stars: stochastic, pocketed, and fully symmetric.

    Dart-thrown against a smooth density field so the galaxy grows dense
    clusters and sparse voids, but every throw is evaluated in wedge-local
    coordinates and stamped onto all of its images at once, so the galaxy stays
    exactly symmetric under a quarter turn and under reflection in any bisector
    or midline. Each star must land within one hyperspace-3 hop of something
    already placed, which keeps the galaxy in a single connected component no
    matter how the field falls.
    """
    rng = random.Random(FILLER_SEED)
    posts = [(s["location"]["x"], s["location"]["y"]) for s in wormholes if s["_role"] == "post"]

    occupied = [(s["location"]["x"], s["location"]["y"]) for s in seeded]
    occupied += [(s["location"]["x"], s["location"]["y"]) for s in wormholes]
    # The posts are deliberately unreachable at hyperspace 3, so they are not
    # valid anchors for the connectivity requirement.
    anchors = [(s["location"]["x"], s["location"]["y"]) for s in seeded]
    anchors += [(s["location"]["x"], s["location"]["y"]) for s in wormholes
                if s["_role"] == "gateway"]

    filler = []

    def commit(local: tuple[float, float], role: str) -> None:
        per_wedge = 1 if abs(local[1]) < 1e-9 else 2    # a star on the bisector, or a pair
        for index, pos in enumerate(images_of(local)):
            star = new_star(pos)
            star["_role"] = role
            star["_wedge"] = index // per_wedge
            filler.append(star)
            occupied.append(pos)
            anchors.append(pos)

    # Bridge star: the galactic core is CAPITAL_R - FEATURE_R from the nearest
    # wedge star, too far to reach, so one filler per wedge splits the gap.
    commit((CORE_BRIDGE_R, 0.0), "bridge")

    def admissible(p: tuple[float, float]) -> bool:
        # Filler stays out of what a post could see on its black hole alone, so
        # the terrain by itself shows nothing but the midline binary and fringe
        # arc it was placed against. What the Telescope Array adds on top of
        # that is a view of the neutral ground on the approaches.
        if any(dist(p, s) <= POST_CLEARANCE for s in posts):
            return False
        images = images_of(p)
        needed = separation_at(p)
        for img in images:
            if any(dist(img, o) < needed for o in occupied):
                return False
        for i in range(len(images)):
            for j in range(i + 1, len(images)):
                if dist(images[i], images[j]) < needed:
                    return False
        return min(dist(p, a) for a in anchors) <= REACH

    for _ in range(FILLER_PAIRS_PER_WEDGE):
        fallback = None
        for attempt in range(FILLER_ATTEMPTS):
            u = rng.random()
            r = math.sqrt(u * (FRINGE_R ** 2 - FILLER_INNER_R ** 2) + FILLER_INNER_R ** 2)
            # Half a wedge only: the other half is this throw's mirror image, so
            # sampling both would just be drawing the same pair twice.
            theta = rng.uniform(0.0, WEDGE_STEP / 2.0)
            candidate = polar(r, theta)
            if not admissible(candidate):
                continue
            if fallback is None:
                fallback = candidate
            # Accept in proportion to the density field: sparse pockets keep
            # rejecting, so stars pile into the dense ones.
            if rng.random() < density(candidate):
                fallback = candidate
                break
        if fallback is None:
            raise RuntimeError("ran out of admissible filler positions")
        commit(fallback, "filler")

    return filler


def build_galaxy() -> list[dict]:
    """One galaxy in its own frame, centred on the core star at the origin."""
    core = new_star((0.0, 0.0))
    core["_role"] = "core"
    core["isPulsar"] = True                             # every galaxy's landmark
    core["infrastructure"] = dict(CORE_INFRASTRUCTURE)

    wedges = [s for w in range(PLAYERS_PER_GALAXY) for s in build_wedge(w)]
    midlines = build_midlines()
    wormholes = build_wormholes()
    filler = build_filler([core] + wedges + midlines, wormholes)
    return [core] + wedges + midlines + wormholes + filler


# --------------------------------------------------------------------------
# Resource curve
# --------------------------------------------------------------------------


def curve(radius: float, exponent: float) -> int:
    """NR_MIN at the fringe rising to NR_MAX at the galactic core."""
    t = 1.0 - min(radius, FRINGE_R) / FRINGE_R
    return int(NR_MIN + NR_SPAN * (t ** exponent) + 0.5)


def resources_for(star: dict, exponent: float) -> tuple[int, int, int]:
    role = star["_role"]
    if role == "core":
        return (CORE_NR, CORE_NR, CORE_NR)
    if role == "capital":
        return (CAPITAL_NR, CAPITAL_NR, CAPITAL_NR)
    if role == "binary":
        return (BINARY_NR,) * 3
    # "3x" is applied to the curve's value at the capital's radius so every one
    # of the 36 players gets identical features regardless of where each one
    # lands on the gradient. Swap to curve(star["_radius"], ...) for 3x the
    # feature's own positional value instead.
    base = curve(CAPITAL_R, exponent)
    if role == "nebula":
        return (base, base, base * FEATURE_MULTIPLIER)
    if role == "asteroid":
        return (base * FEATURE_MULTIPLIER, base, base)
    value = curve(star["_radius"], exponent)
    return (value, value, value)


def mean_resources(stars: list[dict], exponent: float) -> float:
    """Mean natural resources over every star and all three channels."""
    values = [v for s in stars for v in resources_for(s, exponent)]
    return statistics.mean(values)


def solve_exponent(stars: list[dict]) -> float:
    """Find the curve exponent whose mean star is NR_MEAN_TARGET.

    The mean falls monotonically as the exponent rises - a steeper curve drops
    every off-core star towards NR_MIN - so bisection converges on it. It lands
    near rather than on the target: rounding each star to a whole number moves
    the mean in steps of 1/(3n), so the two ends of the final interval bracket
    the target and the closer one wins.
    """
    lo, hi = 0.1, 12.0
    if mean_resources(stars, lo) < NR_MEAN_TARGET or mean_resources(stars, hi) > NR_MEAN_TARGET:
        raise RuntimeError(f"mean {NR_MEAN_TARGET} unreachable "
                           f"({mean_resources(stars, hi):.2f} .. "
                           f"{mean_resources(stars, lo):.2f})")
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if mean_resources(stars, mid) > NR_MEAN_TARGET:
            lo = mid
        else:
            hi = mid
    return min((lo, hi), key=lambda e: abs(mean_resources(stars, e) - NR_MEAN_TARGET))


def solve_ring_radius(galaxy: list[dict]) -> float:
    """Ring radius that puts EDGE_GAP between the nearest stars of neighbours."""
    local = [(s["location"]["x"], s["location"]["y"]) for s in galaxy]

    def min_gap(ring_r: float) -> float:
        best = float("inf")
        first = None
        for g in (0, 1):
            phi = GALAXY_STEP * g
            centre = polar(ring_r, phi)
            placed = [(rotate(p, phi)[0] + centre[0], rotate(p, phi)[1] + centre[1]) for p in local]
            if g == 0:
                first = placed
            else:
                for a in first:
                    for b in placed:
                        best = min(best, dist(a, b))
        return best

    lo, hi = FRINGE_R, 30000.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if min_gap(mid) < EDGE_GAP:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def player_colour(galaxy: int, wedge: int) -> dict:
    """One distinct colour per player, four contrasting ones per galaxy."""
    group = COLOUR_GROUPS[(galaxy + COLOUR_GROUP_STEP * wedge) % len(COLOUR_GROUPS)]
    alias, value = group[galaxy // PLAYERS_PER_GALAXY]
    return {"alias": alias, "value": value}


def build() -> tuple[list[dict], list[dict], float]:
    template = build_galaxy()
    exponent = solve_exponent(template)
    ring_r = solve_ring_radius(template)

    stars: list[dict] = []
    galaxies: list[list[dict]] = []
    for g in range(N_GALAXIES):
        phi = GALAXY_STEP * g
        centre = polar(ring_r, phi)
        galaxy = []
        for proto in build_galaxy():
            star = dict(proto)
            star["infrastructure"] = dict(proto["infrastructure"])
            nr = resources_for(proto, exponent)
            star["naturalResources"] = {"economy": nr[0], "industry": nr[1], "science": nr[2]}
            # Terrain from wealth, applied in one place for every star: the core,
            # the midline binaries and the bridge stars all clear the threshold,
            # nothing else does. A star that already has terrain of its own keeps
            # it and stays off the binary list however rich its best channel is.
            star["isBinaryStar"] = (max(nr) > BINARY_NR_THRESHOLD
                                    and not star["isNebula"]
                                    and not star["isAsteroidField"])
            x, y = rotate((proto["location"]["x"], proto["location"]["y"]), phi)
            star["location"] = {"x": round(x + centre[0], 6), "y": round(y + centre[1], 6)}
            star["_galaxy"] = g
            galaxy.append(star)
        galaxies.append(galaxy)
        stars.extend(galaxy)

    for index, star in enumerate(stars, start=1):
        star["id"] = str(index)

    # ---- players -------------------------------------------------------
    players = []
    for g in range(N_GALAXIES):
        for w in range(PLAYERS_PER_GALAXY):
            capital = next(s for s in galaxies[g] if s["_role"] == "capital" and s["_wedge"] == w)
            player_id = str(g * PLAYERS_PER_GALAXY + w + 1)
            capital["playerId"] = player_id
            players.append(model.new_player(
                player_id,
                capital["id"],
                technologies=STARTING_TECHNOLOGIES,
                credits=STARTING_CREDITS,
                credits_specialists=STARTING_CREDITS_SPECIALISTS,
                colour=player_colour(g, w),
                shape=WEDGE_SHAPES[w],
            ))
            for star in galaxies[g]:
                if star["_wedge"] == w and star["_role"] in ("capital", "satellite"):
                    star["playerId"] = player_id
                    star["shipsActual"] = STARTING_SHIPS
                    star["ships"] = STARTING_SHIPS

    # ---- wormholes -----------------------------------------------------
    # Slot k in galaxy g pairs with the k-th galaxy along, counting round the
    # ring and wrapping over the other galaxies as often as it takes to place
    # all eight slots. Even k is the black hole post, odd k the gateway, and
    # slot k always meets slot 7-k, so every link runs from a gateway in one
    # galaxy to a post in another. Both ends start neutral.
    for g in range(N_GALAXIES):
        for slot in range(N_WORMHOLE_SLOTS):
            here = next(s for s in galaxies[g] if s["_slot"] == slot)
            partner_galaxy = (g + 1 + slot % (N_GALAXIES - 1)) % N_GALAXIES
            partner_slot = N_WORMHOLE_SLOTS - 1 - slot
            there = next(s for s in galaxies[partner_galaxy] if s["_slot"] == partner_slot)
            here["wormHoleToStarId"] = there["id"]

    return stars, players, exponent


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------


def check(stars: list[dict], players: list[dict]) -> None:
    pos = {s["id"]: (s["location"]["x"], s["location"]["y"]) for s in stars}
    by_id = {s["id"]: s for s in stars}
    failures = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    galaxies: dict[int, list[dict]] = {}
    for s in stars:
        galaxies.setdefault(s["_galaxy"], []).append(s)

    # --- counts and identity ---
    per_wedge = (1 + len(SATELLITE_ANGLES) + len(FEATURE_ANGLES)      # pod and its plain stars
                 + 1 + 2 * FILLER_PAIRS_PER_WEDGE                     # bridge and filler
                 + 2 + FRINGE_COUNT)                                  # one midline, inner ring out
    per_galaxy = 1 + PLAYERS_PER_GALAXY * per_wedge + N_WORMHOLE_SLOTS
    require(len(stars) == N_GALAXIES * per_galaxy, f"unexpected star count {len(stars)}")
    require(len(players) == N_PLAYERS, f"expected {N_PLAYERS} players, got {len(players)}")
    require(len({s["id"] for s in stars}) == len(stars), "duplicate star ids")
    require(len({p["id"] for p in players}) == len(players), "duplicate player ids")

    capitals = [s for s in stars if s["homeStar"]]
    require(len(capitals) == N_PLAYERS, f"expected {N_PLAYERS} home stars, got {len(capitals)}")
    require(all(c["playerId"] is not None for c in capitals), "home star without a playerId")
    home_ids = [p["homeStarId"] for p in players]
    require(len(set(home_ids)) == len(home_ids), "two players share a capital")
    require(all(h in by_id for h in home_ids), "homeStarId does not resolve")
    require(all(by_id[p["homeStarId"]]["playerId"] == p["id"] for p in players),
            "capital not owned by the player that claims it")
    require(len({p["colour"]["value"] for p in players}) == N_PLAYERS,
            "two players share a colour")
    require(len({(p["colour"]["value"], p["shape"]) for p in players}) == N_PLAYERS,
            "duplicate colour/shape combo")
    galaxy_palette: dict[int, list[str]] = {}
    for p in players:
        galaxy_palette.setdefault(by_id[p["homeStarId"]]["_galaxy"], []) \
            .append(p["colour"]["value"])
    for g, palette in galaxy_palette.items():
        require(len(set(palette)) == PLAYERS_PER_GALAXY,
                f"galaxy {g} has two players in the same colour: {sorted(palette)}")

    # --- wormholes ---
    wormholes = [s for s in stars if s["wormHoleToStarId"] is not None]
    require(len(wormholes) == N_GALAXIES * N_WORMHOLE_SLOTS,
            f"expected {N_GALAXIES * N_WORMHOLE_SLOTS} wormhole stars, got {len(wormholes)}")
    for s in wormholes:
        require(s["wormHoleToStarId"] != s["id"], f"star {s['id']} wormholes to itself")
        require(s["wormHoleToStarId"] in by_id, f"star {s['id']} wormholes to a missing star")
        require(by_id[s["wormHoleToStarId"]]["wormHoleToStarId"] == s["id"],
                f"wormhole {s['id']} is not reciprocal")

    pairs = {frozenset((s["id"], s["wormHoleToStarId"])) for s in wormholes}
    require(len(pairs) == N_GALAXIES * N_WORMHOLE_SLOTS // 2,
            f"expected {N_GALAXIES * N_WORMHOLE_SLOTS // 2} wormhole pairs, got {len(pairs)}")
    galaxy_pairs: dict[frozenset, int] = {}
    for a, b in (tuple(p) for p in pairs):
        key = frozenset((by_id[a]["_galaxy"], by_id[b]["_galaxy"]))
        galaxy_pairs[key] = galaxy_pairs.get(key, 0) + 1
    require(all(len(gp) == 2 for gp in galaxy_pairs), "a galaxy wormholes to itself")
    # Every pair of galaxies linked, and all of them linked the same number of
    # times: with two galaxies that is eight links between the pair, with nine
    # it is one link each and the ring is a complete graph.
    require(len(galaxy_pairs) == N_GALAXIES * (N_GALAXIES - 1) // 2,
            f"expected every one of the {N_GALAXIES * (N_GALAXIES - 1) // 2} galaxy pairs to "
            f"be linked, got {len(galaxy_pairs)}")
    require(set(galaxy_pairs.values()) == {LINKS_PER_GALAXY_PAIR},
            f"galaxy pairs are linked unevenly: {sorted(set(galaxy_pairs.values()))}, "
            f"expected {LINKS_PER_GALAXY_PAIR} link(s) each")

    posts = [s for s in stars if s["_role"] == "post"]
    gateways = [s for s in stars if s["_role"] == "gateway"]
    require(len(posts) == N_PLAYERS, f"expected {N_PLAYERS} posts, got {len(posts)}")
    require(len(gateways) == N_PLAYERS, f"expected {N_PLAYERS} gateways, got {len(gateways)}")
    require(len(posts) + len(gateways) == len(wormholes), "a wormhole star is neither end type")
    for a, b in (tuple(p) for p in pairs):
        n_post = sum(1 for e in (a, b) if by_id[e]["_role"] == "post")
        require(n_post == 1, f"wormhole {a}<->{b} has {n_post} post ends, expected 1")
    require(all(s["playerId"] is None for s in posts + gateways),
            "a wormhole star starts owned")

    # --- everything contested sits exactly between two starting pods ---
    def pod_profile(star: dict, player_id: str) -> list[float]:
        """Sorted distances from `star` to every star `player_id` starts with."""
        return sorted(dist(pos[star["id"]], pos[o["id"]]) for o in stars
                      if o["playerId"] == player_id)

    def neighbours_of(star: dict) -> tuple[str, str]:
        """The two players of the star's galaxy whose capitals are nearest."""
        ranked = sorted((dist(pos[star["id"]], pos[c["id"]]), c["playerId"])
                        for c in capitals if c["_galaxy"] == star["_galaxy"])
        return ranked[0][1], ranked[1][1]

    def require_midline(star: dict, label: str) -> None:
        a, b = neighbours_of(star)
        first, second = pod_profile(star, a), pod_profile(star, b)
        require(len(first) == len(second)
                and all(abs(x - y) < 1e-3 for x, y in zip(first, second)),
                f"{label} {star['id']} is not equidistant from the pods of "
                f"players {a} and {b}")

    binaries = [s for s in stars if s["_role"] == "binary"]
    fringe = [s for s in stars if s["_role"] == "fringe"]
    inner = [s for s in stars if s["_role"] == "inner"]
    require(len(binaries) == N_PLAYERS,
            f"expected {N_PLAYERS} midline binaries, got {len(binaries)}")
    require(len(fringe) == N_PLAYERS * FRINGE_COUNT,
            f"expected {N_PLAYERS * FRINGE_COUNT} fringe stars, got {len(fringe)}")
    require(len(inner) == N_PLAYERS,
            f"expected {N_PLAYERS} inner-ring midline stars, got {len(inner)}")
    for s in binaries + fringe + posts + inner:
        require(s["playerId"] is None, f"{s['_role']} {s['id']} starts owned")
    for s in binaries + posts + inner:
        require_midline(s, s["_role"])

    # The fringe arc balances as a set rather than star by star: its members sit
    # off the axis in mirror pairs, so what has to match is the whole spread of
    # distances from one pod to the arc against the same from the other.
    for g, members in galaxies.items():
        for m in range(PLAYERS_PER_GALAXY):
            arc = [s for s in members if s["_role"] == "fringe" and s["_midline"] == m]
            binary = next(s for s in members if s["_role"] == "binary" and s["_midline"] == m)
            require(len(arc) == FRINGE_COUNT,
                    f"galaxy {g} midline {m} has {len(arc)} fringe stars")
            a, b = neighbours_of(binary)
            spread = [sorted(d for f in arc for d in pod_profile(f, pid)) for pid in (a, b)]
            require(all(abs(x - y) < 1e-3 for x, y in zip(*spread)),
                    f"galaxy {g} midline {m}: its fringe arc is not evenly placed "
                    f"between players {a} and {b}")

    # Rings: the binaries four to a galaxy on the outer starting ring, the inner
    # ring eight - four asteroid fields and four midline stars - evenly spaced,
    # which is what leaves the middle of a galaxy without a hole in it.
    for g, members in galaxies.items():
        core = next(s for s in members if s["_role"] == "core")

        def ring_of(roles: tuple[str, ...], radius: float, count: int, name: str) -> None:
            ring = [s for s in members if s["_role"] in roles]
            require(len(ring) == count,
                    f"galaxy {g} has {len(ring)} stars on the {name} ring, expected {count}")
            radii = [dist(pos[s["id"]], pos[core["id"]]) for s in ring]
            require(all(abs(r - radius) < 1e-3 for r in radii),
                    f"galaxy {g}: the {name} ring is not at {radius:.1f}u: "
                    f"{[f'{r:.1f}' for r in radii]}")
            bearings = sorted(math.degrees(math.atan2(pos[s["id"]][1] - pos[core["id"]][1],
                                                      pos[s["id"]][0] - pos[core["id"]][0])) % 360.0
                              for s in ring)
            gaps = [(b - a) % 360.0 for a, b in zip(bearings, bearings[1:] + bearings[:1])]
            require(all(abs(gap - 360.0 / count) < 1e-3 for gap in gaps),
                    f"galaxy {g}: the {name} ring is not evenly spaced: "
                    f"{[f'{x:.2f}' for x in gaps]}")

        ring_of(("binary",), BINARY_R, PLAYERS_PER_GALAXY, "binary")
        ring_of(("inner", "asteroid"), INNER_RING_R, 2 * PLAYERS_PER_GALAXY, "inner")

    # --- posts: isolated, and looking at nothing but contested ground ---
    reached = []
    for s in posts:
        ranked = sorted(((dist(pos[s["id"]], pos[o["id"]]), o) for o in stars if o["id"] != s["id"]),
                        key=lambda t: t[0])
        nearest = ranked[0][0]
        require(s["isBlackHole"], f"post {s['id']} is not a black hole")
        require(abs(nearest - POST_ISOLATION) < 1e-3,
                f"post {s['id']} nearest neighbour is {nearest:.3f}, expected {POST_ISOLATION}")
        require(hyperspace_level(nearest) == 4,
                f"post {s['id']} needs hyperspace {hyperspace_level(nearest)}, expected 4")
        # On the black hole alone: the midline's binary and fringe arc, nothing
        # else. The Telescope Array widens that to POST_SCAN, which reaches out
        # over the neutral approaches but still stops short of either
        # neighbour's starting stars.
        close = [o for d, o in ranked if d <= POST_CLEARANCE]
        require(len(close) == 1 + FRINGE_COUNT,
                f"post {s['id']} sees {len(close)} stars on its black hole alone, "
                f"expected the binary and {FRINGE_COUNT} fringe stars")
        for o in close:
            require(o["_role"] in ("binary", "fringe") and o["_midline"] == s["_midline"],
                    f"post {s['id']} sees a {o['_role']} star that is not its own "
                    f"contested ground")
            # Fringe worth having: each one is a hyperspace-1 hop from a
            # neighbour, so the arc is a place a fleet can work along.
            hop = min(dist(pos[o["id"]], pos[n["id"]]) for n in stars
                      if n["id"] != o["id"] and n["_role"] != "post")
            require(hop <= CORE_HOP,
                    f"star {o['id']} in a post's view is {hop:.1f}u from its nearest "
                    f"neighbour, more than one hyperspace-1 hop ({CORE_HOP}u)")

        visible = [o for d, o in ranked if d <= POST_SCAN]
        require(all(o["playerId"] is None for o in visible),
                f"post {s['id']} has an owned star inside its scan bubble")
        # Whatever else it can see, it sees the same on both sides: reflecting
        # the galaxy in this post's own midline maps its view onto itself, so
        # neither neighbour is watched more closely than the other.
        core = next(o for o in galaxies[s["_galaxy"]] if o["_role"] == "core")
        centre, axis_point = pos[core["id"]], pos[s["id"]]
        axis = math.degrees(math.atan2(axis_point[1] - centre[1], axis_point[0] - centre[0]))
        seen = {o["id"] for o in visible}
        for o in visible:
            local = rotate((pos[o["id"]][0] - centre[0], pos[o["id"]][1] - centre[1]), -axis)
            image = rotate((local[0], -local[1]), axis)
            twin = min(galaxies[s["_galaxy"]],
                       key=lambda t: dist((pos[t["id"]][0] - centre[0],
                                           pos[t["id"]][1] - centre[1]), image))
            require(twin["id"] in seen,
                    f"post {s['id']} sees star {o['id']} but not its mirror image "
                    f"across the midline")

    require(all(s["isBlackHole"] == (s["_role"] == "post") for s in stars),
            "a black hole sits somewhere other than a post")

    # --- gateways: one per player, plainly theirs, but not a starting asset ---
    for gw in gateways:
        post = by_id[gw["wormHoleToStarId"]]
        require(post["_role"] == "post", f"gateway {gw['id']} does not lead to a post")
        require(post["_galaxy"] != gw["_galaxy"],
                f"gateway {gw['id']} leads to a post in its own galaxy")

        owner = str(gw["_galaxy"] * PLAYERS_PER_GALAXY + gw["_wedge"] + 1)
        ranked = sorted((dist(pos[gw["id"]], pos[c["id"]]), c["playerId"]) for c in capitals)
        require(ranked[0][1] == owner,
                f"gateway {gw['id']} is nearer player {ranked[0][1]} than its own "
                f"player {owner}")
        require(ranked[0][0] < ranked[1][0] - MIN_STAR_SEPARATION,
                f"gateway {gw['id']} is not clearly closer to one capital than the next: "
                f"{ranked[0][0]:.1f}u vs {ranked[1][0]:.1f}u")
        # Past hyperspace 4 from every capital, so no player simply starts with
        # one - but a short hop on from their own nebula.
        require(hyperspace_level(ranked[0][0]) > 4,
                f"gateway {gw['id']} is {ranked[0][0]:.1f}u from its capital, inside "
                f"hyperspace {hyperspace_level(ranked[0][0])}")
        nebula = next(o for o in stars if o["_role"] == "nebula"
                      and o["_galaxy"] == gw["_galaxy"] and o["_wedge"] == gw["_wedge"])
        gap = dist(pos[gw["id"]], pos[nebula["id"]])
        require(hyperspace_level(gap) == 1,
                f"gateway {gw['id']} is {gap:.1f}u from its own pod's nebula, hyperspace "
                f"{hyperspace_level(gap)}")
        reached.append(post["id"])
    require(len(set(reached)) == N_PLAYERS, "two gateways lead to the same post")

    # --- resources, infrastructure, ships ---
    for s in stars:
        nr = s["naturalResources"]
        for key in ("economy", "industry", "science"):
            require(0 <= nr[key] <= 2000, f"star {s['id']} {key} resources out of range")
            require(0 <= s["infrastructure"][key] <= 200, f"star {s['id']} {key} infra out of range")
        require(sum(nr.values()) > 0, f"star {s['id']} is a dead star")
        require(0 <= s["shipsActual"] <= 200000, f"star {s['id']} ship count out of range")
        if s["playerId"] is None:
            require(s["shipsActual"] == 0 and s["ships"] == 0, f"unowned star {s['id']} has ships")
        feature = s["isNebula"] or s["isAsteroidField"]
        require(s["isBinaryStar"] == (max(nr.values()) > BINARY_NR_THRESHOLD and not feature),
                f"star {s['id']} is {'not ' if not s['isBinaryStar'] else ''}a binary at "
                f"{nr['economy']}/{nr['industry']}/{nr['science']}"
                f"{' (nebula or asteroid field)' if feature else ''}")
        # Terrain and specialists, each in exactly one place and nowhere else.
        require(s["specialistId"] == (SPECIALIST_TELESCOPE_ARRAY if s["_role"] == "post" else None),
                f"star {s['id']} ({s['_role']}) carries specialist {s['specialistId']}")
        require(s["isPulsar"] == (s["_role"] == "core"),
                f"star {s['id']} ({s['_role']}) has isPulsar {s['isPulsar']}")
        require(s["isNebula"] == (s["_role"] == "nebula"),
                f"star {s['id']} ({s['_role']}) has isNebula {s['isNebula']}")
        require(s["isAsteroidField"] == (s["_role"] == "asteroid"),
                f"star {s['id']} ({s['_role']}) has isAsteroidField {s['isAsteroidField']}")
        require(not s["warpGate"], f"star {s['id']} has a warp gate")

    require(all(s["naturalResources"] == {"economy": CORE_NR, "industry": CORE_NR,
                                          "science": CORE_NR}
                for s in stars if s["_role"] == "core"),
            f"a galactic core is not {CORE_NR}/{CORE_NR}/{CORE_NR}")
    require(all(s["naturalResources"] == {"economy": BINARY_NR, "industry": BINARY_NR,
                                          "science": BINARY_NR}
                for s in binaries),
            f"a midline binary is not {BINARY_NR}/{BINARY_NR}/{BINARY_NR}")

    pooled = statistics.mean(v for s in stars for v in s["naturalResources"].values())
    require(abs(pooled - NR_MEAN_TARGET) <= NR_MEAN_TOLERANCE,
            f"mean natural resources are {pooled:.3f}, expected {NR_MEAN_TARGET} "
            f"+/-{NR_MEAN_TOLERANCE}")
    require(all(s["naturalResources"] == {"economy": CAPITAL_NR, "industry": CAPITAL_NR,
                                          "science": CAPITAL_NR}
                for s in stars if s["_role"] == "capital"),
            f"a capital is not {CAPITAL_NR}/{CAPITAL_NR}/{CAPITAL_NR}")
    # The curve stars only: core, capital and the feature stars all override it.
    gradient = [s["naturalResources"]["economy"] for s in stars
                if s["_role"] not in ("core", "capital", "binary", "nebula", "asteroid")]
    require(min(gradient) == NR_MIN, f"fringe resources are {min(gradient)}, expected {NR_MIN}")
    require(max(gradient) <= NR_MAX, f"gradient peaks at {max(gradient)}, expected <= {NR_MAX}")

    # 6 each: the capital and its 5 satellites. Everything else - features,
    # midline binaries, wormhole stars, filler - starts neutral.
    owned = [s for s in stars if s["playerId"] is not None]
    require(len(owned) == N_PLAYERS * STARTING_STARS,
            f"expected {N_PLAYERS * STARTING_STARS} owned stars, got {len(owned)}")
    require(all(s["_role"] in ("capital", "satellite") for s in owned),
            "a star outside the starting pods begins owned")
    require(all(s["wormHoleToStarId"] is None for s in owned),
            "a wormhole star begins owned")

    # --- separation, symmetry, connectivity ---
    min_sep = float("inf")
    for members in galaxies.values():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                min_sep = min(min_sep, dist(pos[a["id"]], pos[b["id"]]))
    require(min_sep >= MIN_STAR_SEPARATION - 1e-6,
            f"minimum star separation {min_sep:.2f} is under {MIN_STAR_SEPARATION}")

    inter = min(dist(pos[a["id"]], pos[b["id"]]) for a in galaxies[0] for b in galaxies[1])
    require(abs(inter - EDGE_GAP) < 1e-2,
            f"adjacent galaxy gap {inter:.2f}, expected {EDGE_GAP}")

    # Congruence, compared with a tolerance: rotating a galaxy onto the ring and
    # rounding its coordinates to 6dp perturbs radii by ~1e-6.
    reference = None
    for g, members in galaxies.items():
        core = next(s for s in members if s["_role"] == "core")
        centre = pos[core["id"]]
        # Sorted on the exact integer resources first so float noise in the
        # radius can never reorder two stars that share a radius (the nebula and
        # the midline binaries all sit on the feature ring).
        signature = sorted((s["naturalResources"]["economy"],
                            s["naturalResources"]["industry"],
                            s["naturalResources"]["science"],
                            dist(pos[s["id"]], centre)) for s in members)
        if reference is None:
            reference = signature
            continue
        same = len(signature) == len(reference) and all(
            a[:3] == b[:3] and abs(a[3] - b[3]) < 1e-3
            for a, b in zip(signature, reference))
        require(same, f"galaxy {g} is not congruent to galaxy 0")

    # Dihedral symmetry inside a galaxy: a quarter turn about the core, and a
    # reflection in any midline, must each map it onto itself - resources and
    # role included. The reflection is the one that matters for fairness: it is
    # what makes a midline star's surroundings identical on both sides, so no
    # contested star sits nearer one player's expansion than the other's.
    for g, members in galaxies.items():
        core = next(s for s in members if s["_role"] == "core")
        centre = pos[core["id"]]
        local = [((pos[s["id"]][0] - centre[0], pos[s["id"]][1] - centre[1]), s)
                 for s in members]
        # The galaxy has been rotated onto the ring, so its midlines have moved
        # with it: take the bearing from one of its own capitals.
        first = next(p for p, s in local if s["_role"] == "capital" and s["_wedge"] == 0)
        axis = math.degrees(math.atan2(first[1], first[0])) + MIDLINE_OFFSET

        def image_of(point: tuple[float, float], flip: bool) -> tuple[float, float]:
            """A quarter turn, or a reflection in one of the galaxy's midlines."""
            if not flip:
                return rotate(point, WEDGE_STEP)
            turned = rotate(point, -axis)
            return rotate((turned[0], -turned[1]), axis)

        for flip, name in ((False, "quarter turn"), (True, "midline reflection")):
            for point, s in local:
                image = image_of(point, flip)
                twin_point, twin = min(local, key=lambda t: dist(t[0], image))
                require(dist(twin_point, image) < 1e-3,
                        f"galaxy {g}: nothing sits at the {name} of star {s['id']}")
                require(twin["_role"] == s["_role"],
                        f"star {s['id']} is a {s['_role']} but its {name} image "
                        f"{twin['id']} is a {twin['_role']}")
                require(twin["naturalResources"] == s["naturalResources"],
                        f"star {s['id']} and its {name} image {twin['id']} differ in "
                        f"resources: {s['naturalResources']} vs {twin['naturalResources']}")

    # Every star but the posts reachable from its core at hyperspace 3, and every
    # player's own 6 stars, 2 features and gateway reachable from their capital
    # at the hyperspace 2 they start on.
    core_ticks: list[float] = []
    for members in galaxies.values():
        pool = [s for s in members if s["_role"] != "post"]
        core = next(s for s in members if s["_role"] == "core")
        reachable = {core["id"]}
        frontier = [core]
        while frontier:
            current = frontier.pop()
            for other in pool:
                if other["id"] in reachable:
                    continue
                if dist(pos[current["id"]], pos[other["id"]]) <= REACH:
                    reachable.add(other["id"])
                    frontier.append(other)
        require(len(reachable) == len(pool),
                f"{len(pool) - len(reachable)} stars unreachable at hyperspace 3")

        # The core is an equal prize: same tick cost from every player's start,
        # on hyperspace-1 hops, at about CORE_TICK_TARGET ticks.
        for w in range(PLAYERS_PER_GALAXY):
            start = [s for s in members
                     if s["_wedge"] == w and s["_role"] in ("capital", "satellite")]
            core_ticks.append(ticks_to_core(pool, start, core, pos))

        for w in range(PLAYERS_PER_GALAXY):
            home = [s for s in members if s["_wedge"] == w and s["_role"] in
                    ("capital", "satellite", "gateway") + FEATURE_NAMES]
            capital = next(s for s in home if s["_role"] == "capital")
            seen = {capital["id"]}
            frontier = [capital]
            while frontier:
                current = frontier.pop()
                for other in home:
                    if other["id"] in seen:
                        continue
                    if dist(pos[current["id"]], pos[other["id"]]) <= HOP:
                        seen.add(other["id"])
                        frontier.append(other)
            require(len(seen) == len(home),
                    f"wedge {w}: {len(home) - len(seen)} starting stars need more than "
                    f"hyperspace {START_HYPERSPACE}")

    require(len(core_ticks) == N_PLAYERS, "core route not measured for every player")
    require(len(set(core_ticks)) == 1,
            f"players have unequal routes to their core: {sorted(set(core_ticks))} ticks")
    lo = CORE_TICK_TARGET * (1.0 - CORE_TICK_TOLERANCE)
    hi = CORE_TICK_TARGET * (1.0 + CORE_TICK_TOLERANCE)
    require(lo <= core_ticks[0] <= hi,
            f"core is {core_ticks[0]} ticks from a starting star, want "
            f"{CORE_TICK_TARGET} +/-{CORE_TICK_TOLERANCE:.0%} ({lo:.0f}-{hi:.0f})")

    # Every hop on the core chain must sit mid-bucket, or float noise flips a
    # wedge into the next tick and the routes stop being equal.
    for gap in (FEATURE_R - SATELLITE_R, CORE_BRIDGE_R, CAPITAL_R - FEATURE_R - CORE_BRIDGE_R):
        edge = min(gap % CARRIER_SPEED, CARRIER_SPEED - (gap % CARRIER_SPEED))
        require(edge >= CORE_TICK_MARGIN,
                f"core chain hop of {gap}u sits {edge:.1f}u from a tick boundary, "
                f"want >= {CORE_TICK_MARGIN}u")
        require(gap <= CORE_HOP, f"core chain hop of {gap}u exceeds hyperspace 1 ({CORE_HOP}u)")

    # --- no player starts with a better hand than any other ---
    # The galaxy as each of the 36 players sees it: every star in it, how far
    # from their capital, what it is worth, what it carries, and whether it is
    # theirs, a rival's or unowned. If all 36 of those readings are identical
    # then nobody has a shorter route to anything, a richer neighbourhood, a
    # closer wormhole or a softer neighbour - the positions are the same
    # position, turned.
    def player_view(player: dict) -> list[tuple]:
        capital = by_id[player["homeStarId"]]
        view = []
        for o in galaxies[capital["_galaxy"]]:
            nr, infra = o["naturalResources"], o["infrastructure"]
            view.append(((nr["economy"], nr["industry"], nr["science"],
                          o["_role"],
                          "mine" if o["playerId"] == player["id"]
                          else "rival" if o["playerId"] is not None else "neutral",
                          o["isBinaryStar"], o["isBlackHole"], o["isPulsar"],
                          o["isNebula"], o["isAsteroidField"], o["warpGate"],
                          o["specialistId"], o["wormHoleToStarId"] is not None,
                          infra["economy"], infra["industry"], infra["science"],
                          o["shipsActual"]),
                         dist(pos[capital["id"]], pos[o["id"]])))
        # Sorted on the exact fields first, so float noise in a distance can
        # never reorder two stars that are otherwise identical.
        return sorted(view)

    reference_id = players[0]["id"]
    reference_view = player_view(players[0])
    for player in players[1:]:
        view = player_view(player)
        same = len(view) == len(reference_view) and all(
            a[0] == b[0] and abs(a[1] - b[1]) < 1e-3
            for a, b in zip(view, reference_view))
        require(same, f"player {player['id']} does not see the same galaxy as "
                      f"player {reference_id}")

    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        raise SystemExit(f"\n{len(failures)} check(s) failed - nothing written.")


# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--galaxies", type=int, default=N_GALAXIES,
                        help=f"galaxies on the ring, {PLAYERS_PER_GALAXY} players each "
                             f"(default {N_GALAXIES})")
    parser.add_argument("--output", type=Path, default=None,
                        help="where to write the map (default out/spy_v_spy[_<players>p].json)")
    parser.add_argument("--render", action="store_true",
                        help="also draw the annotated documentation figures")
    args = parser.parse_args()
    configure(args.galaxies)
    if args.output is not None:
        global OUTPUT
        OUTPUT = args.output

    stars, players, exponent = build()
    check(stars, players)

    pos = {s["id"]: (s["location"]["x"], s["location"]["y"]) for s in stars}
    galaxy0 = [s for s in stars if s["_galaxy"] == 0]
    hops = []
    for s in galaxy0:
        if s["_role"] == "post":
            continue
        hops.append(min(dist(pos[s["id"]], pos[o["id"]]) for o in galaxy0
                        if o["id"] != s["id"] and o["_role"] != "post"))
    buckets: dict[int, int] = {}
    for h in hops:
        buckets[hyperspace_level(h)] = buckets.get(hyperspace_level(h), 0) + 1

    print(f"galaxies            {N_GALAXIES} on a ring, {PLAYERS_PER_GALAXY} players each")
    print(f"stars               {len(stars)}  ({len(stars) // N_GALAXIES} per galaxy)")
    print(f"players             {len(players)}")
    print(f"wormholes           {N_GALAXIES * N_WORMHOLE_SLOTS // 2} pairs, all neutral: "
          f"{N_PLAYERS} black hole posts, {N_PLAYERS} gateways, "
          f"{LINKS_PER_GALAXY_PAIR} link(s) between every pair of galaxies")
    print(f"starting stars      {STARTING_STARS} per player "
          f"({N_PLAYERS * STARTING_STARS} owned, {len(stars) - N_PLAYERS * STARTING_STARS} neutral)")
    print(f"fringe radius       {FRINGE_R:.2f}u ({FRINGE_R / LIGHT_YEAR:.1f} LY)")
    gateway = next(s for s in galaxy0 if s["_role"] == "gateway")
    capital = next(s for s in galaxy0 if s["_role"] == "capital"
                   and s["_wedge"] == gateway["_wedge"])
    nebula = next(s for s in galaxy0 if s["_role"] == "nebula"
                  and s["_wedge"] == gateway["_wedge"])
    to_capital = dist(pos[gateway["id"]], pos[capital["id"]])
    to_nebula = dist(pos[gateway["id"]], pos[nebula["id"]])
    print(f"midlines            {PLAYERS_PER_GALAXY} per galaxy, {WEDGE_STEP:.0f} degrees apart, "
          f"each a mirror axis: inner ring {INNER_RING_R:.0f}u, binary {BINARY_R:.0f}u, "
          f"{FRINGE_COUNT} fringe stars, post {POST_R:.0f}u from the core")
    print(f"inner ring          {2 * PLAYERS_PER_GALAXY} stars at {INNER_RING_R:.0f}u, "
          f"{360 / (2 * PLAYERS_PER_GALAXY):.0f} degrees apart - the four pods' asteroid fields "
          f"and one more on each midline")
    print(f"gateways            one per player on their own bisector: {to_nebula:.1f}u past "
          f"their nebula (hyperspace {hyperspace_level(to_nebula)}), {to_capital:.1f}u from "
          f"their capital (hyperspace {hyperspace_level(to_capital)})")
    post = next(s for s in galaxy0 if s["_role"] == "post")
    post_owned = min(dist(pos[post["id"]], pos[o["id"]]) for o in galaxy0
                     if o["playerId"] is not None)
    print(f"post isolation      {POST_ISOLATION}u = hyperspace "
          f"{hyperspace_level(POST_ISOLATION)}; the black hole alone shows the binary and all "
          f"{FRINGE_COUNT} fringe stars, {FRINGE_HOP:.1f}u apart along the arc")
    print(f"post scan           {POST_SCAN:.0f}u once taken (black hole +"
          f"{BLACK_HOLE_SCANNING_BONUS}, Telescope Array +{TELESCOPE_SCANNING_BONUS}), and the "
          f"nearest starting star of either neighbour is {post_owned:.0f}u away")
    chain = [FEATURE_R - SATELLITE_R, CORE_BRIDGE_R, CAPITAL_R - FEATURE_R - CORE_BRIDGE_R]
    print(f"core run            {sum(ticks_for(g) for g in chain)} ticks, identical for all "
          f"{N_PLAYERS} players (hops {'+'.join(f'{g:.0f}u' for g in chain)}, hyperspace 1)")
    print(f"resource curve      NR = {NR_MIN} + {NR_SPAN} * (1 - r/R)^{exponent:.3f}")
    for channel in ("economy", "industry", "science"):
        values = [s["naturalResources"][channel] for s in stars]
        print(f"  {channel:<9}       min {min(values):>3}  median {statistics.median(values):>3.0f}  "
              f"mean {statistics.mean(values):>5.1f}  max {max(values):>3}")
    print(f"nearest-neighbour   min {min(hops):.0f}u  median {statistics.median(hops):.0f}u  "
          f"max {max(hops):.0f}u")
    print("hops by hyperspace  " + "  ".join(f"h{k}: {buckets[k]}" for k in sorted(buckets)))

    # model.galaxy drops every scratch field (anything starting with `_`) and
    # emits the exact CustomGalaxy shape.
    galaxy_json = model.galaxy(stars, players, carriers=[])

    # The map does not ship until Solaris would accept it. This is the same
    # check the game runs at Create Game time, so a pass here means the file
    # loads there.
    report = validate.validate(galaxy_json)
    for warning in report.warnings:
        print(f"warning             {warning}")
    report.raise_for_errors()

    model.write(OUTPUT, galaxy_json)
    print(f"\nwrote {OUTPUT}  ({OUTPUT.stat().st_size / 1024:.0f} KB)  "
          f"validated against Solaris's rules")

    if args.render:
        render_figures(galaxy_json)


# --------------------------------------------------------------------------
# Figures
#
# The generic renderer draws the galaxy; everything below is what is specific
# to *this* map, expressed as annotation hooks. Roles are recovered from terrain
# because the written JSON carries no scratch fields: a pulsar is a galactic
# core, a black hole is a spy post, any other wormhole star is a gateway.
# --------------------------------------------------------------------------


def _roles(data: dict) -> dict[str, list[dict]]:
    stars = data["stars"]
    return {
        "cores": [s for s in stars if s["isPulsar"]],
        "posts": [s for s in stars if s["isBlackHole"]],
        "gateways": [s for s in stars if s["wormHoleToStarId"] and not s["isBlackHole"]],
        "capitals": [s for s in stars if s["homeStar"]],
    }


def _point(star: dict) -> tuple[float, float]:
    return star["location"]["x"], star["location"]["y"]


def render_figures(data: dict) -> None:
    """Write the two documentation figures into out/."""
    from solarismap import render

    roles = _roles(data)
    out_dir = ROOT / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    def mark_cores(ctx):
        """Amber rings on each galactic core, numbered round the ring."""
        for index, core in enumerate(sorted(roles["cores"],
                                            key=lambda s: math.atan2(*_point(s)[::-1])), 1):
            cx, cy = _point(core)
            yield ctx.circle(cx, cy, 40, ctx.palette.amber, 2.4, 0.95)
            yield ctx.circle(cx, cy, 54, ctx.palette.amber, 1.2, 0.45, dash="8 7")
            yield ctx.text(cx, cy - 72, f"galaxy {index}", 30, ctx.palette.amber, weight="700")

    def mark_posts(ctx):
        """What a spy post sees: the black hole alone, then with its array."""
        for post in roles["posts"]:
            cx, cy = _point(post)
            yield ctx.circle(cx, cy, POST_CLEARANCE, ctx.palette.green, 1.6, 0.30, dash="14 10")
            yield ctx.circle(cx, cy, POST_SCAN, ctx.palette.green, 1.4, 0.20, dash="6 12")

    # --- the whole ring ---------------------------------------------------
    whole = render.draw(
        data,
        render.Options(resources=False, ships=False, margin=260.0),
        annotate_over=lambda ctx: list(mark_cores(ctx)) + list(mark_posts(ctx)),
    )
    target = out_dir / "spy_v_spy.svg"
    target.write_text(whole, encoding="utf-8")
    print(f"wrote {target}  ({target.stat().st_size / 1024:.0f} KB, the whole ring)")

    # --- one galaxy, annotated -------------------------------------------
    core = min(roles["cores"], key=lambda s: math.atan2(*_point(s)[::-1]))
    fx, fy = _point(core)

    def callouts(ctx):
        """Name one of each kind of star, with a leader line out to the label."""
        here = [s for s in ctx.stars
                if geometry.dist(_point(s), (fx, fy)) < POST_R + 200]
        named = [
            ("capital", next((s for s in here if s["homeStar"]), None)),
            ("spy post: +6 scanning, reachable only by wormhole",
             next((s for s in here if s["isBlackHole"]), None)),
            ("wormhole gateway",
             next((s for s in here if s["wormHoleToStarId"] and not s["isBlackHole"]), None)),
            ("contested binary, 75 resources",
             next((s for s in here if s["isBinaryStar"] and s["playerId"] is None
                   and not s["isPulsar"]
                   and (s["naturalResources"] or {}).get("economy") == BINARY_NR), None)),
            ("nebula: science", next((s for s in here if s["isNebula"]), None)),
            ("asteroid field: economy", next((s for s in here if s["isAsteroidField"]), None)),
        ]
        for label, star in named:
            if star is None:
                continue
            cx, cy = _point(star)
            angle = math.atan2(cy - fy, cx - fx)
            lx = cx + 150 * math.cos(angle)
            ly = cy + 150 * math.sin(angle)
            anchor = "start" if lx >= cx else "end"
            yield ctx.line(cx, cy, lx, ly, ctx.palette.muted, 1.4, 0.75)
            yield ctx.text(lx + (8 if anchor == "start" else -8), ly + 5, label, 20,
                           ctx.palette.paper, anchor=anchor, weight="700")

    pod = render.draw(
        data,
        render.Options(resources=True, ships=True, margin=80.0,
                       focus=(fx, fy, POST_R + 260)),
        annotate_over=lambda ctx: list(mark_posts(ctx)) + list(callouts(ctx)),
    )
    target = out_dir / "spy_v_spy_pod.svg"
    target.write_text(pod, encoding="utf-8")
    print(f"wrote {target}  ({target.stat().st_size / 1024:.0f} KB, one galaxy annotated)")


if __name__ == "__main__":
    main()
