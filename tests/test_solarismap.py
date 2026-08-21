#!/usr/bin/env python3
"""Self-check for the solarismap toolkit.

A validator that never rejects anything is worse than no validator, so this
takes a known-good map and breaks it one rule at a time, asserting that each
break is caught. Run it after touching rules.py or validate.py:

    python tests/test_solarismap.py

No test framework: plain asserts, exit status says whether it passed.
"""

import collections
import copy
import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from solarismap import (cli, geometry, inspect, metrics, model, render,  # noqa: E402
                        rules, specialists, validate)

ROOT = Path(__file__).resolve().parent.parent

passed = 0
failed: list[str] = []


def check(name: str, condition: bool) -> None:
    global passed
    if condition:
        passed += 1
    else:
        failed.append(name)


def rejects(name: str, data: dict, needle: str, advanced: bool = True) -> None:
    """The map must be rejected, with an error mentioning `needle`."""
    report = validate.validate(data, advanced=advanced)
    hit = any(needle.lower() in e.lower() for e in report.errors)
    check(name, hit)
    if not hit:
        failed[-1] += f"  (errors were: {report.errors[:3]})"


def warns(name: str, data: dict, needle: str) -> None:
    report = validate.validate(data)
    check(name, any(needle.lower() in w.lower() for w in report.warnings))


# --------------------------------------------------------------------------
# A minimal valid map, built through the model factories
# --------------------------------------------------------------------------


def base_map() -> dict:
    stars = []
    for wedge in range(2):
        capital = model.new_star(geometry.polar(400.0, wedge * 180.0))
        neighbour = model.new_star(geometry.polar(300.0, wedge * 180.0))
        stars += [capital, neighbour]
    model.assign_ids(stars)
    for star in stars:
        model.set_resources(star, 25)
    players = []
    for wedge in range(2):
        capital = stars[wedge * 2]
        model.make_home_star(capital, str(wedge + 1), ships=10, economy=5, industry=5, science=1)
        stars[wedge * 2 + 1]["playerId"] = str(wedge + 1)
        model.set_ships(stars[wedge * 2 + 1], 10)
        players.append(model.new_player(str(wedge + 1), capital["id"]))
    return model.galaxy(stars, players)


valid = base_map()
report = validate.validate(valid)
check("a map built from the factories is valid", report.ok)
if not report.ok:
    failed[-1] += f"  ({report.errors})"

# --------------------------------------------------------------------------
# Field limits
# --------------------------------------------------------------------------

m = copy.deepcopy(valid)
m["stars"][0]["naturalResources"]["economy"] = rules.MAX_NATURAL_RESOURCES + 1
rejects("natural resources over 2000", m, "outside 0..2000")

m = copy.deepcopy(valid)
m["stars"][0]["infrastructure"]["economy"] = rules.MAX_INFRASTRUCTURE + 1
rejects("infrastructure over 200", m, "outside 0..200")

m = copy.deepcopy(valid)
m["stars"][0]["infrastructure"]["economy"] = None
rejects("null infrastructure", m, "requires a number")

m = copy.deepcopy(valid)
m["stars"][0]["name"] = "AB"
rejects("star name under 3 characters", m, "must be 3..30")

m = copy.deepcopy(valid)
m["stars"][0]["shipsActual"] = rules.MAX_SHIPS_ACTUAL + 1
rejects("shipsActual over 200000", m, "outside 0..200000")

m = copy.deepcopy(valid)
m["players"][0]["credits"] = rules.MAX_CREDITS + 1
rejects("credits over 200000", m, "credits")

m = copy.deepcopy(valid)
m["players"][0]["technologies"]["weapons"] = rules.MAX_TECHNOLOGY_LEVEL + 1
rejects("technology over 200", m, "technologies.weapons")

m = copy.deepcopy(valid)
m["stars"] = [copy.deepcopy(m["stars"][0]) for _ in range(rules.MAX_STARS + 1)]
rejects("more than 1500 stars", m, "must be 1..1500")

m = copy.deepcopy(valid)
m["stars"][0]["id"] = 1          # a number, not a string
rejects("numeric star id", m, "non-empty string")

