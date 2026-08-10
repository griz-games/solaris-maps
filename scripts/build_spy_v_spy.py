#!/usr/bin/env python3
"""Build a 36-player symmetric multi-galaxy custom map for Solaris.

Emits map36.json in the editor's native 'editor_this' structure, which is
field-for-field Solaris's CustomGalaxy input format.

Layout: 9 galaxies on a ring, 4 player wedges each. Every galaxy is linked to
every other exactly once (C(9,2) = 36 wormholes). Exactly one end of each
wormhole is a spy post owned by a foreign player and carrying a Telescope
Array, so all 36 players get exactly one spy and no wormhole has two. The far
(neutral) end of each link sits beside its owner's nebula, one hyperspace-2 hop
from home.

Run:  python scripts/build_map.py
"""

import heapq
import json
import math
import random
import statistics
from pathlib import Path

# --------------------------------------------------------------------------
# Constants mirrored from the editor source (this script cannot import from
# src/: helper.ts pulls in the Pinia store and map.ts, and the specialist and
# colour tables are defineStore() calls).
# --------------------------------------------------------------------------

LIGHT_YEAR = 50.0                       # GalaxyMap.lightYearDistance, src/scripts/map.ts:28
MIN_STAR_SEPARATION = 50.0              # settings.generation.minDistanceBetweenStars, src/scripts/storage.ts:194

SPECIALIST_WAR_MACHINE = 7              # star specialist id 7, src/stores/specialists.ts:595
SPECIALIST_TELESCOPE_ARRAY = 13         # star specialist id 13, src/stores/specialists.ts:723


def hyperspace_range(level: float) -> float:
    """helper.getHyperspaceDistanceByLevel - src/scripts/helper.ts:199"""
    return (level + 1.5) * LIGHT_YEAR


def hyperspace_level(distance: float) -> int:
    """helper.getHyperspaceLevelByDistance - src/scripts/helper.ts:194"""
    return math.ceil(distance / LIGHT_YEAR - 1.5) or 1


def scanning_range(level: float) -> float:
    """Inverse of helper.getScanningLevelByDistance - src/scripts/helper.ts:189"""
    return (level + 1) * LIGHT_YEAR


# --------------------------------------------------------------------------
# CONFIG - every tunable lives here
# --------------------------------------------------------------------------

N_GALAXIES = 9
PLAYERS_PER_GALAXY = 4
N_PLAYERS = N_GALAXIES * PLAYERS_PER_GALAXY             # 36
N_WORMHOLE_SLOTS = N_GALAXIES - 1                       # 8 wormhole stars per galaxy

START_HYPERSPACE = 2                                    # player starting hyperspace tech
START_SCANNING = 2                                      # player starting scanning tech
TELESCOPE_SCANNING_BONUS = 3                            # Telescope Array local.scanning modifier

HOP = hyperspace_range(START_HYPERSPACE)                # 175.0 - normal travel at game start
REACH = hyperspace_range(3)                             # 225.0 - the galaxy-wide connectivity floor
SPY_SCAN = scanning_range(START_SCANNING + TELESCOPE_SCANNING_BONUS)   # 300.0

# Isolation of every spy post from the rest of the map. Sits 0.1u under
# hyperspace_range(4) = 275.0 so float noise can never round the requirement up
# to level 5; still far outside hyperspace_range(3) = 225.0.
SPY_ISOLATION = hyperspace_range(4) - 0.1               # 274.9

# The galactic core must be an equal-length prize for all 36 players: reachable
# from a starting star on hyperspace-1 hops in about CORE_TICK_TARGET ticks, and
# in exactly the same number of ticks for everyone.
# helper.getTicksBetweenObjects charges ceil(distance / speed) per hop, so every
# hop on the chain is placed mid-bucket - at least CORE_TICK_MARGIN away from a
# multiple of CARRIER_SPEED. Land one on a bucket boundary and the ~1e-6 float
# noise from rotating each galaxy onto the ring flips some wedges up a whole
# tick, which silently breaks the symmetry.
CARRIER_SPEED = 10.0                                    # settings.carriers.baseCarrierSpeed,
                                                        # src/scripts/storage.ts:173 (Standard, 0.2 ly/tick)
