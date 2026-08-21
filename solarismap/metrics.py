"""Measure a map against the fairness, compactness and novelty statistics.

Three levels

    1. per player, in real units      contested_resources(reading) -> [0, 1347, ...]
    2. reduced to one number          spread(values) -> 1.80
    3. across many maps               summarise([...]) / prob_better(a, b)

"""

from __future__ import annotations

import heapq
import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field

from . import geometry, rules

Point = tuple[float, float]

# "Confrontation distance" - a neutral star both sides can be at within this
# many ticks is ground worth fighting over. Long enough to cover an opening
# expansion, short enough to exclude the far side of the galaxy.
CONTEST_TICKS = 40.0

# Which unowned star's travel time stands for expansion speed. The 1st is noise
# - it is whatever happens to sit next door - and the 50th is a whole campaign.
NTH_STAR = 10

# Radius for the local-density count, in world units. Deliberately a fixed
# world distance and NOT scaled to the jump range: comparing two conditions at
# different lattice pitches is the whole point of the measure, and a radius
# that grew with the map would hide exactly that difference.
DENSITY_RADIUS = 150.0

# Highest hyperspace level `connect_level` will look at before giving up and
# calling the galaxy severed. The game's own irregular maps join up by 5.
CONNECT_CEILING = 8

# Hyperspace and scanning to assume for a map whose `players` array does not
# say - a basic-mode galaxy, where Solaris reads only `stars`.
DEFAULT_HYPERSPACE = 1
DEFAULT_SCANNING = 1


# --------------------------------------------------------------------------
# The statistic registry
#
# Names, grouping and direction, so a figure or a sweep can iterate the
# statistics without hard-coding a list that will drift.
# --------------------------------------------------------------------------

FAIRNESS = ("contested_resources", "fronts", "ticks_to_nth_star",
            "first_contact", "capital_exposure", "starting_vision")
COMPACTNESS = ("ticks_between_capitals", "roundness")
NOVELTY = ("density_variation", "chokepoints_per_star", "situation_divergence")
ALL = FAIRNESS + COMPACTNESS + NOVELTY

LABELS = {
    "contested_resources": "contested NR",
    "fronts": "fronts",
    "ticks_to_nth_star": f"ticks to {NTH_STAR}th star",
    "first_contact": "ticks to first contact",
    "capital_exposure": "capital exposure",
    "starting_vision": "starting vision",
    "ticks_between_capitals": "ticks between capitals",
    "roundness": "roundness (1.0 = circle)",
    "density_variation": "local density variation",
    "chokepoints_per_star": "chokepoints per star",
    "situation_divergence": "player situation divergence",
    "between_seed_diversity": "between-seed diversity",
}

UNITS = {
    "contested_resources": "resources",
    "fronts": "rival players",
    "ticks_to_nth_star": "ticks",
    "first_contact": "ticks",
    "capital_exposure": "ticks",
    "starting_vision": "stars",
}

# Which way is better, for `prob_better`. The six fairness statistics are
# reported as spreads, where 0 means every player got the same, so lower wins.
# The novelty ones are the opposite: a map nobody can tell apart from any other
# is a failure. Compactness has no better direction - it is a description, not
# a score - and is deliberately absent.
LOWER_IS_BETTER = {name: True for name in FAIRNESS}
LOWER_IS_BETTER.update({name: False for name in NOVELTY})


# --------------------------------------------------------------------------
# The reading
# --------------------------------------------------------------------------


