"""Command line for the toolkit: `python -m solarismap <command>`.

    validate <map.json>      will Solaris load this? exit 1 if not
    inspect  <map.json>      is this the map you meant? numbers, not opinions
    metrics  <map.json>      fairness, compactness and novelty statistics
    render   <map.json>      draw it to SVG with the game's own art
    rules                    the constants, formulas and limits, --json for machines
    sync-specialists <path>  regenerate the specialist table from an editor checkout

Standard library only, so it runs anywhere Python does.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import inspect as inspect_module
from . import metrics as metrics_module
from . import model, render, rules, specialists, validate


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"no such file: {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} is not valid JSON: {exc}")
    if not isinstance(data, dict) or "stars" not in data:
        raise SystemExit(f"{path} does not look like a custom galaxy: no `stars` array")
    return data


# --------------------------------------------------------------------------
# validate
# --------------------------------------------------------------------------


def cmd_validate(args) -> int:
    data = _load(args.path)
    report = validate.validate(data, advanced=not args.basic)

    for line in report.errors:
        print(f"ERROR    {line}")
    if not args.quiet:
        for line in report.warnings:
            print(f"warning  {line}")

    print()
    print(f"{args.path.name}: {len(data['stars'])} stars, "
          f"{len(data.get('players') or [])} players, "
          f"{len(data.get('carriers') or [])} carriers")
    for line in validate.describe_derived_settings(data):
        print("  " + line)
    print()
    print(f"{'VALID' if report.ok else 'INVALID'} "
          f"({len(report.errors)} error(s), {len(report.warnings)} warning(s))")
    return 0 if report.ok else 1


# --------------------------------------------------------------------------
# inspect
# --------------------------------------------------------------------------


def cmd_inspect(args) -> int:
    data = _load(args.path)
    result = inspect_module.report(data, hyperspace=args.hyperspace)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{args.path.name}")
        print(inspect_module.format_report(result))
    return 0


# --------------------------------------------------------------------------
# metrics
# --------------------------------------------------------------------------


def cmd_metrics(args) -> int:
    data = _load(args.path)
    result = metrics_module.summary(data, hyperspace=args.hyperspace,
                                    scanning=args.scanning)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{args.path.name}")
        print(metrics_module.format_summary(result))
    return 0


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------


def cmd_render(args) -> int:
    data = _load(args.path)
    focus = None
    if args.focus:
        try:
            fx, fy, radius = (float(v) for v in args.focus.split(","))
            focus = (fx, fy, radius)
        except ValueError:
            raise SystemExit("--focus wants x,y,radius, e.g. --focus 1231,0,600")

    options = render.Options(
        labels=args.labels,
        resources=not args.no_resources,
        ships=not args.no_ships,
        scan_circles=args.scan,
        hyperspace_circles=args.hyperspace_circles,
        wormhole_links=not args.no_wormholes,
        margin=args.margin,
        focus=focus,
    )
    svg = render.draw(data, options)
    _, drawn = render.frame(data, options)

    out = args.output or args.path.with_suffix(".svg")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    scope = (f"{len(drawn)} of {len(data['stars'])} stars" if focus
             else f"{len(data['stars'])} stars")
    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB, {scope})")
    return 0


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------


def rules_document() -> dict:
    """Everything a map builder has to obey, in one structure."""
    return {
        "scale": {
            "lightYear": rules.LIGHT_YEAR,
            "minStarSeparation": rules.MIN_STAR_SEPARATION,
            "baseCarrierSpeed": rules.BASE_CARRIER_SPEED,
            "blackHoleScanningBonus": rules.BLACK_HOLE_SCANNING_BONUS,
            "wormholeTicks": rules.WORMHOLE_TICKS,
        },
        "formulas": {
            "hyperspaceRange": "(level + 1.5) * 50   world units a carrier jumps",
            "hyperspaceLevel": "ceil(distance / 50 - 1.5), floored at 1 when it computes to 0",
            "scanningRange": "(level + 1) * 50   world units a star sees",
            "scanningLevel": "ceil(distance / 50 - 1), floored at 1 when it computes to 0",
            "ticksByDistance": "ceil(distance / (carrierSpeed * tickModifier))",
            "terraformedResource": "0 if natural is 0, else floor(natural + 5 * terraforming)",
            "effectiveScanning": "0 if dead, else max(base + specialist + blackHole, 1)",
        },
        "limits": {
            "stars": [rules.MIN_STARS, rules.MAX_STARS],
            "players": [rules.MIN_PLAYERS, rules.MAX_PLAYERS],
            "carriers": [0, rules.MAX_CARRIERS],
            "naturalResourcesPerChannel": [0, rules.MAX_NATURAL_RESOURCES],
            "infrastructurePerChannel": [0, rules.MAX_INFRASTRUCTURE],
            "shipsActual": [0, rules.MAX_SHIPS_ACTUAL],
            "credits": [0, rules.MAX_CREDITS],
            "creditsSpecialists": [0, rules.MAX_CREDITS_SPECIALISTS],
            "technologyLevel": [0, rules.MAX_TECHNOLOGY_LEVEL],
            "carrierShips": [rules.MIN_CARRIER_SHIPS, rules.MAX_CARRIER_SHIPS],
            "starNameLength": [rules.MIN_STAR_NAME, rules.MAX_STAR_NAME],
            "otherNameLength": [rules.MIN_NAME, rules.MAX_NAME],
        },
        "fields": {
            "technologies": list(rules.TECHNOLOGIES),
            "resourceChannels": list(rules.RESOURCE_CHANNELS),
        },
        "semantics": [
            "playerLimit is the number of stars with homeStar: true, not a setting",
            "starsPerPlayer is starCount / playerLimit",
            "home stars must have a playerId",
            "unowned stars must have 0 ships",
            "a dead star (resources summing to 0) may not have infrastructure, "
            "a specialist or a warp gate",
            "a specialist must be flagged active.custom",
            "wormHoleToStarId must exist and may not be the star itself; Solaris does "
            "not require reciprocity but the editor does",
            "splitResources turns on automatically if any star has unequal channels",
            "all random terrain settings are forced to 0",
            "carrier waypoints are truncated outside tutorial games",
        ],
        "starsPerPlayerCap": {
            str(count): rules.max_stars_per_player(count)
            for count in (2, 4, 8, 12, 16, 24, 32, 36, 48, 64)
        },
        "specialists": {
            "star": [
                {"id": s["id"], "name": s["name"], "key": s["key"],
                 "custom": s["active"]["custom"],
                 "modifiers": s.get("modifiers", {})}
                for s in specialists.star_specialists(custom_only=False)
            ],
            "carrier": [
                {"id": s["id"], "name": s["name"], "key": s["key"],
                 "custom": s["active"]["custom"]}
                for s in specialists.carrier_specialists(custom_only=False)
            ],
        },
    }


def cmd_rules(args) -> int:
    document = rules_document()
    if args.json:
        print(json.dumps(document, indent=2))
        return 0

    print("scale")
    for key, value in document["scale"].items():
        print(f"  {key:<26} {value}")
    print("\nformulas")
    for key, value in document["formulas"].items():
        print(f"  {key:<26} {value}")
    print("\nhard limits (Solaris rejects anything outside these)")
    for key, (low, high) in document["limits"].items():
        print(f"  {key:<26} {low}..{high}")
    print("\nsemantics")
    for line in document["semantics"]:
        print(f"  - {line}")
    print("\nmax stars per player, to stay inside the 1500 cap")
    print("  " + "  ".join(f"{k}p: {v}" for k, v in document["starsPerPlayerCap"].items()))
    star_custom = sum(1 for s in document["specialists"]["star"] if s["custom"])
    carrier_custom = sum(1 for s in document["specialists"]["carrier"] if s["custom"])
    print(f"\nspecialists  {star_custom} star and {carrier_custom} carrier specialists "
          f"usable in a custom galaxy")
    print("  run with --json for the full table, ids and modifiers included")
    return 0


# --------------------------------------------------------------------------
# sync-specialists
# --------------------------------------------------------------------------


def cmd_sync_specialists(args) -> int:
    from . import sync_specialists
    return sync_specialists.sync(args.source)


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m solarismap",
        description="Build, check and draw Solaris custom galaxies.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="will Solaris load this map?")
    p.add_argument("path", type=Path)
    p.add_argument("--basic", action="store_true",
                   help="validate for basic mode, where only `stars` is read")
    p.add_argument("--quiet", action="store_true", help="errors only, no warnings")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("inspect", help="geometry and balance report")
    p.add_argument("path", type=Path)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--hyperspace", type=int, default=None,
                   help="level to measure reach at (default: the players' own)")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("metrics",
                       help="fairness, compactness and novelty statistics")
    p.add_argument("path", type=Path)
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.add_argument("--hyperspace", type=int, default=None,
                   help="level to measure travel at (default: the players' own)")
    p.add_argument("--scanning", type=int, default=None,
                   help="level to measure vision at (default: the players' own)")
    p.set_defaults(func=cmd_metrics)

    p = sub.add_parser("render", help="draw the map to SVG")
    p.add_argument("path", type=Path)
    p.add_argument("-o", "--output", type=Path, default=None)
    p.add_argument("--labels", action="store_true", help="print star ids")
    p.add_argument("--no-resources", action="store_true")
    p.add_argument("--no-ships", action="store_true")
    p.add_argument("--no-wormholes", action="store_true", help="omit wormhole links")
    p.add_argument("--scan", action="store_true", help="draw scanning ranges")
    p.add_argument("--hyperspace-circles", action="store_true",
                   help="draw each owned star's jump range")
    p.add_argument("--focus", default=None, metavar="X,Y,R",
                   help="crop to a circle, e.g. --focus 1231,0,600")
    p.add_argument("--margin", type=float, default=120.0)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("rules", help="the constants, formulas and limits")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("sync-specialists",
                       help="regenerate specialists.json from an editor checkout")
    p.add_argument("source", type=Path,
                   help="path to src/stores/specialists.ts in a clone of "
                        "IHateAttackMaps/solaris-custom-galaxy-editor")
    p.set_defaults(func=cmd_sync_specialists)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