CORE_HOP = hyperspace_range(1)                          # 125.0
CORE_TICK_TARGET = 30
CORE_TICK_TOLERANCE = 0.10
CORE_TICK_MARGIN = 3.0

# Wedge layout, in the wedge's local frame (+x points radially outward).
CAPITAL_R = 409.0                                       # capital distance from the galactic core
SATELLITE_R = 120.0                                     # satellite ring around the capital
SATELLITE_ANGLES = (36.0, -36.0, 108.0, -108.0, 180.0)  # 0 deliberately empty: the +-36 pair
                                                        # is what the spy post sees
FEATURE_R = 215.0                                       # feature ring around the capital
FEATURE_ANGLES = (72.0, -72.0, 180.0)                   # binary, nebula, asteroid field

# The neutral end of each player's wormhole sits this far from their nebula,
# drawn straight in towards the galactic core. 170u = hyperspace 2.
GATEWAY_TO_NEBULA = 170.0

# One filler star per wedge, halfway from the core out to the inward feature.
# That splits the run to the core into three hops of 95, 97 and 97 units - all
# inside hyperspace 1, all mid-bucket, 30 ticks end to end:
#   inner satellite (289) -> asteroid (194) -> bridge (97) -> core (0)
CORE_BRIDGE_R = (CAPITAL_R - FEATURE_R) / 2.0           # 97.0

# Filler: stochastic, but evaluated in wedge-local coordinates and stamped into
# all four wedges, so the pockets are identical under 90 degree rotation.
FILLER_PER_WEDGE = 10                                   # includes the 1 core bridge star
FILLER_SEED = 20260810
FILLER_ATTEMPTS = 20000                                 # dart throws per placement
FILLER_INNER_R = 90.0
SEPARATION_DENSE = 85.0                                 # min separation where the field is dense
SEPARATION_SPARSE = 150.0                               # min separation where the field is sparse

EDGE_GAP = 20.0 * LIGHT_YEAR                            # 1000u between adjacent galaxies

# Resource curve: NR = NR_MIN + NR_SPAN * (1 - r/R)^exponent, with the exponent
# solved at build time so the median star lands on NR_MEDIAN_TARGET.
NR_MIN = 10                                             # at the fringe
NR_MAX = 100                                            # at the galactic core
NR_SPAN = NR_MAX - NR_MIN
NR_MEDIAN_TARGET = 25

BINARY_FEATURE_NR = 75                                  # binary star near each player
FEATURE_MULTIPLIER = 3                                  # nebula science / asteroid economy

CORE_NR = 150                                           # the War Machine core overrides the curve
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

# One colour per galaxy, one shape per wedge -> 36 unique combos, and galaxy
# membership is readable at a glance. Cosmetic only; Solaris reassigns both.
GALAXY_COLOURS = [
    {"alias": "Red", "value": "#ff0000"},
    {"alias": "Blue", "value": "#0000ff"},
    {"alias": "Lime", "value": "#00ff00"},
    {"alias": "Yellow", "value": "#ffff00"},
    {"alias": "Magenta", "value": "#ff00ff"},
    {"alias": "Cyan", "value": "#00ffff"},
    {"alias": "Royal orange", "value": "#ff7a2a"},
    {"alias": "Purple", "value": "#800080"},
    {"alias": "Silver", "value": "#e0e0e0"},
]
WEDGE_SHAPES = ["circle", "square", "hexagon", "diamond"]

OUTPUT = Path(__file__).resolve().parent.parent / "map36.json"

# --------------------------------------------------------------------------
# Derived geometry
# --------------------------------------------------------------------------