@dataclass
class Reading:
    """One map, with everything the statistics share computed once.

    Building this is the expensive part - an all-pairs distance scan and a
    Dijkstra per player - so every statistic takes a `Reading` rather than a
    galaxy, and a caller that wants several statistics pays for it once.

    Two graphs, deliberately, and which one a statistic uses is a statement
    about what it means.

    `adj_open` is the galaxy at the hyperspace level the players actually start
    on. It is the right graph for structure: `chokepoints_per_star` asks how
    redundant the routes are at the range people can currently fly, and that
    question is meaningless at a range nobody has.

    `adj_travel` is the galaxy at `connect_level`, the lowest hyperspace level
    at which it is one piece. It is the right graph for travel time. A grown
    galaxy is not connected at the opening jump and is not meant to be, but no
    real game is played at a fixed tech level either - hyperspace is the first
    thing anybody researches, and a star nobody can reach on tick 0 is merely
    far away, not marooned. Measuring travel on the opening graph produces
    infinite distances that then have to be dropped, and dropping them makes a
    badly connected map score as a *fairer* one, because the players who could
    not reach anything stop counting. Measuring at `connect_level` prices those
    players in instead.

    For a well-formed map the two are the same graph and none of this applies -
    `spy_v_spy` and `example_map` are both connected at their own starting
    level. It engages only where the alternative was silently discarding data.
    """

    stars: list[dict]
    points: list[Point]
    index: dict[str, int]
    capitals: list[dict]
    player_ids: list[str | None]
    pods: list[list[int]]
    neutral: list[int]

    hyperspace: int
    scanning: int
    opening_reach: float
    travel_reach: float
    connect_level: int | None

    adj_open: list[list[tuple[int, float]]]
    adj_travel: list[list[tuple[int, float]]]
    costs: list[list[float]]
    territory: list[int | None]
    marooned: int

    _cache: dict = field(default_factory=dict, repr=False)

    @property
    def player_count(self) -> int:
        return len(self.capitals)

    @property
    def star_count(self) -> int:
        return len(self.stars)

    @property
    def connected_at_start(self) -> bool:
        """True if the galaxy is one piece at the players' own hyperspace level.

        False is not an error - `maps/irregular.py` says plainly that a grown
        galaxy is not connected at the opening jump and that the voids are the
        point - but it does mean every travel statistic was measured at
        `connect_level` rather than at `hyperspace`.
        """
        return self.connect_level == self.hyperspace


def read(galaxy: dict, *, hyperspace: int | None = None,
         scanning: int | None = None, ceiling: int = CONNECT_CEILING) -> Reading:
    """Build the shared context for one map. The one expensive call.

    `hyperspace` and `scanning` default to the lowest level any player starts
    with, which is what the map itself says; pass them to measure a map at a
    level its players do not have.
    """
    stars = galaxy["stars"]
    if not stars:
        raise ValueError("a galaxy with no stars cannot be measured")
    players = galaxy.get("players") or []

    hyperspace = (hyperspace if hyperspace is not None
                  else _starting_level(players, "hyperspace", DEFAULT_HYPERSPACE))
    scanning = (scanning if scanning is not None
                else _starting_level(players, "scanning", DEFAULT_SCANNING))

    points = [geometry.star_point(s) for s in stars]
    index = {s["id"]: i for i, s in enumerate(stars)}

    # Capitals in a stable order. `players` is the authority when the map has
    # one, so the per-player lists line up with the map's own player order; a
    # basic-mode map has no `players` array at all, and there `homeStar` is the
    # only thing to go on.
    capitals = [s for s in stars if s.get("homeStar")]
    if not capitals:
        raise ValueError("no star is flagged homeStar - nothing to measure per player")
    if players:
        order = {p.get("homeStarId"): n for n, p in enumerate(players)}
        capitals.sort(key=lambda s: order.get(s["id"], len(players)))

    player_ids = [s.get("playerId") for s in capitals]
    owned: dict[str | None, list[int]] = {}
    for i, star in enumerate(stars):
        owned.setdefault(star.get("playerId"), []).append(i)
    pods = [owned.get(pid, [index[c["id"]]]) for pid, c in zip(player_ids, capitals)]
    neutral = owned.get(None, [])

    opening_reach = rules.hyperspace_range(hyperspace)
    adj_open = _adjacency(stars, points, index, opening_reach)

    # The lowest level that joins the galaxy up, then the graph at that level.
    # Rebuilt rather than grown because a higher level changes which pairs
    # qualify, not what they cost, and a rebuild is one O(n^2) scan.
    level = _connect_level(stars, points, index, adj_open, hyperspace, ceiling)
    if level == hyperspace:
        travel_reach, adj_travel = opening_reach, adj_open
    else:
        travel_reach = rules.hyperspace_range(level if level is not None else ceiling)
        adj_travel = _adjacency(stars, points, index, travel_reach)

    costs = [_ticks_from(adj_travel, pod) for pod in pods]
    marooned = sum(1 for i in range(len(stars))
                   if all(math.isinf(c[i]) for c in costs))

    # Territory: whose ground is this star on. The player who can get a carrier
    # here soonest from anywhere in their starting pod, ties to the lower index
    # so the partition is deterministic. A travel-time Voronoi, and it is what
    # `fronts` counts borders in.
    territory: list[int | None] = []
    for i in range(len(stars)):
        best = min(range(len(pods)), key=lambda p: (costs[p][i], p))
        territory.append(best if not math.isinf(costs[best][i]) else None)

    return Reading(stars=stars, points=points, index=index, capitals=capitals,
                   player_ids=player_ids, pods=pods, neutral=neutral,
                   hyperspace=hyperspace, scanning=scanning,
                   opening_reach=opening_reach, travel_reach=travel_reach,
                   connect_level=level, adj_open=adj_open, adj_travel=adj_travel,
                   costs=costs, territory=territory, marooned=marooned)