m = copy.deepcopy(valid)
del m["stars"][0]["isPulsar"]
rejects("missing required star field", m, "missing required field")

# --------------------------------------------------------------------------
# Semantic rules
# --------------------------------------------------------------------------

m = copy.deepcopy(valid)
m["stars"][1]["id"] = m["stars"][0]["id"]
rejects("duplicate star ids", m, "duplicate star id")

m = copy.deepcopy(valid)
m["stars"][0]["playerId"] = None
rejects("home star with no playerId", m, "home star must have a playerId")

m = copy.deepcopy(valid)
model.set_ships(m["stars"][0], 10)
m["stars"][0]["playerId"] = None
m["stars"][0]["homeStar"] = False
rejects("unowned star with ships", m, "unowned star must have 0 ships")

m = copy.deepcopy(valid)
model.set_infrastructure(m["stars"][1], economy=5)
model.set_resources(m["stars"][1], 0)
rejects("dead star with infrastructure", m, "dead star")

m = copy.deepcopy(valid)
model.set_resources(m["stars"][1], 0)
model.set_infrastructure(m["stars"][1])
m["stars"][1]["warpGate"] = True
rejects("dead star with a warp gate", m, "warp gate")

m = copy.deepcopy(valid)
model.set_resources(m["stars"][1], 0)
model.set_infrastructure(m["stars"][1])
m["stars"][1]["specialistId"] = 13
rejects("dead star with a specialist", m, "dead star cannot have a specialist")

m = copy.deepcopy(valid)
m["stars"][1]["wormHoleToStarId"] = m["stars"][1]["id"]
rejects("wormhole to itself", m, "points at itself")

m = copy.deepcopy(valid)
m["stars"][1]["wormHoleToStarId"] = "999"
rejects("wormhole to a missing star", m, "does not exist")

m = copy.deepcopy(valid)
m["stars"][1]["wormHoleToStarId"] = m["stars"][3]["id"]
warns("one-way wormhole warns", m, "one-way")

m = copy.deepcopy(valid)
m["stars"][1]["specialistId"] = 19       # War Hero: exists, but only as a carrier specialist
rejects("carrier specialist put on a star", m, "not a star specialist")

m = copy.deepcopy(valid)
m["stars"][1]["specialistId"] = 999
rejects("specialist that does not exist", m, "specialistId 999")

# --------------------------------------------------------------------------
# Players
# --------------------------------------------------------------------------

m = copy.deepcopy(valid)
m["players"][1]["id"] = m["players"][0]["id"]
rejects("duplicate player ids", m, "duplicate player id")

m = copy.deepcopy(valid)
m["players"][1]["homeStarId"] = m["players"][0]["homeStarId"]
rejects("two players sharing a capital", m, "already claimed")

m = copy.deepcopy(valid)
m["players"][0]["homeStarId"] = "999"
rejects("homeStarId that does not exist", m, "does not exist")

m = copy.deepcopy(valid)
m["stars"][0]["playerId"] = m["players"][1]["id"]
rejects("capital owned by the wrong player", m, "not by the player claiming it")

m = copy.deepcopy(valid)
m["stars"][1]["playerId"] = "nobody"
rejects("star owned by a non-player", m, "is not a player")

m = copy.deepcopy(valid)
m["players"] = m["players"][:1]
rejects("fewer than 2 players", m, "must be 2..64")

m = copy.deepcopy(valid)
del m["players"]
rejects("no players in advanced mode", m, "required in advanced mode")

m = copy.deepcopy(valid)
del m["players"]
check("no players is fine in basic mode", validate.validate(m, advanced=False).ok)

m = copy.deepcopy(valid)
m["stars"][1]["homeStar"] = True
rejects("a second home star for one player", m, "must have exactly 1")

# --------------------------------------------------------------------------
# Carriers
# --------------------------------------------------------------------------

m = copy.deepcopy(valid)
m["carriers"] = [model.new_carrier("1", "1", m["stars"][0]["id"], ships=0)]
rejects("carrier with 0 ships", m, "outside 1..20000")

