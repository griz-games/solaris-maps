"""Solaris game rules: the constants and the math every map has to obey.

Every function here mirrors a specific function in the editor or in Solaris
itself, and carries the source reference. Nothing in this module knows about
any particular map - it is the layer a map builder computes distances against.

The editor is the reference for the geometry (it is what renders the map and
what Solaris's own Create Game page points authors at); Solaris's validator is
the reference for the limits.
"""

from __future__ import annotations

import math

# --------------------------------------------------------------------------
# Scale
# --------------------------------------------------------------------------

# The unit every range in the game keys off. A "light year" is 50 world units.
LIGHT_YEAR = 50.0                   # GalaxyMap.lightYearDistance, editor map.ts

# The editor's default minimum spacing between two stars. Not enforced by
# Solaris - a map may pack stars tighter - but going below it makes a galaxy
# hard to read and hard to click.
MIN_STAR_SEPARATION = 50.0          # settings.generation.minDistanceBetweenStars, editor storage.ts

# Carrier speed in world units per tick, before any modifier.
BASE_CARRIER_SPEED = 10.0           # settings.carriers.baseCarrierSpeed, editor storage.ts

# Terrain that changes a star's effective technology levels.
BLACK_HOLE_SCANNING_BONUS = 3       # helper.getEffectiveTechs, editor helper.ts


# --------------------------------------------------------------------------
# Ranges
#
# Hyperspace and scanning are inverses of each other but they are NOT the same
# formula: hyperspace subtracts 1.5 light years, scanning subtracts 1.
# --------------------------------------------------------------------------


def hyperspace_range(level: float) -> float:
    """How far a carrier at this hyperspace level can jump, in world units.

    helper.getHyperspaceDistanceByLevel - editor helper.ts
    """
    return (level + 1.5) * LIGHT_YEAR


def hyperspace_level(distance: float) -> int:
    """Lowest hyperspace level that can cross this distance in one jump.

    helper.getHyperspaceLevelByDistance - editor helper.ts
    """
    return math.ceil(distance / LIGHT_YEAR - 1.5) or 1


def scanning_range(level: float) -> float:
    """How far a star at this scanning level can see, in world units.

    Inverse of helper.getScanningLevelByDistance - editor helper.ts
    """
    return (level + 1) * LIGHT_YEAR


def scanning_level(distance: float) -> int:
    """Lowest scanning level that reaches this distance.

    helper.getScanningLevelByDistance - editor helper.ts
    """
    return math.ceil(distance / LIGHT_YEAR - 1) or 1


def ticks_by_distance(distance: float, carrier_speed: float = BASE_CARRIER_SPEED,
                      tick_distance_modifier: float = 1.0) -> int:
    """Ticks a carrier spends covering this distance.

    helper.getTicksByDistance - editor helper.ts
    """
    return math.ceil(distance / (carrier_speed * tick_distance_modifier))


# A traversed wormhole always costs exactly one tick, whatever the distance.
# helper.getTicksBetweenObjects - editor helper.ts
WORMHOLE_TICKS = 1


# --------------------------------------------------------------------------
# Star economics
# --------------------------------------------------------------------------


def terraformed_resource(natural_resource: int, terraforming: int) -> int:
    """helper.calculateTerraformedResource - editor helper.ts"""
    if natural_resource == 0:
        return 0
    return math.floor(natural_resource + 5 * terraforming)


def is_dead_star(star: dict) -> bool:
    """A star whose three natural resources sum to zero.

    Solaris refuses a dead star that carries infrastructure, a specialist or a
    warp gate. helper.isDeadStar - editor helper.ts
    """
    nr = star.get("naturalResources") or {}
    return (nr.get("economy", 0) + nr.get("industry", 0) + nr.get("science", 0)) == 0


def effective_scanning(base_scanning: int, star: dict,
                       specialist_scanning: int = 0) -> int:
    """Scanning level a star actually has, terrain and specialist included.

    A dead star scans nothing at all; otherwise a black hole is worth +3 and the
    specialist's own modifier stacks on top, floored at 1.
    helper.getEffectiveTechs - editor helper.ts
    """
    if is_dead_star(star):
        return 0
    bonus = BLACK_HOLE_SCANNING_BONUS if star.get("isBlackHole") else 0
    return max(base_scanning + specialist_scanning + bonus, 1)


# --------------------------------------------------------------------------
# Hard limits enforced by Solaris's validator
#
# common/src/validation/customGalaxy.ts in the solaris-games/solaris repo.
# A map that breaks any of these is rejected outright at Create Game time.
# --------------------------------------------------------------------------

MAX_STARS = 1500
MIN_STARS = 1
MIN_PLAYERS = 2                     # advanced mode only; players[] is optional in basic mode
MAX_PLAYERS = 64
MAX_CARRIERS = 500

MAX_NATURAL_RESOURCES = 2000        # per channel
MAX_INFRASTRUCTURE = 200            # per channel
MAX_SHIPS_ACTUAL = 200000
MAX_CREDITS = 200000
MAX_CREDITS_SPECIALISTS = 200000
MAX_TECHNOLOGY_LEVEL = 200

MIN_CARRIER_SHIPS = 1               # 0 is rejected
MAX_CARRIER_SHIPS = 20000

MIN_STAR_NAME = 3                   # the editor allows shorter; Solaris does not
MAX_STAR_NAME = 30
MIN_NAME = 1                        # player alias, carrier name, team name
MAX_NAME = 30

TECHNOLOGIES = ("scanning", "hyperspace", "terraforming", "experimentation",
                "weapons", "banking", "manufacturing", "specialists")
RESOURCE_CHANNELS = ("economy", "industry", "science")


def max_stars_per_player(player_count: int) -> int:
    """Largest starsPerPlayer that keeps the galaxy inside the 1500-star cap.

    Solaris derives starsPerPlayer as starCount / playerLimit, and playerLimit
    is the number of home stars on the map, so this is a design constraint
    rather than a validation one: 36 players allows 41 stars each (1476), and
    42 each would be 1512 and rejected.
    """
    return MAX_STARS // player_count