def _starting_level(players: Sequence[dict], key: str, fallback: int) -> int:
    """The lowest level any player starts on. `inspect._starting_hyperspace`."""
    levels = [(p.get("technologies") or {}).get(key) for p in players]
    levels = [lv for lv in levels if isinstance(lv, int)]
    return min(levels) if levels else fallback


def _adjacency(stars: Sequence[dict], points: Sequence[Point],
               index: dict[str, int], reach: float) -> list[list[tuple[int, float]]]:
    """Tick cost between every pair of stars within one jump.

    `geometry.connected_hops` answers the same question and rescans every star
    on every pop, which is fine for one map and far too slow for a hundred.
    Same answer, adjacency list, one O(n^2) pass.
    """
    adj: list[list[tuple[int, float]]] = [[] for _ in stars]
    for i in range(len(stars)):
        px, py = points[i]
        for j in range(i + 1, len(stars)):
            qx, qy = points[j]
            gap = math.hypot(px - qx, py - qy)
            if gap <= reach:
                cost = float(rules.ticks_by_distance(gap))
                adj[i].append((j, cost))
                adj[j].append((i, cost))
        # A wormhole is one tick at any distance, at any hyperspace level.
        hole = stars[i].get("wormHoleToStarId")
        if hole is not None and hole in index:
            adj[i].append((index[hole], float(rules.WORMHOLE_TICKS)))
    return adj


def _ticks_from(adj: Sequence[Sequence[tuple[int, float]]],
                sources: Sequence[int]) -> list[float]:
    """Dijkstra from every source at once. inf where nothing reaches."""
    best = [math.inf] * len(adj)
    heap: list[tuple[float, int]] = []
    for s in sources:
        best[s] = 0.0
        heapq.heappush(heap, (0.0, s))
    while heap:
        cost, node = heapq.heappop(heap)
        if cost > best[node]:
            continue
        for nxt, step in adj[node]:
            total = cost + step
            if total < best[nxt]:
                best[nxt] = total
                heapq.heappush(heap, (total, nxt))
    return best


def _is_connected(adj: Sequence[Sequence[tuple[int, float]]]) -> bool:
    """Is the whole graph one piece. Cost-free flood from a single star.

    Single-source deliberately. Flooding from every player's pod at once
    answers the weaker question "is every star reachable by *somebody*", and
    two players sealed in separate pockets pass it - each reaches their own
    pocket and between them they cover the galaxy. That is precisely the map
    the travel statistics cannot be measured on, since first contact and
    capital exposure are questions about getting from one player to another.
    """
    seen = {0}
    stack = [0]
    while stack:
        node = stack.pop()
        for nxt, _ in adj[node]:
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return len(seen) == len(adj)


def _connect_level(stars: Sequence[dict], points: Sequence[Point],
                   index: dict[str, int],
                   adj_open: Sequence[Sequence[tuple[int, float]]],
                   start: int, ceiling: int) -> int | None:
    """Lowest hyperspace level at which the whole galaxy is one piece.

    None if it never joins up by `ceiling`, which means the layout is severed
    rather than that the players need more research.
    """
    if _is_connected(adj_open):
        return start
    for level in range(start + 1, ceiling + 1):
        if _is_connected(_adjacency(stars, points, index,
                                    rules.hyperspace_range(level))):
            return level
    return None


# --------------------------------------------------------------------------
# Reducers - plain statistics, no game rules
# --------------------------------------------------------------------------


def spread(values: Sequence[float | None]) -> float | None:
    """(max - min) / mean across players. 0 means every player got the same.

    Unitless, so it compares across statistics measured in resources, ticks and
    stars alike. It says nothing about whether the map is rich or poor, only
    whether the players are treated alike. Lower is fairer.
    """
    clean = _finite(values)
    if not clean:
        return None
    mean = statistics.mean(clean)
    return (max(clean) - min(clean)) / mean if mean else 0.0


def ratio(values: Sequence[float | None]) -> float | None:
    """max / min across players - how many times better the best seat is.

    The same fact as `spread` in a form you can feel: a spread of 1.25 is
    abstract, "the best-off player has four times what the worst-off has" is
    not. None when the worst-off player has zero, which is itself the finding.
    """
    clean = _finite(values)
    if not clean or min(clean) <= 0:
        return None
    return max(clean) / min(clean)