def polar(r: float, degrees: float) -> tuple[float, float]:
    a = math.radians(degrees)
    return r * math.cos(a), r * math.sin(a)


def rotate(p: tuple[float, float], degrees: float) -> tuple[float, float]:
    a = math.radians(degrees)
    ca, sa = math.cos(a), math.sin(a)
    return p[0] * ca - p[1] * sa, p[0] * sa + p[1] * ca


def dist(p: tuple[float, float], q: tuple[float, float]) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def ticks_for(distance: float) -> int:
    """helper.getTicksBetweenObjects - src/scripts/helper.ts:160-181"""
    return math.ceil(distance / CARRIER_SPEED)


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


# The +36 satellite in wedge-local coordinates. The spy radius is derived from
# it, not chosen: it is the radius at which both the +36 and -36 satellites sit
# at exactly SPY_ISOLATION from the spy post directly outward of them.
_SAT36 = (CAPITAL_R + SATELLITE_R * math.cos(math.radians(36.0)),
          SATELLITE_R * math.sin(math.radians(36.0)))
FRINGE_R = _SAT36[0] + math.sqrt(SPY_ISOLATION ** 2 - _SAT36[1] ** 2)

WEDGE_STEP = 360.0 / PLAYERS_PER_GALAXY                 # 90 degrees
SLOT_STEP = 360.0 / N_WORMHOLE_SLOTS                    # 45 degrees
GALAXY_STEP = 360.0 / N_GALAXIES                        # 40 degrees


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
    return {
        "id": None,                                     # assigned once the galaxy is complete
        "homeStar": False,
        "playerId": None,
        "warpGate": False,
        "isNebula": False,
        "isAsteroidField": False,
        "isBinaryStar": False,
        "isBlackHole": False,
        "isPulsar": False,
        "wormHoleToStarId": None,
        "specialistId": None,
        "specialistExpireTick": None,
        "location": {"x": pos[0], "y": pos[1]},
        "naturalResources": None,                       # assigned once the curve is solved
        "shipsActual": 0,
        "ships": 0,
        "infrastructure": {"economy": 0, "industry": 0, "science": 0},
        # scratch fields, stripped before writing
        "_role": None,
        "_wedge": None,
        "_slot": None,
        "_radius": math.hypot(*pos),                    # distance from the galactic core
    }


def wedge_local(role: str) -> tuple[float, float]:
    """Position of a named wedge object in the wedge's own frame."""
    if role == "capital":
        return (CAPITAL_R, 0.0)
    for angle in SATELLITE_ANGLES:
        if role == f"satellite{angle:+.0f}":
            offset = polar(SATELLITE_R, angle)
            return (CAPITAL_R + offset[0], offset[1])
    for angle, name in zip(FEATURE_ANGLES, ("binary", "nebula", "asteroid")):
        if role == name:
            offset = polar(FEATURE_R, angle)
            return (CAPITAL_R + offset[0], offset[1])
    raise KeyError(role)


def gateway_local() -> tuple[float, float]:
    """Neutral wormhole mouth: GATEWAY_TO_NEBULA inward of the wedge's nebula.

    Drawn towards the galactic core rather than outward so it stays clear of
    every spy post's 300u scan bubble.
    """
    nebula = wedge_local("nebula")
    r = math.hypot(*nebula)
    return (nebula[0] * (r - GATEWAY_TO_NEBULA) / r,
            nebula[1] * (r - GATEWAY_TO_NEBULA) / r)


def build_wedge(wedge: int) -> list[dict]:
    """Capital + 5 satellites + 3 feature stars, rotated onto wedge's bisector."""
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

    for role in ("binary", "nebula", "asteroid"):
        star = place(wedge_local(role), role)
        star["isBinaryStar"] = role == "binary"
        star["isNebula"] = role == "nebula"
        star["isAsteroidField"] = role == "asteroid"

    return stars


