"""Builders for the objects a custom galaxy is made of.

The factories here emit every field Solaris requires and nothing it rejects, so
a map assembled out of them is structurally valid before a single rule is
checked. Scratch fields are allowed - anything whose key starts with `_` is
working state for the builder and is stripped on the way out - which lets a
builder carry roles, symmetry classes and radii on the star itself instead of
in a parallel dict.

Field reference: common/src/types/common/customGalaxy.ts in solaris-games/solaris.
Every star field is required and non-defaulting except shipsActual,
isKingOfTheHillStar and name. All ids are strings.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from . import rules

Point = tuple[float, float]


# --------------------------------------------------------------------------
# Stars
# --------------------------------------------------------------------------


def new_star(pos: Point, **overrides: Any) -> dict:
    """A neutral, empty star at `pos`.

    `id` and `naturalResources` are left None deliberately: a builder normally
    assigns ids once the galaxy is complete (see `assign_ids`) and resources
    once its curve is solved. `finish` fills in anything still missing.
    """
    star = {
        "id": None,
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
        "naturalResources": None,
        "shipsActual": 0,
        "ships": 0,
        "infrastructure": {"economy": 0, "industry": 0, "science": 0},
        # Distance from the origin, quantised. Rotating a position by an exact
        # number of degrees perturbs the radius by ~1e-13; if a resource curve
        # rounds on radius, two stars meant to be mirror images can land either
        # side of a rounding boundary and come out one resource apart. Snapping
        # here keeps a radius class exact.
        "_radius": round(math.hypot(*pos), 6),
    }
    star.update(overrides)
    return star


def set_resources(star: dict, economy: int, industry: int | None = None,
                  science: int | None = None) -> dict:
    """Set a star's natural resources; one value sets all three."""
    star["naturalResources"] = {
        "economy": economy,
        "industry": economy if industry is None else industry,
        "science": economy if science is None else science,
    }
    return star


def set_infrastructure(star: dict, economy: int = 0, industry: int = 0,
                       science: int = 0) -> dict:
    star["infrastructure"] = {"economy": economy, "industry": industry, "science": science}
    return star


def set_ships(star: dict, ships: float) -> dict:
    """Set both ship counts at once.

    `shipsActual` is the authoritative float and `ships` the floored display
    value; the editor requires them to agree, and an unowned star must have both
    at zero.
    """
    star["shipsActual"] = ships
    star["ships"] = math.floor(ships)
    return star


def make_home_star(star: dict, player_id: str, ships: float = 0,
                   economy: int = 0, industry: int = 0, science: int = 0) -> dict:
    """Turn a star into a player's capital.

    Solaris requires a home star to carry a playerId, and requires the player
    claiming it via homeStarId to be that same player.
    """
    star["homeStar"] = True
    star["playerId"] = player_id
    set_infrastructure(star, economy, industry, science)
    set_ships(star, ships)
    return star


def link_wormhole(a: dict, b: dict) -> None:
    """Join two stars with a wormhole.

    Solaris only requires the target to exist, but the editor requires the pair
    to be reciprocal, so always link both ends - otherwise the map is valid in
    the game and rejected on import into the viewer.
    """
    if a["id"] is None or b["id"] is None:
        raise ValueError("assign ids before linking wormholes")
    if a["id"] == b["id"]:
        raise ValueError(f"star {a['id']} cannot wormhole to itself")
    a["wormHoleToStarId"] = b["id"]
    b["wormHoleToStarId"] = a["id"]


# --------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------

DEFAULT_TECHNOLOGIES = {
    "scanning": 1,
    "hyperspace": 1,
    "terraforming": 1,
    "experimentation": 1,
    "weapons": 1,
    "banking": 1,
    "manufacturing": 1,
    "specialists": 1,
}


def new_player(player_id: str, home_star_id: str, technologies: dict | None = None,
               credits: int = 500, credits_specialists: int = 5,
               colour: dict | None = None, shape: str | None = None,
               **overrides: Any) -> dict:
    """A player owning `home_star_id`.

    `colour` and `shape` are cosmetic: Solaris discards both and reassigns via
    its own playerColourService. They are emitted anyway because the editor uses
    them to draw the map you are checking, and they sit where the editor puts
    them so a round trip through the editor does not reshuffle the file.
    """
    player: dict[str, Any] = {"id": player_id, "homeStarId": home_star_id}
    if colour is not None:
        player["colour"] = colour
    if shape is not None:
        player["shape"] = shape
    player["technologies"] = dict(technologies or DEFAULT_TECHNOLOGIES)
    player["credits"] = credits
    player["creditsSpecialists"] = credits_specialists
    player.update(overrides)
    return player


def new_carrier(carrier_id: str, player_id: str, orbiting_star_id: str,
                ships: int = 1, **overrides: Any) -> dict:
    """A carrier parked at a star.

    Ships must be at least 1 - Solaris rejects a carrier with none. Waypoints
    are pointless on a starting map: outside tutorial games Solaris truncates
    an orbiting carrier's waypoints to zero and forces waypointsLooped false.
    """
    carrier = {
        "id": carrier_id,
        "playerId": player_id,
        "orbiting": orbiting_star_id,
        "waypoints": [],
        "waypointsLooped": False,
        "ships": ships,
        "specialistId": None,
        "specialistExpireTick": None,
        "isGift": False,
        "progress": None,
    }
    carrier.update(overrides)
    return carrier


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------


def assign_ids(stars: list[dict], start: int = 1) -> list[dict]:
    """Number stars 1..N in list order. Ids are strings in Solaris."""
    for n, star in enumerate(stars, start=start):
        star["id"] = str(n)
    return stars


def strip_scratch(obj: dict) -> dict:
    """Drop the builder's own `_`-prefixed working fields."""
    return {k: v for k, v in obj.items() if not k.startswith("_")}


def galaxy(stars: list[dict], players: list[dict] | None = None,
           carriers: list[dict] | None = None,
           teams: list[dict] | None = None) -> dict:
    """Assemble the top-level object, scratch fields stripped.

    Basic mode reads only `stars`; advanced mode requires `players` and honours
    `carriers` and `teams`.
    """
    out: dict[str, Any] = {"stars": [strip_scratch(s) for s in stars]}
    if players is not None:
        out["players"] = [strip_scratch(p) for p in players]
    out["carriers"] = [strip_scratch(c) for c in (carriers or [])]
    if teams is not None:
        out["teams"] = [strip_scratch(t) for t in teams]
    return out


def write(path: str | Path, data: dict, indent: int | None = None) -> Path:
    """Write a galaxy to disk.

    Defaults to no indentation: these files run to hundreds of kilobytes and
    are pasted into a web form, not read.
    """
    path = Path(path)
    # out/ is not tracked by git, so a fresh clone has no directory to write into.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=indent), encoding="utf-8")
    return path


def player_count(data: dict) -> int:
    """What Solaris will set playerLimit to: the number of home stars."""
    return sum(1 for s in data["stars"] if s.get("homeStar"))


def stars_per_player(data: dict) -> float:
    """What Solaris will derive as starsPerPlayer."""
    count = player_count(data)
    return len(data["stars"]) / count if count else 0.0


def split_resources(data: dict) -> bool:
    """Whether Solaris will auto-enable splitResources for this map.

    True as soon as any star has unequal economy/industry/science.
    """
    for star in data["stars"]:
        nr = star.get("naturalResources") or {}
        if len({nr.get(c) for c in rules.RESOURCE_CHANNELS}) > 1:
            return True
    return False