def band(values: Sequence[float | None]) -> tuple[float, float, float] | None:
    """(worst, typical, best) across players, in the statistic's own units.

    Report this next to `spread`, always. A spread cannot distinguish "the
    worst-off player has a little" from "the worst-off player has nothing", and
    that distinction is the most concrete fairness finding in the study.
    """
    clean = _finite(values)
    if not clean:
        return None
    return min(clean), statistics.median(clean), max(clean)


def _finite(values: Sequence[float | None]) -> list[float]:
    return [float(v) for v in values if v is not None and not math.isinf(v)]


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile of an already-sorted sequence."""
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def summarise(values: Sequence[float | None]) -> dict | None:
    """Centre and spread of one statistic over many maps.

    The uncertainty interval here is a **percentile interval of the draws**,
    not a confidence interval on the mean. The question is "how much does the
    map I am about to generate vary", and that spread does not shrink however
    many maps are measured. A CI would shrink, and would imply a reliability
    the generator does not have.

    The median alone hides the thing that decides whether a generator is
    usable: one with a good median and a heavy tail produces occasional
    disasters, and on a map you generate once, the tail is what you get.
    """
    clean = sorted(float(v) for v in values
                   if v is not None and not math.isinf(v))
    if not clean:
        return None
    mean = statistics.mean(clean)
    q1, q3 = percentile(clean, 0.25), percentile(clean, 0.75)
    return {"mean": mean, "median": statistics.median(clean),
            "q1": q1, "q3": q3, "iqr": q3 - q1,
            "p10": percentile(clean, 0.10), "p90": percentile(clean, 0.90),
            "min": clean[0], "max": clean[-1],
            "cv": (statistics.pstdev(clean) / mean) if mean else 0.0,
            "n": len(clean)}


def prob_better(baseline: Sequence[float | None], candidate: Sequence[float | None],
                lower_is_better: bool = True) -> float | None:
    """P(a random candidate map beats a random baseline map).

    The common-language effect size, and the honest answer to "how reliable is
    this improvement". 0.50 means the two are indistinguishable on a single
    draw; 1.00 means the candidate wins every time. Read it before any
    percentage change in a median: a shift with this near 0.5 is a difference
    nobody would notice generating one map.
    """
    a = _finite(baseline)
    b = _finite(candidate)
    if not a or not b:
        return None
    wins = ties = 0
    for x in a:
        for y in b:
            if y == x:
                ties += 1
            elif (y < x) == lower_is_better:
                wins += 1
    return (wins + 0.5 * ties) / (len(a) * len(b))


# --------------------------------------------------------------------------
# Fairness - six per-player quantities, in real units
#
# Each returns one value per player, in the order of `reading.capitals`.
# Reduce with `spread` for a map-level number, or read with `band` to see what
# the worst-off, typical and best-off player actually get.
# --------------------------------------------------------------------------


def contested_resources(reading: Reading, *,
                        ticks: float = CONTEST_TICKS) -> list[float]:
    """Natural resources on neutral stars you and a rival can both reach.

    The prize you have to fight for, as opposed to the prize you are handed. A
    player with nothing contested nearby has no reason to leave home, and a
    player whose every neighbour is contested has no safe ground to build on.

    Unit: resources. Zero is not a low score, it is a broken seat - there is no
    neutral star that both this player and any rival can be at within `ticks`,
    so there is no contested ground at all.
    """
    key = ("contested", ticks)
    if key not in reading._cache:
        out = []
        for p in range(reading.player_count):
            total = 0.0
            for i in reading.neutral:
                if reading.costs[p][i] > ticks:
                    continue
                if any(reading.costs[q][i] <= ticks
                       for q in range(reading.player_count) if q != p):
                    total += sum((reading.stars[i].get("naturalResources")
                                  or {}).values())
            out.append(total)
        reading._cache[key] = out
    return list(reading._cache[key])


def fronts(reading: Reading) -> list[int]:
    """How many rival players' territory touches yours.

    Territory is a travel-time Voronoi: every star belongs to whoever can get a
    carrier to it soonest from their starting pod. Two players are on a front
    when a star of one is one legal jump from a star of the other. This is how
    many directions you can be attacked from, and nobody chose which they got -
    one neighbour and five are different games.

    Unit: rival players. It counts *actual* frontage rather than capital
    adjacency, which matters two ways. A corridor walled by deleting the stars
    in it stops being a front, as intended, where a capital-distance measure
    still counts it. And it works on a hand-placed map: the lattice heuristic
    in `randomise.capital_graph` takes the shortest capital-to-capital distance
    as the pitch, so on a ring of evenly spaced capitals it reports exactly two
    for everybody whatever else the map does - it says 2 for all 36 players of
    `spy_v_spy`, where this says 2 for eighteen of them and 3 for the rest.
    """
    if "fronts" not in reading._cache:
        touching: list[set[int]] = [set() for _ in range(reading.player_count)]
        for i, mine in enumerate(reading.territory):
            if mine is None:
                continue
            # Borders are counted on `adj_open`, the range the players actually
            # have, not on `adj_travel`. The two graphs answer different
            # questions and this is a structure question - see `Reading`.
            #
            # On `adj_travel` a badly connected galaxy is measured at whatever
            # hyperspace level finally joins it up, which can be 8: a 475u jump
            # against the 175u the players start with. At that radius a star is
            # "one jump" from most of the neighbourhood, so territories two and
            # three regions apart get counted as touching, and the statistic
            # inflates precisely on the maps that are worst connected. Measured
            # across 400 draws it ran to 20 rivals where the opening jump gives
            # 14, and the inflation tracked `connect_level` monotonically.
            #
            # Territory still comes from `adj_travel`, so no star is dropped for
            # being unreachable - that hazard is real and is what the graph is
            # there for. Only the border test moves.
            for j, _ in reading.adj_open[i]:
                theirs = reading.territory[j]
                if theirs is not None and theirs != mine:
                    touching[mine].add(theirs)
                    touching[theirs].add(mine)
        reading._cache["fronts"] = [len(t) for t in touching]
    return list(reading._cache["fronts"])


def ticks_to_nth_star(reading: Reading, *, n: int = NTH_STAR) -> list[float | None]:
    """Travel time to your Nth nearest unowned star, from your whole pod.

    Expansion speed, which compounds: a player slower to their tenth star is
    behind on economy for the rest of the game, and the gap widens.

    Unit: ticks. None if the map has fewer than `n` unowned stars this player
    can reach at all, which on a connected galaxy means the map is too small
    for the question.
    """
    key = ("nth", n)
    if key not in reading._cache:
        out: list[float | None] = []
        for p in range(reading.player_count):
            got = sorted(c for c in (reading.costs[p][i] for i in reading.neutral)
                         if not math.isinf(c))
            out.append(got[n - 1] if len(got) >= n else None)
        reading._cache[key] = out
    return list(reading._cache[key])


def first_contact(reading: Reading) -> list[float | None]:
    """Travel time until you can touch any rival-owned star.

    When the shooting can start. Being reachable on tick 8 while a rival is
    safe until tick 40 is a handicap set before anyone moves.

    Unit: ticks.
    """
    if "contact" not in reading._cache:
        out: list[float | None] = []
        for p in range(reading.player_count):
            rival = [i for q, pod in enumerate(reading.pods) if q != p for i in pod]
            best = min((reading.costs[p][i] for i in rival), default=math.inf)
            out.append(None if math.isinf(best) else best)
        reading._cache["contact"] = out
    return list(reading._cache["contact"])


def capital_exposure(reading: Reading) -> list[float | None]:
    """Travel time for the nearest rival to reach *your* capital.

    The same question as `first_contact` about the one star whose loss ends
    your game in the official home-star-elimination modes.

    Unit: ticks. Measured towards you, not from you - it is the one fairness
    statistic where a high number is unambiguously good for its player.
    """
    if "exposure" not in reading._cache:
        out: list[float | None] = []
        for p, capital in enumerate(reading.capitals):
            home = reading.index[capital["id"]]
            best = min((reading.costs[q][home]
                        for q in range(reading.player_count) if q != p),
                       default=math.inf)
            out.append(None if math.isinf(best) else best)
        reading._cache["exposure"] = out
    return list(reading._cache["exposure"])


def starting_vision(reading: Reading) -> list[int]:
    """Stars visible from your starting pod on turn one. Solaris has fog.

    Per star rather than one flat radius, because a black hole scans at +3 and
    a dead star scans nothing at all: at scanning 3 a black hole sees 350 units
    against a plain star's 200. Using one radius for the whole map understates
    the vision of any map with a black hole near a pod, which is most of them.

    Unit: stars, excluding the player's own.
    """
    if "vision" not in reading._cache:
        radius = [rules.scanning_range(rules.effective_scanning(reading.scanning, s))
                  for s in reading.stars]
        out = []
        for pod in reading.pods:
            seen = {j for i in pod for j in range(reading.star_count)
                    if geometry.dist(reading.points[i], reading.points[j]) <= radius[i]}
            out.append(len(seen - set(pod)))
        reading._cache["vision"] = out
    return list(reading._cache["vision"])


# --------------------------------------------------------------------------
# Compactness - one number per map
#
# Not scores. A compact galaxy is not better or worse than a roomy one, and
# neither of these has a good direction. They are here because the study found
# every timing statistic shrinking by about 10% and had nothing that could say
# why - these two say why.
# --------------------------------------------------------------------------


def ticks_between_capitals(reading: Reading) -> float | None:
    """Median shortest-path travel time between every pair of capitals.

    Compactness in the units the game cares about. How much room the galaxy
    occupies is a description of the picture; this is how far apart that
    actually puts people, which is the thing a compact map changes. Lower is
    more compact.

    Unit: ticks.
    """
    if "span" not in reading._cache:
        home = [reading.index[c["id"]] for c in reading.capitals]
        pairs = [reading.costs[a][home[b]]
                 for a in range(reading.player_count)
                 for b in range(reading.player_count)
                 if a != b and not math.isinf(reading.costs[a][home[b]])]
        reading._cache["span"] = statistics.median(pairs) if pairs else None
    return reading._cache["span"]


def roundness(reading: Reading) -> float:
    """Isoperimetric quotient `4*pi*A / P^2` of the galaxy's convex hull.

    1.0 is a perfect circle and it falls towards 0 for anything long or ragged
    - a direct reading of "round blob" against "stringy". Independent of size,
    which is the point: scaling a lattice up restores a galaxy's area without
    restoring its shape, and only a shape measure can tell the two apart.

    Unitless, 0 to 1.
    """
    if "roundness" not in reading._cache:
        reading._cache["roundness"] = hull_shape(reading.points)[2]
    return reading._cache["roundness"]


def convex_hull(points: Sequence[Point]) -> list[Point]:
    """Andrew's monotone chain. The galaxy's outline."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def half(seq: Sequence[Point]) -> list[Point]:
        out: list[Point] = []
        for p in seq:
            while len(out) >= 2:
                (ax, ay), (bx, by) = out[-2], out[-1]
                if (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax) > 0:
                    break
                out.pop()
            out.append(p)
        return out[:-1]

    return half(pts) + half(list(reversed(pts)))