def build_fringe() -> list[dict]:
    """8 wormhole stars: 4 isolated spy posts, 4 gateways beside the nebulas.

    Slot k pairs with galaxy (g + k + 1) % 9. Even slots land on a wedge
    bisector out at FRINGE_R and become spy posts watching that wedge's player;
    odd slot 2w+1 is player w's own neutral gateway, parked one hyperspace-2 hop
    inward of their nebula.
    """
    stars = []
    for slot in range(N_WORMHOLE_SLOTS):
        wedge = slot // 2
        if slot % 2 == 0:
            star = new_star(polar(FRINGE_R, WEDGE_STEP * wedge))
            star["_role"] = "spy"
            star["specialistId"] = SPECIALIST_TELESCOPE_ARRAY
        else:
            star = new_star(rotate(gateway_local(), WEDGE_STEP * wedge))
            star["_role"] = "gateway"
        star["_slot"] = slot
        star["_wedge"] = wedge                          # spy: the wedge it watches
        stars.append(star)                              # gateway: the wedge that owns it
    return stars


def build_filler(seeded: list[dict], fringe: list[dict]) -> list[dict]:
    """Neutral background stars: stochastic, pocketed, 4-fold symmetric.

    Dart-thrown against a smooth density field so the galaxy grows dense
    clusters and sparse voids, but every throw is evaluated in wedge-local
    coordinates and stamped into all four wedges at once, so the galaxy stays
    exactly symmetric under 90 degree rotation. Each star must land within one
    hyperspace-3 hop of something already placed, which keeps the galaxy in a
    single connected component no matter how the field falls.
    """
    rng = random.Random(FILLER_SEED)
    spies = [(s["location"]["x"], s["location"]["y"]) for s in fringe if s["_role"] == "spy"]

    occupied = [(s["location"]["x"], s["location"]["y"]) for s in seeded]
    occupied += [(s["location"]["x"], s["location"]["y"]) for s in fringe]
    # Spy posts are deliberately unreachable at hyperspace 3, so they are not
    # valid anchors for the connectivity requirement.
    anchors = [(s["location"]["x"], s["location"]["y"]) for s in seeded]
    anchors += [(s["location"]["x"], s["location"]["y"]) for s in fringe if s["_role"] == "gateway"]

    filler = []

    def commit(local: tuple[float, float], role: str) -> None:
        for wedge in range(PLAYERS_PER_GALAXY):
            pos = rotate(local, WEDGE_STEP * wedge)
            star = new_star(pos)
            star["_role"] = role
            star["_wedge"] = wedge
            filler.append(star)
            occupied.append(pos)
            anchors.append(pos)

    # Bridge star: the galactic core is CAPITAL_R - FEATURE_R from the nearest
    # wedge star, too far to reach, so one filler per wedge splits the gap.
    commit((CORE_BRIDGE_R, 0.0), "bridge")

    def admissible(p: tuple[float, float]) -> bool:
        # Nothing may enter a spy's scan bubble except its two target
        # satellites, so each spy sees exactly one player and nothing else.
        if any(dist(p, s) <= SPY_SCAN for s in spies):
            return False
        images = [rotate(p, WEDGE_STEP * w) for w in range(PLAYERS_PER_GALAXY)]
        needed = separation_at(p)
        for img in images:
            if any(dist(img, o) < needed for o in occupied):
                return False
        for i in range(len(images)):
            for j in range(i + 1, len(images)):
                if dist(images[i], images[j]) < needed:
                    return False
        return min(dist(p, a) for a in anchors) <= REACH

    for _ in range(FILLER_PER_WEDGE - 1):
        fallback = None
        for attempt in range(FILLER_ATTEMPTS):
            u = rng.random()
            r = math.sqrt(u * (FRINGE_R ** 2 - FILLER_INNER_R ** 2) + FILLER_INNER_R ** 2)
            theta = rng.uniform(-WEDGE_STEP / 2.0, WEDGE_STEP / 2.0)
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
    core["isBinaryStar"] = True
    core["specialistId"] = SPECIALIST_WAR_MACHINE
    core["infrastructure"] = dict(CORE_INFRASTRUCTURE)

    wedges = [s for w in range(PLAYERS_PER_GALAXY) for s in build_wedge(w)]
    fringe = build_fringe()
    filler = build_filler([core] + wedges, fringe)
    return [core] + wedges + fringe + filler


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
    if role == "binary":
        return (BINARY_FEATURE_NR,) * 3
    # "3x" is applied to the capital's curve value so every one of the 36
    # players gets identical features regardless of where each one lands on the
    # gradient. Swap to curve(star["_radius"], ...) for 3x the feature's own
    # positional value instead.
    base = curve(CAPITAL_R, exponent)
    if role == "nebula":
        return (base, base, base * FEATURE_MULTIPLIER)
    if role == "asteroid":
        return (base * FEATURE_MULTIPLIER, base, base)
    value = curve(star["_radius"], exponent)
    return (value, value, value)