m = copy.deepcopy(valid)
m["carriers"] = [model.new_carrier("1", "1", "999")]
rejects("carrier orbiting a missing star", m, "does not exist")

m = copy.deepcopy(valid)
m["carriers"] = [model.new_carrier("1", "nobody", m["stars"][0]["id"])]
rejects("carrier owned by a non-player", m, "is not a player")

m = copy.deepcopy(valid)
carrier = model.new_carrier("1", "1", m["stars"][0]["id"])
carrier["orbiting"] = None
m["carriers"] = [carrier]
rejects("in-flight carrier with no waypoints", m, "at least one waypoint")

m = copy.deepcopy(valid)
carrier = model.new_carrier("1", "1", m["stars"][0]["id"])
carrier["orbiting"] = None
carrier["progress"] = 0.5
carrier["waypoints"] = [
    {"source": m["stars"][0]["id"], "destination": m["stars"][1]["id"], "delayTicks": 0},
    {"source": m["stars"][3]["id"], "destination": m["stars"][2]["id"], "delayTicks": 0},
]
m["carriers"] = [carrier]
rejects("waypoints that do not chain", m, "does not continue")

m = copy.deepcopy(valid)
m["carriers"] = [model.new_carrier(str(n), "1", m["stars"][0]["id"])
                 for n in range(rules.MAX_CARRIERS + 1)]
rejects("more than 500 carriers", m, "maximum is 500")

# --------------------------------------------------------------------------
# Teams
# --------------------------------------------------------------------------

m = copy.deepcopy(valid)
m["teams"] = [{"id": "1", "name": "Alpha", "players": ["1"]}]
rejects("a player in no team", m, "not in any team")

m = copy.deepcopy(valid)
m["teams"] = [{"id": "1", "name": "Alpha", "players": ["1", "2"]},
              {"id": "2", "name": "Beta", "players": ["2"]}]
rejects("a player in two teams", m, "must be in one")

# --------------------------------------------------------------------------
# rules.py math, against the editor's implementations
# --------------------------------------------------------------------------

check("hyperspace range at level 1", rules.hyperspace_range(1) == 125.0)
check("hyperspace range at level 2", rules.hyperspace_range(2) == 175.0)
check("hyperspace level round-trips", all(
    rules.hyperspace_level(rules.hyperspace_range(level)) == level for level in range(1, 20)))
check("scanning range at level 1", rules.scanning_range(1) == 100.0)
check("scanning level round-trips", all(
    rules.scanning_level(rules.scanning_range(level)) == level for level in range(1, 20)))
# The editor floors a computed level of 0 to 1 (`|| 1`), and 75u is exactly that
# case: ceil(75/50 - 1.5) == 0. It does NOT floor negatives, and neither do we.
check("a level that computes to 0 becomes 1", rules.hyperspace_level(75) == 1)
check("terraforming adds 5 per level", rules.terraformed_resource(10, 3) == 25)
check("terraforming leaves a dead resource dead", rules.terraformed_resource(0, 5) == 0)
check("ticks round up", rules.ticks_by_distance(101, 10) == 11)
check("max stars per player at 36", rules.max_stars_per_player(36) == 41)
check("41 stars each fits, 42 does not",
      36 * 41 <= rules.MAX_STARS < 36 * 42)

dead = model.set_resources(model.new_star((0.0, 0.0)), 0)
check("dead star detected", rules.is_dead_star(dead))
check("a dead star scans nothing", rules.effective_scanning(5, dead) == 0)

black_hole = model.set_resources(model.new_star((0.0, 0.0)), 10)
black_hole["isBlackHole"] = True
check("black hole is worth +3 scanning", rules.effective_scanning(2, black_hole) == 5)
check("black hole plus Telescope Array is +6",
      rules.effective_scanning(2, black_hole, specialists.scanning_bonus(13)) == 8)

# --------------------------------------------------------------------------
# Specialists
# --------------------------------------------------------------------------

check("Telescope Array is star specialist 13", specialists.by_name("Telescope Array")["id"] == 13)
check("Telescope Array grants +3 scanning", specialists.scanning_bonus(13) == 3)
check("Joker is not usable in a custom galaxy",
      not specialists.is_custom_carrier_specialist(18))