def hull_shape(points: Sequence[Point]) -> tuple[float, float, float]:
    """(area, perimeter, isoperimetric quotient) of the convex hull."""
    hull = convex_hull(points)
    if len(hull) < 3:
        return 0.0, 0.0, 0.0
    area = abs(sum(hull[i][0] * hull[i - 1][1] - hull[i - 1][0] * hull[i][1]
                   for i in range(len(hull)))) / 2.0
    perimeter = sum(geometry.dist(hull[i], hull[i - 1]) for i in range(len(hull)))
    quotient = (4.0 * math.pi * area / (perimeter * perimeter)) if perimeter else 0.0
    return area, perimeter, quotient


# --------------------------------------------------------------------------
# Novelty - one number per map
#
# Fairness is a floor, not a goal. A perfectly fair map can be perfectly dull,
# and a rotationally symmetric one is the limiting case: every place in it
# exists N times, so it scores the minimum on situation divergence by
# construction.
# --------------------------------------------------------------------------


def density_variation(reading: Reading, *, radius: float = DENSITY_RADIUS) -> float:
    """Coefficient of variation of how many stars sit within `radius` of a star.

    0 is a perfectly even field with no places in it. 0.33 means a typical
    neighbourhood is about a third denser or sparser than average, which is
    roughly what the game's own generator produces. Higher is more varied.

    Unitless. `radius` is a fixed world distance, so this is *not* invariant to
    the scale of the map - which is deliberate when comparing two conditions,
    and a trap when comparing maps built at different lattice pitches.
    """
    key = ("density", radius)
    if key not in reading._cache:
        counts = [sum(1 for q in reading.points if geometry.dist(p, q) <= radius)
                  for p in reading.points]
        mean = statistics.mean(counts)
        reading._cache[key] = statistics.pstdev(counts) / mean if mean else 0.0
    return reading._cache[key]