def solve_exponent(stars: list[dict]) -> float:
    """Find the curve exponent whose median star is NR_MEDIAN_TARGET.

    The median is a descending step function of the exponent, so bisection
    lands on the interval that produces the target and returns its midpoint.
    """
    def median_at(exponent: float) -> float:
        return statistics.median(resources_for(s, exponent)[0] for s in stars)

    lo, hi = 0.1, 12.0
    if median_at(lo) < NR_MEDIAN_TARGET or median_at(hi) > NR_MEDIAN_TARGET:
        raise RuntimeError(f"median {NR_MEDIAN_TARGET} unreachable "
                           f"({median_at(lo)} .. {median_at(hi)})")
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if median_at(mid) > NR_MEDIAN_TARGET:
            lo = mid
        else:
            hi = mid
    # lo is the last exponent above the target, hi the first at or below it.
    return hi if median_at(hi) == NR_MEDIAN_TARGET else lo


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
            players.append({
                "id": player_id,
                "homeStarId": capital["id"],
                "colour": dict(GALAXY_COLOURS[g]),
                "shape": WEDGE_SHAPES[w],
                "technologies": dict(STARTING_TECHNOLOGIES),
                "credits": STARTING_CREDITS,
                "creditsSpecialists": STARTING_CREDITS_SPECIALISTS,
            })
            for star in galaxies[g]:
                if star["_wedge"] == w and star["_role"] in ("capital", "satellite"):
                    star["playerId"] = player_id
                    star["shipsActual"] = STARTING_SHIPS
                    star["ships"] = STARTING_SHIPS

    # ---- wormholes -----------------------------------------------------
    # Slot k in galaxy g pairs with galaxy g+k+1. Even k is the spy end, owned
    # by wedge (3 - k/2) of the partner galaxy; odd k is a neutral gateway.
    for g in range(N_GALAXIES):
        for slot in range(N_WORMHOLE_SLOTS):
            here = next(s for s in galaxies[g] if s["_slot"] == slot)
            partner_galaxy = (g + slot + 1) % N_GALAXIES
            partner_slot = N_WORMHOLE_SLOTS - 1 - slot
            there = next(s for s in galaxies[partner_galaxy] if s["_slot"] == partner_slot)
            here["wormHoleToStarId"] = there["id"]

            if slot % 2 == 0:
                wedge = PLAYERS_PER_GALAXY - 1 - slot // 2
                owner = str(partner_galaxy * PLAYERS_PER_GALAXY + wedge + 1)
                here["playerId"] = owner
                here["shipsActual"] = STARTING_SHIPS
                here["ships"] = STARTING_SHIPS

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

    # --- counts and identity ---
    per_galaxy = 1 + PLAYERS_PER_GALAXY * (9 + FILLER_PER_WEDGE) + N_WORMHOLE_SLOTS
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
    require(len({(p["colour"]["value"], p["shape"]) for p in players}) == N_PLAYERS,
            "duplicate colour/shape combo")

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
    require(len(pairs) == N_GALAXIES * (N_GALAXIES - 1) // 2,
            f"expected 36 wormhole pairs, got {len(pairs)}")
    galaxy_pairs = {frozenset((by_id[a]["_galaxy"], by_id[b]["_galaxy"])) for a, b in
                    (tuple(p) for p in pairs)}
    require(len(galaxy_pairs) == len(pairs), "a galaxy pair is linked more than once")
    require(all(len(gp) == 2 for gp in galaxy_pairs), "a galaxy wormholes to itself")

    spies = [s for s in stars if s["specialistId"] == SPECIALIST_TELESCOPE_ARRAY]
    require(len(spies) == N_PLAYERS, f"expected {N_PLAYERS} spy posts, got {len(spies)}")
    for a, b in (tuple(p) for p in pairs):
        n_spy = sum(1 for e in (a, b) if by_id[e]["specialistId"] == SPECIALIST_TELESCOPE_ARRAY)
        require(n_spy == 1, f"wormhole {a}<->{b} has {n_spy} spy ends, expected 1")

    owners = [s["playerId"] for s in spies]
    require(len(set(owners)) == N_PLAYERS, "a player owns more than one spy post")
    require(all(o is not None for o in owners), "spy post without an owner")
    home_galaxy = {p["id"]: by_id[p["homeStarId"]]["_galaxy"] for p in players}
    for s in spies:
        require(home_galaxy[s["playerId"]] != s["_galaxy"],
                f"spy {s['id']} is owned by a player from its own galaxy")

    # --- spy isolation and vision ---
    watched = []
    for s in spies:
        ranked = sorted(((dist(pos[s["id"]], pos[o["id"]]), o) for o in stars if o["id"] != s["id"]),
                        key=lambda t: t[0])
        nearest = ranked[0][0]
        require(abs(nearest - SPY_ISOLATION) < 1e-3,
                f"spy {s['id']} nearest neighbour is {nearest:.3f}, expected {SPY_ISOLATION}")
        require(hyperspace_level(nearest) == 4,
                f"spy {s['id']} needs hyperspace {hyperspace_level(nearest)}, expected 4")
        visible = [o for d, o in ranked if d <= SPY_SCAN]
        seen = {o["playerId"] for o in visible if o["playerId"] is not None}
        require(len(seen) == 1, f"spy {s['id']} sees {len(seen)} players, expected exactly 1")
        require(all(o["playerId"] is not None for o in visible),
                f"spy {s['id']} has a neutral star inside its scan bubble")
        if seen:
            watched.append(seen.pop())
    require(len(set(watched)) == N_PLAYERS, "some player is watched by zero or multiple spies")
    require(all(w != o for w, o in zip(watched, owners)), "a spy watches its own owner")

    # --- gateways sit beside their owner's nebula ---
    gateways = [s for s in wormholes if s["specialistId"] is None]
    require(len(gateways) == N_PLAYERS, f"expected {N_PLAYERS} gateways, got {len(gateways)}")
    for gw in gateways:
        require(gw["playerId"] is None, f"gateway {gw['id']} should start neutral")
        nebula = next(s for s in stars if s["_galaxy"] == gw["_galaxy"]
                      and s["_role"] == "nebula" and s["_wedge"] == gw["_wedge"])
        d = dist(pos[gw["id"]], pos[nebula["id"]])
        require(abs(d - GATEWAY_TO_NEBULA) < 1e-3,
                f"gateway {gw['id']} is {d:.2f} from its nebula, expected {GATEWAY_TO_NEBULA}")
        require(hyperspace_level(d) == 2,
                f"gateway {gw['id']} needs hyperspace {hyperspace_level(d)} from its nebula")
        owner = next(p for p in players
                     if home_galaxy[p["id"]] == gw["_galaxy"]
                     and p["id"] == str(gw["_galaxy"] * PLAYERS_PER_GALAXY + gw["_wedge"] + 1))
        spy = next(s for s in spies if s["playerId"] == owner["id"])
        require(gw["wormHoleToStarId"] == spy["id"],
                f"gateway {gw['id']} does not lead to the spy of the player beside it")

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
        if s["specialistId"] is not None:
            require(s["specialistId"] in (SPECIALIST_WAR_MACHINE, SPECIALIST_TELESCOPE_ARRAY),
                    f"star {s['id']} has an unexpected specialist")

    for channel in ("economy", "industry", "science"):
        med = statistics.median(s["naturalResources"][channel] for s in stars)
        require(med == NR_MEDIAN_TARGET, f"median {channel} is {med}, expected {NR_MEDIAN_TARGET}")
    gradient = [s["naturalResources"]["economy"] for s in stars
                if s["_role"] not in ("core", "binary", "nebula", "asteroid")]
    require(min(gradient) == NR_MIN, f"fringe resources are {min(gradient)}, expected {NR_MIN}")
    require(max(gradient) <= NR_MAX, f"gradient peaks at {max(gradient)}, expected <= {NR_MAX}")

    owned = [s for s in stars if s["playerId"] is not None]
    require(len(owned) == N_PLAYERS * 7, f"expected {N_PLAYERS * 7} owned stars, got {len(owned)}")

    # --- separation, symmetry, connectivity ---
    galaxies: dict[int, list[dict]] = {}
    for s in stars:
        galaxies.setdefault(s["_galaxy"], []).append(s)

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
        # radius can never reorder two stars that share a radius (the binary and
        # the nebula both sit at FEATURE_R from their capital).
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

    # Every non-spy star reachable from its core at hyperspace 3, and every
    # player's own 6 stars + 3 features reachable from their capital at 2.
    core_ticks: list[float] = []
    for members in galaxies.values():
        pool = [s for s in members if s["_role"] != "spy"]
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
                    ("capital", "satellite", "binary", "nebula", "asteroid", "gateway")]
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

    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        raise SystemExit(f"\n{len(failures)} check(s) failed - nothing written.")


