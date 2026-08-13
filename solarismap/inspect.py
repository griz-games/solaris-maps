"""Measure a finished map: is this the map that was intended?

`validate` answers a different question - will Solaris load this file. A map can
pass validation and still be unplayable: one player boxed in, another handed a
third more resources, half the galaxy unreachable until somebody researches
hyperspace 5. This module answers that second question in numbers.

Nothing here decides what is good. It reports; the person or agent reading the
report decides whether the spread is deliberate.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Any

from . import geometry, model, rules, specialists

# Which starting hyperspace level to measure reach at, when the map does not say.
DEFAULT_HYPERSPACE = 1


def _star_technologies(data: dict, player_id: str | None) -> dict:
    for player in data.get("players") or []:
        if player.get("id") == player_id:
            return player.get("technologies") or {}
    return {}


def _starting_hyperspace(data: dict) -> int:
    """The hyperspace level the players actually start on, if the map says so."""
    levels = [(p.get("technologies") or {}).get("hyperspace")
              for p in (data.get("players") or [])]
    levels = [lv for lv in levels if isinstance(lv, int)]
    return min(levels) if levels else DEFAULT_HYPERSPACE


def _spread(values: list[float]) -> dict:
    """Min, max and the gap between them - where asymmetry shows up."""
    if not values:
        return {"min": 0, "max": 0, "mean": 0, "spread": 0, "spread_pct": 0.0}
    low, high, mean = min(values), max(values), statistics.mean(values)
    return {
        "min": low,
        "max": high,
        "mean": round(mean, 2),
        "spread": round(high - low, 2),
        "spread_pct": round((high - low) / mean * 100, 2) if mean else 0.0,
    }


# --------------------------------------------------------------------------
# The sections
# --------------------------------------------------------------------------


def counts(data: dict) -> dict:
    stars = data["stars"]
    return {
        "stars": len(stars),
        "players": model.player_count(data),
        "carriers": len(data.get("carriers") or []),
        "teams": len(data.get("teams") or []),
        "stars_per_player": round(model.stars_per_player(data), 4),
        "split_resources": model.split_resources(data),
        "star_cap_headroom": rules.MAX_STARS - len(stars),
    }


def players(data: dict) -> dict:
    """Per player: what they start with, and how far apart the players are."""
    stars = data["stars"]
    owned: dict[str, list[dict]] = {}
    for star in stars:
        if star.get("playerId") is not None:
            owned.setdefault(star["playerId"], []).append(star)

    rows = []
    for player in data.get("players") or []:
        pid = player.get("id")
        mine = owned.get(pid, [])
        nr = {channel: sum((s.get("naturalResources") or {}).get(channel, 0) for s in mine)
              for channel in rules.RESOURCE_CHANNELS}
        infra = {channel: sum((s.get("infrastructure") or {}).get(channel, 0) for s in mine)
                 for channel in rules.RESOURCE_CHANNELS}
        capital = next((s for s in mine if s.get("homeStar")), None)
        rows.append({
            "id": pid,
            "stars": len(mine),
            "ships": sum(s.get("shipsActual") or 0 for s in mine),
            "natural_resources": nr,
            "natural_resources_total": sum(nr.values()),
            "infrastructure": infra,
            "capital": capital["id"] if capital else None,
            "capital_resources": (sum((capital.get("naturalResources") or {}).values())
                                  if capital else 0),
        })

    return {
        "each": rows,
        "spread": {
            "stars": _spread([r["stars"] for r in rows]),
            "ships": _spread([r["ships"] for r in rows]),
            "natural_resources": _spread([r["natural_resources_total"] for r in rows]),
        },
    }


def spacing(data: dict) -> dict:
    """How tightly packed the galaxy is, against the editor's minimum."""
    points = [geometry.star_point(s) for s in data["stars"]]
    if len(points) < 2:
        return {"minimum": 0, "median": 0, "maximum": 0, "below_floor": 0}
    gaps = geometry.nearest_neighbour_gaps(points)
    return {
        "minimum": round(min(gaps), 2),
        "median": round(statistics.median(gaps), 2),
        "maximum": round(max(gaps), 2),
        "floor": rules.MIN_STAR_SEPARATION,
        "below_floor": sum(1 for g in gaps if g < rules.MIN_STAR_SEPARATION),
    }


def connectivity(data: dict, hyperspace: int) -> dict:
    """What a player can actually get to, starting from their own stars.

    Measured per player from everything they own, at one hyperspace level, with
    wormholes costing a tick. A star nobody can reach is worth knowing about; so
    is one only a single player can reach.
    """
    stars = data["stars"]
    reach = rules.hyperspace_range(hyperspace)

    owned: dict[str, list[dict]] = {}
    for star in stars:
        if star.get("playerId") is not None:
            owned.setdefault(star["playerId"], []).append(star)

    reachable_by: Counter = Counter()
    rows = []
    for pid, mine in sorted(owned.items()):
        ticks = geometry.connected_hops(stars, mine, reach)
        reached = [sid for sid, cost in ticks.items() if not math.isinf(cost)]
        for sid in reached:
            reachable_by[sid] += 1
        neutral = [(cost, sid) for sid, cost in ticks.items()
                   if not math.isinf(cost) and cost > 0
                   and next(s for s in stars if s["id"] == sid).get("playerId") is None]
        rows.append({
            "id": pid,
            "reachable": len(reached),
            "unreachable": len(stars) - len(reached),
            "ticks_to_nearest_neutral": min(neutral)[0] if neutral else None,
        })

    unreachable_by_all = [s["id"] for s in stars if reachable_by[s["id"]] == 0]
    contested = sum(1 for s in stars if reachable_by[s["id"]] > 1)

    return {
        "hyperspace": hyperspace,
        "reach": reach,
        "each": rows,
        "spread": _spread([r["reachable"] for r in rows]),
        "unreachable_by_anyone": unreachable_by_all,
        "contested_stars": contested,
    }