check("every star specialist in the table is custom-active",
      all(s["active"]["custom"] for s in specialists.star_specialists()))

# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

check("polar at 0 degrees", geometry.polar(100, 0) == (100.0, 0.0))
check("mirroring twice is the identity",
      all(math.isclose(a, b, abs_tol=1e-9) for a, b in
          zip(geometry.mirror(geometry.mirror((37.0, 11.0), 45.0), 45.0), (37.0, 11.0))))
check("a point on the mirror axis does not move",
      all(math.isclose(a, b, abs_tol=1e-9) for a, b in
          zip(geometry.mirror((100.0, 0.0), 0.0), (100.0, 0.0))))
check("too_close respects the separation floor",
      geometry.too_close((0.0, 0.0), [(49.0, 0.0)]) and
      not geometry.too_close((0.0, 0.0), [(51.0, 0.0)]))

hop_stars = [model.new_star((0.0, 0.0)), model.new_star((100.0, 0.0)),
             model.new_star((5000.0, 0.0))]
model.assign_ids(hop_stars)
reach = geometry.connected_hops(hop_stars, [hop_stars[0]], rules.hyperspace_range(1))
check("a star in range is reachable", reach[hop_stars[1]["id"]] == 10)
check("a star out of range is not", math.isinf(reach[hop_stars[2]["id"]]))

model.link_wormhole(hop_stars[0], hop_stars[2])
reach = geometry.connected_hops(hop_stars, [hop_stars[0]], rules.hyperspace_range(1))
check("a wormhole costs one tick however far it goes", reach[hop_stars[2]["id"]] == 1)

# --------------------------------------------------------------------------
# Derived settings, and the real map
# --------------------------------------------------------------------------

check("player count is the home star count", model.player_count(valid) == 2)
check("splitResources is off when resources are equal", not model.split_resources(valid))
m = copy.deepcopy(valid)
model.set_resources(m["stars"][1], 10, 20, 30)
check("splitResources is on when they are not", model.split_resources(m))

real = ROOT / "out" / "spy_v_spy.json"
if real.exists():
    data = json.loads(real.read_text(encoding="utf-8"))
    report = validate.validate(data)
    check(f"{real.name} is valid for Solaris", report.ok)
    if not report.ok:
        failed[-1] += f"  ({report.errors[:5]})"
    check(f"{real.name} declares 36 players", model.player_count(data) == 36)
    check(f"{real.name} is inside the star cap", len(data["stars"]) <= rules.MAX_STARS)

# --------------------------------------------------------------------------
# inspect
# --------------------------------------------------------------------------

result = inspect.report(valid)
check("inspect counts the stars", result["counts"]["stars"] == len(valid["stars"]))
check("inspect counts the players", result["counts"]["players"] == 2)
check("a symmetric map has no resource spread",
      result["players"]["spread"]["natural_resources"]["spread"] == 0)

lopsided = copy.deepcopy(valid)
model.set_resources(lopsided["stars"][1], 500)          # hand one player a fortune
skewed = inspect.report(lopsided)
check("inspect catches a lopsided map",
      skewed["players"]["spread"]["natural_resources"]["spread"] > 0)

marooned = copy.deepcopy(valid)
marooned["stars"].append(model.set_resources(
    model.new_star((99999.0, 99999.0), id="99"), 10))
check("inspect finds a star nobody can reach",
      "99" in inspect.report(marooned, hyperspace=1)["connectivity"]["unreachable_by_anyone"])

check("inspect reports spacing against the floor",
      inspect.report(valid)["spacing"]["floor"] == rules.MIN_STAR_SEPARATION)
check("format_report produces text", "counts" in inspect.format_report(result))

# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------

svg = render.draw(valid)
check("render output parses as XML", ET.fromstring(svg).tag.endswith("svg"))
check("render draws a glyph per star", svg.count("<use") >= len(valid["stars"]))
check("render inlines the star symbols", 'id="star-home"' in svg)
check("render carries no unresolved values",
      not any(token in svg for token in ("NaN", "None", "undefined")))