def chokepoints_per_star(reading: Reading) -> float:
    """Articulation points of the opening reachability graph, over star count.

    A cut vertex is a star whose loss disconnects a region: hold it and you
    hold everything behind it. 0.25 means one star in four is such a
    chokepoint. Higher is more tactically structured.

    Measured on `adj_open`, at the hyperspace level the players actually start
    with, because the statistic is about density relative to the jump range
    people have. A rounder, denser field has more redundant routes and so fewer
    chokepoints; spreading the same field out thins the graph until nearly
    every star is a cut vertex.

    Unitless, 0 to 1.
    """
    if "choke" not in reading._cache:
        reading._cache["choke"] = (len(articulation_points(reading.adj_open))
                                   / reading.star_count)
    return reading._cache["choke"]


def articulation_points(adj: Sequence[Sequence[tuple[int, float]]]) -> set[int]:
    """Vertices whose removal disconnects their component. Iterative Tarjan.

    Iterative rather than recursive because a 1500-star galaxy is deeper than
    Python's stack. Walks every component, which matters here: the opening
    graph of a grown galaxy is several pieces, not one.
    """
    n = len(adj)
    disc = [-1] * n
    low = [0] * n
    parent = [-1] * n
    cut: set[int] = set()
    timer = 0
    for root in range(n):
        if disc[root] != -1:
            continue
        stack = [(root, iter(adj[root]))]
        disc[root] = low[root] = timer
        timer += 1
        children = 0
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt, _ in it:
                if disc[nxt] == -1:
                    parent[nxt] = node
                    disc[nxt] = low[nxt] = timer
                    timer += 1
                    if node == root:
                        children += 1
                    stack.append((nxt, iter(adj[nxt])))
                    advanced = True
                    break
                if nxt != parent[node]:
                    low[node] = min(low[node], disc[nxt])
            if not advanced:
                stack.pop()
                if stack:
                    up = stack[-1][0]
                    low[up] = min(low[up], low[node])
                    if up != root and low[node] >= disc[up]:
                        cut.add(up)
        if children > 1:
            cut.add(root)
    return cut


