"""Solaris-parity validation for a custom galaxy.

This is the check that decides whether a map is usable. It reimplements what
Solaris runs at Create Game time, so a map that passes here loads there:

  common/src/validation/customGalaxy.ts   field types and numeric ranges
  server/services/customGalaxy.ts         validateAndCompleteCustomGalaxy

Errors are things Solaris rejects. Warnings are things Solaris accepts but that
either break the editor's import - so you could not open the map in the viewer
to look at it - or that silently change the game's settings.

Deliberately NOT checked: anything about whether the map is a *good* map.
Reachability, balance and symmetry are the builder's business; this module only
answers "will Solaris take it".
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import rules, specialists


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def __str__(self) -> str:
        lines = [f"ERROR    {e}" for e in self.errors]
        lines += [f"warning  {w}" for w in self.warnings]
        if not lines:
            return "valid: no errors, no warnings"
        return "\n".join(lines)

    def raise_for_errors(self) -> None:
        """Abort the build if the map would be rejected."""
        if self.errors:
            raise ValueError("map is not valid for Solaris:\n" +
                             "\n".join(f"  - {e}" for e in self.errors))


# --------------------------------------------------------------------------
# Field-level helpers
# --------------------------------------------------------------------------


def _check_id(report: Report, value: Any, what: str) -> bool:
    if not isinstance(value, str) or len(value) < 1:
        report.error(f"{what}: id must be a non-empty string, got {value!r}")
        return False
    return True


def _check_int_range(report: Report, value: Any, low: int, high: int, what: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        report.error(f"{what}: expected a number, got {value!r}")
        return
    if value < low or value > high:
        report.error(f"{what}: {value} is outside {low}..{high}")


def _check_name(report: Report, value: Any, low: int, high: int, what: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        report.error(f"{what}: name must be a string, got {value!r}")
        return
    if not (low <= len(value) <= high):
        report.error(f"{what}: name {value!r} is {len(value)} characters, must be {low}..{high}")


# --------------------------------------------------------------------------
# Stars
# --------------------------------------------------------------------------

REQUIRED_STAR_FIELDS = (
    "id", "location", "playerId", "naturalResources", "specialistId",
    "specialistExpireTick", "homeStar", "warpGate", "isNebula", "isAsteroidField",
    "isBinaryStar", "isBlackHole", "isPulsar", "wormHoleToStarId", "infrastructure",
)


def _validate_stars(report: Report, stars: list[dict]) -> None:
    if not isinstance(stars, list):
        report.error("stars: must be an array")
        return
    if not (rules.MIN_STARS <= len(stars) <= rules.MAX_STARS):
        report.error(f"stars: {len(stars)} entries, must be "
                     f"{rules.MIN_STARS}..{rules.MAX_STARS}")

    seen: set[str] = set()
    for index, star in enumerate(stars):
        what = f"star {star.get('id', f'#{index}')!r}"

        missing = [f for f in REQUIRED_STAR_FIELDS if f not in star]
        if missing:
            report.error(f"{what}: missing required field(s) {', '.join(missing)}")
            continue

        if _check_id(report, star["id"], what):
            if star["id"] in seen:
                report.error(f"{what}: duplicate star id")
            seen.add(star["id"])

        location = star.get("location")
        if (not isinstance(location, dict)
                or not isinstance(location.get("x"), (int, float))
                or not isinstance(location.get("y"), (int, float))):
            report.error(f"{what}: location must be {{x, y}} numbers, got {location!r}")

        nr = star.get("naturalResources")
        if not isinstance(nr, dict):
            report.error(f"{what}: naturalResources must be an object, got {nr!r}")
        else:
            for channel in rules.RESOURCE_CHANNELS:
                if channel not in nr:
                    report.error(f"{what}: naturalResources.{channel} is required")
                else:
                    _check_int_range(report, nr[channel], 0, rules.MAX_NATURAL_RESOURCES,
                                     f"{what}: naturalResources.{channel}")

        infra = star.get("infrastructure")
        if not isinstance(infra, dict):
            report.error(f"{what}: infrastructure must be an object, got {infra!r}")
        else:
            for channel in rules.RESOURCE_CHANNELS:
                if channel not in infra:
                    report.error(f"{what}: infrastructure.{channel} is required")
                elif infra[channel] is None:
                    # The editor's type allows null per field; Solaris requires a number.
                    report.error(f"{what}: infrastructure.{channel} is null, "
                                 f"Solaris requires a number")
                else:
                    _check_int_range(report, infra[channel], 0, rules.MAX_INFRASTRUCTURE,
                                     f"{what}: infrastructure.{channel}")

        if "shipsActual" in star and star["shipsActual"] is not None:
            _check_int_range(report, star["shipsActual"], 0, rules.MAX_SHIPS_ACTUAL,
                             f"{what}: shipsActual")

        _check_name(report, star.get("name"), rules.MIN_STAR_NAME, rules.MAX_STAR_NAME, what)

        if star.get("playerId") is not None and not isinstance(star["playerId"], str):
            report.error(f"{what}: playerId must be a string or null")

        specialist_id = star.get("specialistId")
        if specialist_id is not None:
            if not specialists.is_custom_star_specialist(specialist_id):
                known = specialists.star_specialist(specialist_id)
                reason = ("is not flagged active.custom" if known
                          else "is not a star specialist")
                report.error(f"{what}: specialistId {specialist_id} {reason}")

        # --- semantic rules Solaris always enforces ---
        if star.get("homeStar") and star.get("playerId") is None:
            report.error(f"{what}: home star must have a playerId")

        ships = star.get("shipsActual") or 0
        if star.get("playerId") is None and ships:
            report.error(f"{what}: unowned star must have 0 ships, has {ships}")

        if rules.is_dead_star(star):
            if any((infra or {}).get(c) for c in rules.RESOURCE_CHANNELS):
                report.error(f"{what}: dead star (0 natural resources) cannot have "
                             f"infrastructure")
            if star.get("specialistId") is not None:
                report.error(f"{what}: dead star cannot have a specialist")
            if star.get("warpGate"):
                report.error(f"{what}: dead star cannot have a warp gate")

        # --- the editor's own extra field, if present, must agree ---
        if "ships" in star and star.get("ships") is not None:
            floored = int(star["shipsActual"] or 0)
            if star["ships"] != floored:
                report.warn(f"{what}: ships {star['ships']} does not match "
                            f"floor(shipsActual) {floored}; the editor keeps them in sync")

    _validate_wormholes(report, stars)


def _validate_wormholes(report: Report, stars: list[dict]) -> None:
    by_id = {s["id"]: s for s in stars if isinstance(s.get("id"), str)}
    for star in stars:
        target_id = star.get("wormHoleToStarId")
        if target_id is None:
            continue
        what = f"star {star.get('id')!r}"
        if target_id == star.get("id"):
            report.error(f"{what}: wormhole points at itself")
            continue
        target = by_id.get(target_id)
        if target is None:
            report.error(f"{what}: wormHoleToStarId {target_id!r} does not exist")
            continue
        if target.get("wormHoleToStarId") != star.get("id"):
            # Solaris does not require reciprocity; the editor does, so a
            # one-way wormhole makes the map unopenable in the viewer.
            report.warn(f"{what}: wormhole to {target_id!r} is one-way. Solaris accepts "
                        f"this, the editor rejects it on import")


# --------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------


def _validate_players(report: Report, players: list[dict], stars: list[dict]) -> None:
    if not isinstance(players, list):
        report.error("players: must be an array")
        return
    if not (rules.MIN_PLAYERS <= len(players) <= rules.MAX_PLAYERS):
        report.error(f"players: {len(players)} entries, must be "
                     f"{rules.MIN_PLAYERS}..{rules.MAX_PLAYERS} in advanced mode")

    by_star_id = {s["id"]: s for s in stars if isinstance(s.get("id"), str)}
    seen: set[str] = set()
    claimed: dict[str, str] = {}

    for index, player in enumerate(players):
        what = f"player {player.get('id', f'#{index}')!r}"

        if _check_id(report, player.get("id"), what):
            if player["id"] in seen:
                report.error(f"{what}: duplicate player id")
            seen.add(player["id"])

        _check_name(report, player.get("alias"), rules.MIN_NAME, rules.MAX_NAME, what)

        for money, cap in (("credits", rules.MAX_CREDITS),
                           ("creditsSpecialists", rules.MAX_CREDITS_SPECIALISTS)):
            if money in player and player[money] is not None:
                _check_int_range(report, player[money], 0, cap, f"{what}: {money}")

        technologies = player.get("technologies")
        if technologies is not None:
            if not isinstance(technologies, dict):
                report.error(f"{what}: technologies must be an object")
            else:
                for tech in rules.TECHNOLOGIES:
                    if tech in technologies:
                        _check_int_range(report, technologies[tech], 0,
                                         rules.MAX_TECHNOLOGY_LEVEL,
                                         f"{what}: technologies.{tech}")

        home_star_id = player.get("homeStarId")
        if home_star_id is None:
            report.error(f"{what}: homeStarId is required")
            continue
        home = by_star_id.get(home_star_id)
        if home is None:
            report.error(f"{what}: homeStarId {home_star_id!r} does not exist")
            continue
        if home_star_id in claimed:
            report.error(f"{what}: capital {home_star_id!r} is already claimed by "
                         f"player {claimed[home_star_id]!r}")
        claimed[home_star_id] = player.get("id")
        if not home.get("homeStar"):
            report.error(f"{what}: star {home_star_id!r} is named as a capital but is not "
                         f"flagged homeStar")
        if home.get("playerId") != player.get("id"):
            report.error(f"{what}: capital {home_star_id!r} is owned by "
                         f"{home.get('playerId')!r}, not by the player claiming it")

    player_ids = {p.get("id") for p in players}
    for star in stars:
        if star.get("playerId") is not None and star["playerId"] not in player_ids:
            report.error(f"star {star.get('id')!r}: playerId {star['playerId']!r} "
                         f"is not a player")


def _validate_home_star_coverage(report: Report, players: list[dict],
                                 stars: list[dict], has_carriers: bool) -> None:
    """With no carriers array Solaris demands exactly one home star per player."""
    if has_carriers:
        return
    homes: dict[str, int] = {}
    for star in stars:
        if star.get("homeStar") and star.get("playerId") is not None:
            homes[star["playerId"]] = homes.get(star["playerId"], 0) + 1
    for player in players:
        count = homes.get(player.get("id"), 0)
        if count != 1:
            report.error(f"player {player.get('id')!r}: has {count} home stars, "
                         f"must have exactly 1 when the map declares no carriers")
    owners = {s["playerId"] for s in stars if s.get("playerId") is not None}
    for owner in owners:
        if owner not in homes:
            report.error(f"player {owner!r}: owns stars but has no home star")


# --------------------------------------------------------------------------
# Carriers and teams
# --------------------------------------------------------------------------


def _validate_carriers(report: Report, carriers: list[dict], stars: list[dict],
                       players: list[dict] | None) -> None:
    if not isinstance(carriers, list):
        report.error("carriers: must be an array")
        return
    if len(carriers) > rules.MAX_CARRIERS:
        report.error(f"carriers: {len(carriers)} entries, maximum is {rules.MAX_CARRIERS}")

    star_ids = {s["id"] for s in stars if isinstance(s.get("id"), str)}
    player_ids = {p.get("id") for p in (players or [])}
    seen: set[str] = set()

    for index, carrier in enumerate(carriers):
        what = f"carrier {carrier.get('id', f'#{index}')!r}"

        if _check_id(report, carrier.get("id"), what):
            if carrier["id"] in seen:
                report.error(f"{what}: duplicate carrier id")
            seen.add(carrier["id"])

        _check_name(report, carrier.get("name"), rules.MIN_NAME, rules.MAX_NAME, what)

        ships = carrier.get("ships")
        if not isinstance(ships, int) or isinstance(ships, bool):
            report.error(f"{what}: ships must be an integer, got {ships!r}")
        else:
            _check_int_range(report, ships, rules.MIN_CARRIER_SHIPS,
                             rules.MAX_CARRIER_SHIPS, f"{what}: ships")

        if players is not None and carrier.get("playerId") not in player_ids:
            report.error(f"{what}: playerId {carrier.get('playerId')!r} is not a player")

        specialist_id = carrier.get("specialistId")
        if specialist_id is not None and not specialists.is_custom_carrier_specialist(specialist_id):
            report.error(f"{what}: specialistId {specialist_id} is not a carrier "
                         f"specialist flagged active.custom")

        orbiting = carrier.get("orbiting")
        waypoints = carrier.get("waypoints") or []
        if orbiting is not None:
            if orbiting not in star_ids:
                report.error(f"{what}: orbiting star {orbiting!r} does not exist")
        else:
            if not waypoints:
                report.error(f"{what}: in-flight carrier needs at least one waypoint")
            progress = carrier.get("progress")
            if progress is None:
                report.error(f"{what}: in-flight carrier needs a progress value")
            else:
                _check_int_range(report, progress, 0, 1, f"{what}: progress")
            if waypoints and waypoints[0].get("delayTicks") not in (0, None):
                report.error(f"{what}: in-flight carrier's first waypoint must have "
                             f"delayTicks 0")

        for i in range(1, len(waypoints)):
            if waypoints[i - 1].get("destination") != waypoints[i].get("source"):
                report.error(f"{what}: waypoint {i} does not continue from waypoint {i - 1}")

        for i, waypoint in enumerate(waypoints):
            for end in ("source", "destination"):
                if waypoint.get(end) not in star_ids:
                    report.error(f"{what}: waypoint {i} {end} {waypoint.get(end)!r} "
                                 f"is not a star")

        if waypoints:
            report.warn(f"{what}: has waypoints. Outside tutorial games Solaris truncates "
                        f"them to the first one in flight and to none in orbit")


def _validate_teams(report: Report, teams: list[dict], players: list[dict] | None) -> None:
    if not isinstance(teams, list):
        report.error("teams: must be an array")
        return

    seen: set[str] = set()
    assigned: dict[str, int] = {}
    for index, team in enumerate(teams):
        what = f"team {team.get('id', f'#{index}')!r}"
        if _check_id(report, team.get("id"), what):
            if team["id"] in seen:
                report.error(f"{what}: duplicate team id")
            seen.add(team["id"])
        _check_name(report, team.get("name"), rules.MIN_NAME, rules.MAX_NAME, what)
        for player_id in team.get("players") or []:
            assigned[player_id] = assigned.get(player_id, 0) + 1

    if players is None:
        return
    player_ids = {p.get("id") for p in players}
    for player_id, count in assigned.items():
        if player_id not in player_ids:
            report.error(f"teams: {player_id!r} is not a player")
        elif count > 1:
            report.error(f"teams: player {player_id!r} is in {count} teams, must be in one")
    for player_id in player_ids:
        if player_id not in assigned:
            report.error(f"teams: player {player_id!r} is not in any team")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def validate(data: dict, advanced: bool = True) -> Report:
    """Check a custom galaxy against Solaris's rules.

    `advanced` mirrors the Advanced Custom Galaxy game setting. With it off,
    Solaris reads only `stars` and ignores players, carriers and teams entirely,
    so those are not validated; with it on, `players` is required.
    """
    report = Report()

    if not isinstance(data, dict):
        report.error("top level must be an object with a `stars` array")
        return report
    if "stars" not in data:
        report.error("top level must have a `stars` array")
        return report

    stars = data["stars"]
    _validate_stars(report, stars)
    if not isinstance(stars, list):
        return report

    players = data.get("players")
    carriers = data.get("carriers")
    teams = data.get("teams")

    if not advanced:
        if players or carriers or teams:
            report.warn("players/carriers/teams are ignored unless the game is created "
                        "with Advanced Custom Galaxy enabled")
        return report

    if players is None:
        report.error("players: required in advanced mode (2..64 entries)")
    else:
        _validate_players(report, players, stars)
        _validate_home_star_coverage(report, players, stars, bool(carriers))

    if carriers is not None:
        _validate_carriers(report, carriers, stars, players)
    if teams is not None:
        _validate_teams(report, teams, players)

    return report


def describe_derived_settings(data: dict) -> list[str]:
    """What Solaris will override in the game settings, given this map.

    None of these are things a map author sets: Solaris computes them from the
    map and ignores whatever the Create Game form said.
    """
    from . import model

    count = model.player_count(data)
    lines = [
        f"playerLimit      {count}   (count of stars with homeStar: true)",
        f"starsPerPlayer   {model.stars_per_player(data):.4g}   "
        f"({len(data['stars'])} stars / {count} players)",
        f"splitResources   {str(model.split_resources(data)).lower()}   "
        f"(auto-on when any star has unequal economy/industry/science)",
        "randomWarpGates, randomWormHoles, randomNebulas, randomAsteroidFields,",
        "randomBinaryStars, randomBlackHoles, randomPulsars   all forced to 0",
    ]
    if data.get("teams"):
        lines.append(f"teamsCount       {len(data['teams'])}")
        if data.get("players"):
            lines.append(f"maxAlliances     {len(data['players']) - 1}")
    return lines


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate a Solaris custom galaxy JSON file.")
    parser.add_argument("path", type=Path, help="the map JSON")
    parser.add_argument("--basic", action="store_true",
                        help="validate for basic mode, where only `stars` is read")
    parser.add_argument("--quiet", action="store_true", help="suppress warnings")
    args = parser.parse_args(argv)

    data = json.loads(args.path.read_text(encoding="utf-8"))
    report = validate(data, advanced=not args.basic)

    for line in report.errors:
        print(f"ERROR    {line}")
    if not args.quiet:
        for line in report.warnings:
            print(f"warning  {line}")

    print()
    print(f"{args.path.name}: {len(data['stars'])} stars, "
          f"{len(data.get('players') or [])} players, "
          f"{len(data.get('carriers') or [])} carriers")
    for line in describe_derived_settings(data):
        print("  " + line)
    print()
    print(f"{'VALID' if report.ok else 'INVALID'} "
          f"({len(report.errors)} error(s), {len(report.warnings)} warning(s))")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