hooked = render.draw(
    valid,
    annotate_over=lambda ctx: [ctx.text(0, 0, "MARKER", 20, ctx.palette.amber)],
)
check("annotation hooks reach the output", "MARKER" in hooked)
check("a hook can look stars up",
      render.draw(valid, annotate_over=lambda ctx: [
          ctx.circle(*ctx.point(ctx.where(homeStar=True)[0]["id"]), 50,
                     ctx.palette.green, 2)]).count("<circle") > svg.count("<circle"))

cropped_box, cropped_stars = render.frame(
    valid, render.Options(focus=(0.0, 0.0, 10.0)))
check("focus crops the view", cropped_box[2] == 20.0 and len(cropped_stars) < len(valid["stars"]))
check("star_glyph picks the home glyph",
      render.star_glyph(valid["stars"][0]) == "home")

for name, path in list(render.STAR_FILES.items()) + list(render.SHAPE_FILES.items()):
    check(f"vendored asset {name} exists", path.exists())
for path in render.NEBULA_PNGS + render.ASTEROID_PNGS + [render.VORTEX_PNG]:
    check(f"vendored texture {path.name} exists", path.exists())
check("the Telescope Array icon is vendored",
      render.specialist_icon(specialists.by_name("Telescope Array")["key"]).exists())

# --------------------------------------------------------------------------
# metrics - the reducers first, which are plain statistics and easy to pin
# --------------------------------------------------------------------------

check("spread of identical values is 0", metrics.spread([4, 4, 4]) == 0.0)
check("spread is (max - min) / mean", metrics.spread([1, 3]) == 1.0)
check("spread of nothing measurable is None", metrics.spread([None, math.inf]) is None)
check("spread ignores an unreachable player", metrics.spread([1, 3, math.inf]) == 1.0)
check("ratio is max / min", metrics.ratio([2, 8]) == 4.0)
check("ratio is None when the worst player has zero", metrics.ratio([0, 8]) is None)
check("band is (worst, typical, best)", metrics.band([5, 1, 3]) == (1, 3, 5))

hundred = list(range(101))
check("percentile interpolates", metrics.percentile(hundred, 0.10) == 10)
stat = metrics.summarise(hundred)
check("summarise centres on the median", stat["median"] == 50)
check("summarise reports a p10-p90 interval", (stat["p10"], stat["p90"]) == (10, 90))
check("summarise brackets the interval inside min and max",
      stat["min"] <= stat["p10"] <= stat["q1"] <= stat["median"]
      <= stat["q3"] <= stat["p90"] <= stat["max"])
# The interval is a percentile interval of the draws, not a CI on the mean, so
# measuring ten times as many maps must not narrow it. A CI would shrink by ~3x.
check("the interval does not shrink with more draws",
      metrics.summarise([i / 10 for i in range(1001)])["p90"] == stat["p90"])
check("summarise drops infinities", metrics.summarise([1, 2, math.inf])["n"] == 2)
check("prob_better is 0.5 for identical conditions",
      metrics.prob_better([1, 2, 3], [1, 2, 3]) == 0.5)
check("prob_better is 1.0 when every draw wins",
      metrics.prob_better([5, 6], [1, 2]) == 1.0)
check("prob_better respects the direction",
      metrics.prob_better([5, 6], [1, 2], lower_is_better=False) == 0.0)

# --- geometry the statistics lean on ---
square = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
check("convex hull drops an interior point",
      len(metrics.convex_hull(square + [(0.5, 0.5)])) == 4)
area, perimeter, quotient = metrics.hull_shape(square)
check("hull area of the unit square is 1", abs(area - 1.0) < 1e-9)
check("hull perimeter of the unit square is 4", abs(perimeter - 4.0) < 1e-9)
check("roundness of a square is pi/4", abs(quotient - math.pi / 4) < 1e-9)
circle = [geometry.polar(100.0, a * 3.6) for a in range(100)]
check("roundness of a circle approaches 1", metrics.hull_shape(circle)[2] > 0.999)