def situation_divergence(reading: Reading) -> float:
    """How differently the players are situated, within this one map.

    Z-score each player's five fairness quantities across the players of the
    map, then take the mean pairwise distance in that five-dimensional space.
    Exactly 0 means every player's five quantities are identical, which is what
    a fully congruent map scores by construction. Higher means the seats are
    genuinely different from one another. A symmetric map that is congruent in
    most respects still scores above 0 for the ones it is not - `spy_v_spy` is
    identical on five of the six and lands at 1.03, entirely on frontage.

    Capital exposure is deliberately left out of the five, matching the study,
    because it is very nearly the mirror of first contact and counting both
    would weight the same fact twice.

    Unitless. It does not say whether the differences are *fair* - that is what
    the six spreads are for. A map can be wildly divergent and even-handed, and
    that combination is the goal.
    """
    if "divergence" not in reading._cache:
        n = reading.player_count
        if n < 2:
            reading._cache["divergence"] = 0.0
            return 0.0
        rows = [contested_resources(reading),
                [float(v) for v in fronts(reading)],
                [0.0 if v is None else v for v in ticks_to_nth_star(reading)],
                [0.0 if v is None else v for v in first_contact(reading)],
                [float(v) for v in starting_vision(reading)]]
        z = []
        for row in rows:
            mu = statistics.mean(row)
            sd = statistics.pstdev(row) or 1.0
            z.append([(v - mu) / sd for v in row])
        reading._cache["divergence"] = statistics.mean(
            math.dist([col[a] for col in z], [col[b] for col in z])
            for a in range(n) for b in range(a + 1, n))
    return reading._cache["divergence"]


# --------------------------------------------------------------------------
# Across a set of maps
# --------------------------------------------------------------------------


def descriptor(reading: Reading) -> list[float]:
    """Five numbers that place one map in the space of possible maps.

    The input to `between_seed_diversity`, and nothing else. Texture,
    structure, seat variety, aspect ratio and packing - deliberately not the
    fairness statistics, because two maps can be equally fair and completely
    different galaxies.
    """
    xs = [p[0] for p in reading.points]
    ys = [p[1] for p in reading.points]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    return [density_variation(reading), chokepoints_per_star(reading),
            situation_divergence(reading), (max(xs) - min(xs)) / span,
            reading.star_count / (span * span) * 1e5]


def between_seed_diversity(descriptors: Sequence[Sequence[float]],
                           sample: int = 60) -> float | None:
    """Mean pairwise distance between maps, in z-scored descriptor space.

    One number for a whole *set* of maps, not for one map: it asks whether a
    hundred seeds give a hundred different galaxies or the same one a hundred
    times. 0 means the generator makes the same galaxy every time. A generator
    can be perfectly fair and completely monotonous, and nothing measured on a
    single map can tell you which.

    Capped at `sample` maps because the pairwise term is quadratic and the mean
    stops moving long before a hundred. The subsample is evenly spaced rather
    than random, so the answer is deterministic.
    """
    rows = [list(d) for d in descriptors]
    if len(rows) < 2:
        return None
    z = []
    for col in zip(*rows):
        mu = statistics.mean(col)
        sd = statistics.pstdev(col) or 1.0
        z.append([(v - mu) / sd for v in col])
    zrows = list(zip(*z))
    if len(zrows) > sample:
        step = len(zrows) / sample
        zrows = [zrows[int(i * step)] for i in range(sample)]
    return statistics.mean(math.dist(a, b)
                           for i, a in enumerate(zrows) for b in zrows[i + 1:])


