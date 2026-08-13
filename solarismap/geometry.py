"""Plane geometry and graph queries a map builder needs.

Nothing here is Solaris-specific except `reachable_within`, `connected_hops`
and `travel_ticks`, which take a range in world units so the caller can pass
whatever `rules.hyperspace_range(level)` gives them.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Iterable, Sequence

from . import rules

Point = tuple[float, float]


# --------------------------------------------------------------------------
# Points
# --------------------------------------------------------------------------


def polar(r: float, degrees: float) -> Point:
    """Cartesian point r units from the origin at this bearing."""
    a = math.radians(degrees)
    return r * math.cos(a), r * math.sin(a)


def rotate(p: Point, degrees: float) -> Point:
    a = math.radians(degrees)
    ca, sa = math.cos(a), math.sin(a)
    return p[0] * ca - p[1] * sa, p[0] * sa + p[1] * ca


def translate(p: Point, by: Point) -> Point:
    return p[0] + by[0], p[1] + by[1]


def mirror(p: Point, about_degrees: float) -> Point:
    """Reflect a point across the line through the origin at this bearing.

    The workhorse of a symmetric map: reflect a player's whole pod across the
    midline between two wedges and neither player is nearer to anything on it.
    """
    a = math.radians(2.0 * about_degrees)
    ca, sa = math.cos(a), math.sin(a)
    return p[0] * ca + p[1] * sa, p[0] * sa - p[1] * ca


def dist(p: Point, q: Point) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def star_point(star: dict) -> Point:
    return star["location"]["x"], star["location"]["y"]


def bearing(p: Point, q: Point) -> float:
    """Bearing from p to q, in degrees."""
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0]))


# --------------------------------------------------------------------------
# Spacing
# --------------------------------------------------------------------------


def too_close(point: Point, others: Iterable[Point],
              separation: float = rules.MIN_STAR_SEPARATION) -> bool:
    """True if `point` crowds anything in `others`."""
    return any(dist(point, other) < separation for other in others)


def nearest_neighbour_gaps(points: Sequence[Point]) -> list[float]:
    """Distance from each point to its closest neighbour.

    Reported by a builder as a sanity check: a minimum below
    rules.MIN_STAR_SEPARATION means stars overlap on screen.
    """
    gaps = []
    for i, p in enumerate(points):
        best = math.inf
        for j, q in enumerate(points):
            if i == j:
                continue
            best = min(best, dist(p, q))
        gaps.append(best)
    return gaps


# --------------------------------------------------------------------------
# Travel
# --------------------------------------------------------------------------


def travel_ticks(distance: float, carrier_speed: float = rules.BASE_CARRIER_SPEED) -> int:
    """Ticks to cross a gap in one jump. rules.ticks_by_distance, spelled shorter."""
    return rules.ticks_by_distance(distance, carrier_speed)


def reachable_within(source: dict, stars: Iterable[dict], reach: float,
                     include_wormholes: bool = True) -> list[dict]:
    """Every star a carrier at `source` could jump to directly.

    A wormhole is always one hop regardless of distance, so a star linked by one
    is reachable at any hyperspace level.
    """
    here = star_point(source)
    out = []
    for star in stars:
        if star["id"] == source["id"]:
            continue
        if include_wormholes and source.get("wormHoleToStarId") == star["id"]:
            out.append(star)
        elif dist(here, star_point(star)) <= reach:
            out.append(star)
    return out


def connected_hops(stars: Sequence[dict], sources: Sequence[dict], reach: float,
                   carrier_speed: float = rules.BASE_CARRIER_SPEED) -> dict[str, float]:
    """Cheapest travel time in ticks from any of `sources` to every star.

    Dijkstra over jumps no longer than `reach`, with wormholes costing one tick.
    A star that comes back as `inf` cannot be reached at that hyperspace level -
    which is how you prove a map has no marooned pockets, and how you prove a
    deliberately isolated star really is isolated.
    """
    points = {s["id"]: star_point(s) for s in stars}
    best: dict[str, float] = {s["id"]: math.inf for s in stars}
    heap: list[tuple[float, str]] = []
    for source in sources:
        best[source["id"]] = 0.0
        heapq.heappush(heap, (0.0, source["id"]))

    by_id = {s["id"]: s for s in stars}
    while heap:
        cost, sid = heapq.heappop(heap)
        if cost > best[sid]:
            continue
        star = by_id[sid]
        for other in stars:
            if other["id"] == sid:
                continue
            if star.get("wormHoleToStarId") == other["id"]:
                step = float(rules.WORMHOLE_TICKS)
            else:
                gap = dist(points[sid], points[other["id"]])
                if gap > reach:
                    continue
                step = float(travel_ticks(gap, carrier_speed))
            total = cost + step
            if total < best[other["id"]]:
                best[other["id"]] = total
                heapq.heappush(heap, (total, other["id"]))
    return best


def scanned_by(star: dict, stars: Iterable[dict], scanning_level: int,
               specialist_scanning: int = 0) -> list[dict]:
    """Every star this one can see, terrain and specialist bonuses included."""
    effective = rules.effective_scanning(scanning_level, star, specialist_scanning)
    if effective <= 0:
        return []
    radius = rules.scanning_range(effective)
    here = star_point(star)
    return [s for s in stars
            if s["id"] != star["id"] and dist(here, star_point(s)) <= radius]