def scanning(data: dict) -> dict:
    """What each capital can see on turn one."""
    stars = data["stars"]
    rows = []
    for star in stars:
        if not star.get("homeStar"):
            continue
        level = _star_technologies(data, star.get("playerId")).get("scanning", 1)
        bonus = specialists.scanning_bonus(star.get("specialistId"))
        visible = geometry.scanned_by(star, stars, level, bonus)
        rows.append({
            "star": star["id"],
            "player": star.get("playerId"),
            "level": rules.effective_scanning(level, star, bonus),
            "sees": len(visible),
            "sees_enemy_stars": sum(1 for s in visible
                                    if s.get("playerId") not in (None, star.get("playerId"))),
        })
    return {"capitals": rows, "spread": _spread([r["sees"] for r in rows])}


def terrain(data: dict) -> dict:
    flags = ("isNebula", "isAsteroidField", "isBinaryStar", "isBlackHole",
             "isPulsar", "warpGate")
    census = {flag: sum(1 for s in data["stars"] if s.get(flag)) for flag in flags}
    census["deadStars"] = sum(1 for s in data["stars"] if rules.is_dead_star(s))
    census["withSpecialist"] = sum(1 for s in data["stars"]
                                   if s.get("specialistId") is not None)
    return census


def wormholes(data: dict) -> dict:
    stars = data["stars"]
    by_id = {s["id"]: s for s in stars}
    linked = [s for s in stars if s.get("wormHoleToStarId") is not None]
    one_way = [s["id"] for s in linked
               if by_id.get(s["wormHoleToStarId"], {}).get("wormHoleToStarId") != s["id"]]
    pairs = {frozenset((s["id"], s["wormHoleToStarId"])) for s in linked
             if s["id"] not in one_way}
    return {
        "stars_with_wormholes": len(linked),
        "pairs": len(pairs),
        "one_way": one_way,
        "owned_at_start": sum(1 for s in linked if s.get("playerId") is not None),
    }


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def report(data: dict, hyperspace: int | None = None) -> dict:
    level = hyperspace if hyperspace is not None else _starting_hyperspace(data)
    return {
        "counts": counts(data),
        "players": players(data),
        "spacing": spacing(data),
        "connectivity": connectivity(data, level),
        "scanning": scanning(data),
        "terrain": terrain(data),
        "wormholes": wormholes(data),
    }


def _bar(label: str, value: Any) -> str:
    return f"  {label:<22} {value}"


def format_report(result: dict) -> str:
    """The human-readable version. --json gives the structure above instead."""
    out: list[str] = []
    c = result["counts"]
    out.append("counts")
    out.append(_bar("stars", f"{c['stars']}  ({c['star_cap_headroom']} below the "
                             f"{rules.MAX_STARS} cap)"))
    out.append(_bar("players", f"{c['players']}  ({c['stars_per_player']} stars each)"))
    out.append(_bar("carriers", c["carriers"]))
    out.append(_bar("splitResources", str(c["split_resources"]).lower()))

    p = result["players"]
    out.append("")
    out.append("per player")
    for key, unit in (("stars", ""), ("ships", ""), ("natural_resources", "")):
        s = p["spread"][key]
        out.append(_bar(key, f"min {s['min']}  max {s['max']}  mean {s['mean']}  "
                             f"spread {s['spread']} ({s['spread_pct']}%){unit}"))
    if p["spread"]["natural_resources"]["spread_pct"] > 5:
        out.append(_bar("", "^ resources differ by more than 5% between players"))

    s = result["spacing"]
    out.append("")
    out.append("spacing")
    out.append(_bar("nearest neighbour", f"min {s['minimum']}u  median {s['median']}u  "
                                         f"max {s['maximum']}u"))
    out.append(_bar("below the floor", f"{s['below_floor']} pair(s) closer than {s['floor']}u"))

    con = result["connectivity"]
    out.append("")
    out.append(f"connectivity at hyperspace {con['hyperspace']} ({con['reach']:.0f}u)")
    out.append(_bar("reachable per player", f"min {con['spread']['min']}  "
                                            f"max {con['spread']['max']}  "
                                            f"spread {con['spread']['spread']}"))
    out.append(_bar("contested stars", f"{con['contested_stars']} reachable by more "
                                       f"than one player"))
    marooned = con["unreachable_by_anyone"]
    out.append(_bar("unreachable by anyone", f"{len(marooned)}"
                    + (f"  {marooned[:8]}{' ...' if len(marooned) > 8 else ''}"
                       if marooned else "")))

    sc = result["scanning"]
    out.append("")
    out.append("scanning from capitals")
    out.append(_bar("stars seen", f"min {sc['spread']['min']}  max {sc['spread']['max']}  "
                                  f"mean {sc['spread']['mean']}"))
    enemies = sum(r["sees_enemy_stars"] for r in sc["capitals"])
    out.append(_bar("enemy stars visible", f"{enemies} across all capitals"))

    out.append("")
    out.append("terrain")
    out.append(_bar("", "  ".join(f"{k}: {v}" for k, v in result["terrain"].items() if v)))

    w = result["wormholes"]
    out.append("")
    out.append("wormholes")
    out.append(_bar("pairs", f"{w['pairs']}  ({w['stars_with_wormholes']} stars, "
                             f"{w['owned_at_start']} owned at start)"))
    if w["one_way"]:
        out.append(_bar("one-way", f"{w['one_way']}  <- the editor rejects these on import"))

    return "\n".join(out)