# --------------------------------------------------------------------------
# The whole thing at once
# --------------------------------------------------------------------------


def per_player(reading: Reading) -> dict[str, list]:
    """Every fairness statistic, in real units, one list per statistic."""
    return {
        "contested_resources": contested_resources(reading),
        "fronts": fronts(reading),
        "ticks_to_nth_star": ticks_to_nth_star(reading),
        "first_contact": first_contact(reading),
        "capital_exposure": capital_exposure(reading),
        "starting_vision": starting_vision(reading),
    }


def summary(galaxy: dict, *, hyperspace: int | None = None,
            scanning: int | None = None) -> dict:
    """Every statistic for one map, as a flat JSON-serialisable dict.

    The six fairness entries are spreads. Their raw per-player values are under
    `raw`, and the worst / typical / best player under `band` - read those
    before reading the spread, because a spread cannot tell you whether the
    worst-off player has a little or has nothing.
    """
    reading = read(galaxy, hyperspace=hyperspace, scanning=scanning)
    raw = per_player(reading)
    out: dict = {name: spread(values) for name, values in raw.items()}
    out.update({
        "ticks_between_capitals": ticks_between_capitals(reading),
        "roundness": roundness(reading),
        "density_variation": density_variation(reading),
        "chokepoints_per_star": chokepoints_per_star(reading),
        "situation_divergence": situation_divergence(reading),
        "raw": raw,
        "band": {name: band(values) for name, values in raw.items()},
        "ratio": {name: ratio(values) for name, values in raw.items()},
        "descriptor": descriptor(reading),
        "context": {
            "stars": reading.star_count,
            "players": reading.player_count,
            "hyperspace": reading.hyperspace,
            "scanning": reading.scanning,
            "opening_reach": reading.opening_reach,
            "travel_reach": reading.travel_reach,
            "connect_level": reading.connect_level,
            "connected_at_start": reading.connected_at_start,
            "marooned": reading.marooned,
        },
    })
    return out


def format_summary(result: dict) -> str:
    """The human-readable version of `summary`. --json gives the dict."""
    ctx = result["context"]
    out: list[str] = []
    out.append(f"{ctx['stars']} stars, {ctx['players']} players, "
               f"hyperspace {ctx['hyperspace']} ({ctx['opening_reach']:.0f}u), "
               f"scanning {ctx['scanning']}")
    if ctx["connected_at_start"]:
        out.append(f"connected at the opening jump - travel measured at "
                   f"hyperspace {ctx['hyperspace']}")
    elif ctx["connect_level"] is not None:
        out.append(f"not connected at the opening jump - travel measured at "
                   f"hyperspace {ctx['connect_level']} ({ctx['travel_reach']:.0f}u), "
                   f"where the galaxy is one piece")
    else:
        out.append(f"SEVERED - {ctx['marooned']} star(s) unreachable at hyperspace "
                   f"{CONNECT_CEILING}; travel statistics cover only what is reachable")

    out.append("")
    out.append(f"fairness{'':<16}spread    worst  typical     best")
    for name in FAIRNESS:
        value = result[name]
        cell = "     -" if value is None else f"{value:6.2f}"
        b = result["band"][name]
        if b is None:
            out.append(f"  {LABELS[name]:<22}{cell}")
            continue
        out.append(f"  {LABELS[name]:<22}{cell}   {b[0]:6.0f}   {b[1]:6.0f}   "
                   f"{b[2]:6.0f}   {UNITS[name]}")
    out.append("  spread is (max - min) / mean across players. 0 = identical, "
               "lower is fairer.")

    out.append("")
    out.append("compactness - a description, not a score")
    span = result["ticks_between_capitals"]
    out.append(f"  {LABELS['ticks_between_capitals']:<30}"
               f"{'-' if span is None else f'{span:6.1f}'}   ticks, median pair")
    out.append(f"  {LABELS['roundness']:<30}{result['roundness']:6.3f}")

    out.append("")
    out.append("novelty - higher is more interesting")
    for name in NOVELTY:
        out.append(f"  {LABELS[name]:<30}{result[name]:6.3f}")
    return "\n".join(out)