# A path: every interior vertex is a cut vertex. A cycle: none of them are.
path = [[(1, 1.0)], [(0, 1.0), (2, 1.0)], [(1, 1.0), (3, 1.0)], [(2, 1.0)]]
check("articulation points of a path are its interior",
      metrics.articulation_points(path) == {1, 2})
cycle = [[(1, 1.0), (3, 1.0)], [(0, 1.0), (2, 1.0)],
         [(1, 1.0), (3, 1.0)], [(2, 1.0), (0, 1.0)]]
check("a cycle has no articulation points", not metrics.articulation_points(cycle))

# --- reading a map ---
# A congruent map small enough to work out by hand: seven stars in a line at
# 60-80u spacing, so the whole galaxy is one piece at hyperspace 1 (125u), and
# a mirror through the origin maps each player onto the other.
line_stars = [model.new_star((x, 0.0))
              for x in (-200.0, -140.0, -60.0, 0.0, 60.0, 140.0, 200.0)]
model.assign_ids(line_stars)
for star in line_stars:
    model.set_resources(star, 25)
mirrored_players = []
for pod, (home, mate) in enumerate(((0, 1), (6, 5))):
    model.make_home_star(line_stars[home], str(pod + 1), ships=10,
                         economy=5, industry=5, science=1)
    line_stars[mate]["playerId"] = str(pod + 1)
    model.set_ships(line_stars[mate], 10)
    mirrored_players.append(model.new_player(str(pod + 1), line_stars[home]["id"]))
mirrored = model.galaxy(line_stars, mirrored_players)

reading = metrics.read(mirrored)
check("read finds one capital per player", reading.player_count == 2)
check("read takes hyperspace from the players",
      reading.hyperspace == model.DEFAULT_TECHNOLOGIES["hyperspace"])
check("read reports a connected galaxy connected at the opening jump",
      reading.connected_at_start and reading.marooned == 0)
check("fronts counts rival territory, not capital distance",
      metrics.fronts(reading) == [1, 1])
check("a congruent map has zero situation divergence",
      metrics.situation_divergence(reading) == 0.0)
check("every fairness statistic returns one value per player",
      all(len(v) == 2 for v in metrics.per_player(reading).values()))
check("a mirrored map is exactly even on contested resources",
      metrics.spread(metrics.contested_resources(reading)) == 0.0)
check("first contact is the same both ways",
      len(set(metrics.first_contact(reading))) == 1)

basic = copy.deepcopy(mirrored)
del basic["players"]
check("read falls back to hyperspace 1 in basic mode",
      metrics.read(basic).hyperspace == metrics.DEFAULT_HYPERSPACE)

# --- the two-graph answer to unreachability ---
# Two pods 300u apart. At the players' own hyperspace 1 (125u) the galaxy is in
# two pieces, so measuring travel there would hand back infinities that then
# have to be dropped - and dropping them scores the map as *fairer*, because
# the players who could not reach anything stop counting. It is measured at
# the level where the galaxy is one piece instead.
split_stars = []
for pod, base_x in enumerate((0.0, 360.0)):
    for offset in (0.0, 60.0):
        split_stars.append(model.new_star((base_x + offset, 0.0)))
split_stars.append(model.new_star((180.0, 200.0)))
model.assign_ids(split_stars)
for star in split_stars:
    model.set_resources(star, 25)
split_players = []
for pod in range(2):
    capital = split_stars[pod * 2]
    model.make_home_star(capital, str(pod + 1), ships=10, economy=5, industry=5, science=1)
    split_stars[pod * 2 + 1]["playerId"] = str(pod + 1)
    model.set_ships(split_stars[pod * 2 + 1], 10)
    split_players.append(model.new_player(
        str(pod + 1), capital["id"],
        technologies=dict(model.DEFAULT_TECHNOLOGIES, hyperspace=1, scanning=1)))
severed = model.galaxy(split_stars, split_players)
split = metrics.read(severed)
check("a galaxy in pieces is not connected at the opening jump",
      not split.connected_at_start)
check("it reports the level at which it joins up", split.connect_level == 4)
check("travel is measured at that level, so nothing is marooned",
      split.marooned == 0)