# --------------------------------------------------------------------------


def main() -> None:
    stars, players, exponent = build()
    check(stars, players)

    pos = {s["id"]: (s["location"]["x"], s["location"]["y"]) for s in stars}
    galaxy0 = [s for s in stars if s["_galaxy"] == 0]
    hops = []
    for s in galaxy0:
        if s["_role"] == "spy":
            continue
        hops.append(min(dist(pos[s["id"]], pos[o["id"]]) for o in galaxy0
                        if o["id"] != s["id"] and o["_role"] != "spy"))
    buckets: dict[int, int] = {}
    for h in hops:
        buckets[hyperspace_level(h)] = buckets.get(hyperspace_level(h), 0) + 1

    print(f"galaxies            {N_GALAXIES} on a ring, {PLAYERS_PER_GALAXY} players each")
    print(f"stars               {len(stars)}  ({len(stars) // N_GALAXIES} per galaxy)")
    print(f"players             {len(players)}")
    print(f"wormholes           {N_GALAXIES * N_WORMHOLE_SLOTS // 2} pairs, "
          f"{N_PLAYERS} spy posts, {N_PLAYERS} neutral gateways")
    print(f"fringe radius       {FRINGE_R:.2f}u ({FRINGE_R / LIGHT_YEAR:.1f} LY)")
    print(f"spy isolation       {SPY_ISOLATION}u = hyperspace {hyperspace_level(SPY_ISOLATION)}")
    print(f"gateway to nebula   {GATEWAY_TO_NEBULA}u = hyperspace "
          f"{hyperspace_level(GATEWAY_TO_NEBULA)}")
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

    for s in stars:
        for key in ("_role", "_wedge", "_slot", "_galaxy", "_radius"):
            s.pop(key, None)

    OUTPUT.write_text(json.dumps({"stars": stars, "players": players, "carriers": []}),
                      encoding="utf-8")
    print(f"\nwrote {OUTPUT}  ({OUTPUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