check("no travel statistic comes back unreachable",
      all(v is not None for v in metrics.first_contact(split)))
check("chokepoints stay on the opening graph",
      split.adj_open is not split.adj_travel)

# --- the whole summary ---
whole = metrics.summary(valid)
check("summary reports every statistic", all(k in whole for k in metrics.ALL))
check("summary round-trips through JSON",
      isinstance(json.loads(json.dumps(whole)), dict))
check("summary carries the raw per-player values",
      set(whole["raw"]) == set(metrics.FAIRNESS))
check("every statistic has a label", all(k in metrics.LABELS for k in metrics.ALL))
check("every scored statistic has a direction",
      set(metrics.LOWER_IS_BETTER) == set(metrics.FAIRNESS) | set(metrics.NOVELTY))
check("compactness is not scored - it is a description",
      not any(k in metrics.LOWER_IS_BETTER for k in metrics.COMPACTNESS))
check("between-seed diversity of one map is undefined",
      metrics.between_seed_diversity([metrics.descriptor(reading)]) is None)
check("between-seed diversity of identical maps is 0",
      metrics.between_seed_diversity([[1.0, 2.0], [1.0, 2.0], [1.0, 2.0]]) == 0.0)

if real.exists():
    congruent = metrics.summary(json.loads(real.read_text(encoding="utf-8")))
    # spy_v_spy is built by rotating one wedge, so every player's start is
    # congruent to every other by construction and these spreads must be
    # exactly 0. This is the strongest correctness check here: a bug in any of
    # them shows up as a non-zero spread on a map that provably has none.
    #
    # `fronts` is the documented exception - see `metrics.fronts` and
    # `metrics.situation_divergence`, which both state that this map is
    # identical on five of the six and differs only on frontage. The cause is
    # tie-breaking rather than geometry: on a congruent map 9% of stars are
    # exactly equidistant between two players, and the territory partition
    # resolves those to the lower player index, which splits the four players of
    # each galaxy 3/2/3/2. Breaking ties to the *higher* index gives 2/3/2/3 -
    # same spread, mirrored. Asserted here so the artifact stays visible instead
    # of being mistaken for a real asymmetry.
    for name in metrics.FAIRNESS:
        if name == "fronts":
            continue
        check(f"{real.name} has zero {name} spread by congruence",
              congruent[name] == 0.0)
    check(f"{real.name} frontage splits 3/2 within every galaxy",
          sorted(collections.Counter(congruent["raw"]["fronts"]).items())
          == [(2, 18), (3, 18)])
    check(f"{real.name} divergence is frontage alone",
          abs(congruent["situation_divergence"] - 1.03) < 0.01)
    # Nine separate galaxies, so it is deliberately not one piece at the
    # hyperspace its players start on - it joins up at 5, and that is the level
    # its travel statistics are measured at.
    check(f"{real.name} is nine galaxies, not one at the opening jump",
          not congruent["context"]["connected_at_start"])
    check(f"{real.name} joins up below the ceiling",
          congruent["context"]["connect_level"] is not None)

# --------------------------------------------------------------------------
# rules document, as the CLI serves it
# --------------------------------------------------------------------------

document = json.loads(json.dumps(cli.rules_document()))     # must be JSON-serialisable
check("rules document round-trips through JSON", isinstance(document, dict))
check("rules document reports the star cap",
      document["limits"]["stars"] == [rules.MIN_STARS, rules.MAX_STARS])
check("rules document reports the light year",
      document["scale"]["lightYear"] == rules.LIGHT_YEAR)
check("rules document caps 36 players at 41 stars",
      document["starsPerPlayerCap"]["36"] == 41)
check("rules document lists every star specialist",
      len(document["specialists"]["star"]) == 18)
check("rules document marks Joker as unusable",
      any(not s["custom"] for s in document["specialists"]["carrier"]))

# --------------------------------------------------------------------------

print(f"{passed} passed, {len(failed)} failed")
for name in failed:
    print(f"  FAILED: {name}")
sys.exit(1 if failed else 0)
