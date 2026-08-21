"""Star *properties* - resources, terrain, wormholes - as opposed to positions.

`generate` decides where the stars are. This decides what each one is, which is
the half the toolkit was missing: a generated galaxy came out with 360 stars
distinguished by nothing but a resource number - no nebula, no asteroid field,
no binary, no black hole, no pulsar, no wormhole anywhere on the map.

Ported from the editor's Randomise menu (`src/components/menu/randomise/
RandomiseMenu.vue`) and its `settings.random` defaults in `storage.ts`. That is a
separate menu from Generate upstream too, and the split is worth keeping: you can
re-roll a galaxy's terrain without moving a single star.

Two things here are *not* upstream, and both exist because upstream's versions
are unfair on a grown map:

    terrain_from_noise   upstream scatters terrain uniformly at random, which
                         gives salt-and-pepper. This thresholds a noise field, so
                         terrain arrives in regions - a nebula belt, an asteroid
                         cluster - which is what makes it worth navigating.
    balance_by_channel   equalises each resource channel across players, so
                         split resources do not hand somebody a science monopoly.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from . import generate, geometry, rules

Point = tuple[float, float]


# --------------------------------------------------------------------------
# The editor's defaults, settings.random in storage.ts
# --------------------------------------------------------------------------

MIN_RESOURCES = 10
MAX_RESOURCES = 50
LOW_VALUE_BIAS = 0.5                # 0.5 is uniform; see random_int_between_exp
RADIUS_WEIGHT = 0.0                 # 0 disables the distance term entirely

# Every terrain percentage upstream defaults to 0, which is why a freshly
# generated galaxy has no terrain at all unless somebody goes and asks for it.
TERRAIN_KEYS = ("isNebula", "isAsteroidField", "isBinaryStar",
                "isBlackHole", "isPulsar", "warpGate")


# --------------------------------------------------------------------------
# The distribution
# --------------------------------------------------------------------------


def random_int_between_exp(rng: generate.Rng, minimum: int, maximum: int,
                           low_value_bias: float = LOW_VALUE_BIAS) -> int:
    """An integer in [minimum, maximum], skewed by `low_value_bias`.

    `randomIntBetweenExp` - editor RandomiseMenu.vue. Raises a uniform draw to
    the power `log(1 - bias) / log(0.5)`, so over a 10..50 range:

        bias 0.2   exponent 0.32   mean 40
        bias 0.5   exponent 1.00   mean 30, uniform
        bias 0.8   exponent 2.32   mean 22

    Note the direction: **higher bias means lower values**. The name reads as
    "how strongly biased towards the low end", and it increases with the
    parameter. Bias at or above 1 is undefined, and is clamped.

    Why a power curve rather than a bell: it keeps the hard endpoints. An author
    picking 10..50 gets stars worth exactly 10 and exactly 50, which is what
    makes the range meaningful to reason about.
    """
    bias = min(max(low_value_bias, 0.001), 0.999)
    exponent = math.log(1.0 - bias) / math.log(0.5)
    return math.floor((rng.random() ** exponent) * (maximum - minimum + 1) + minimum)


def _bias_at(point: Point, anchors: Sequence[Point], scale: float,
             low_value_bias: float, radius_weight: float) -> float:
    """The bias to use at this point, once distance is folded in.

    `bias = distance / scale * radius_weight + low_value_bias`, straight from the
    editor's weighted-radius mode. With `radius_weight` positive, far stars get a
    higher bias and so come out poorer; negative reverses it.
    """
    if not radius_weight or not anchors or scale <= 0.0:
        return low_value_bias
    nearest = min(geometry.dist(point, anchor) for anchor in anchors)
    return min(nearest / scale, 1.0) * radius_weight + low_value_bias


# --------------------------------------------------------------------------
# Resources
# --------------------------------------------------------------------------


def randomise_resources(stars: Sequence[dict], rng: generate.Rng, *,
                        minimum: int = MIN_RESOURCES, maximum: int = MAX_RESOURCES,
                        low_value_bias: float = LOW_VALUE_BIAS,
                        radius_weight: float = RADIUS_WEIGHT,
                        anchors: Sequence[Point] | None = None,
                        split: bool = True) -> None:
    """Give every star in `stars` natural resources, in place.

    `randomiseNR` - editor RandomiseMenu.vue, with one deliberate change.
    Upstream measures the radius term from the **centre of the selection**, which
    on a grown galaxy is unfair by construction: a player seated on the rim gets
    systematically different stars from one seated in the middle, for no reason
    any player can see or act on.

    Pass `anchors` - normally the capitals - and the distance is measured to the
    *nearest* one instead. Every player then sees the same relationship between
    distance-from-home and value, wherever they were seated. Pass nothing and it
    behaves like upstream.

    `split=True` rolls the three channels independently, which is what turns
    Solaris's `splitResources` on and makes a star qualitatively rather than just
    quantitatively different: a science world is worth taking for different
    reasons than an industry one. `split=False` rolls once and copies.
    """
    from . import model                          # local import: model imports rules

    scale = 0.0
    if anchors and radius_weight:
        # Normalise against the furthest any star sits from its nearest anchor,
        # so `radius_weight` means the same thing at any galaxy size.
        scale = max(min(geometry.dist(geometry.star_point(s), a) for a in anchors)
                    for s in stars) or 1.0

    for star in stars:
        bias = _bias_at(geometry.star_point(star), anchors or (), scale,
                        low_value_bias, radius_weight)
        if split:
            model.set_resources(star,
                                random_int_between_exp(rng, minimum, maximum, bias),
                                random_int_between_exp(rng, minimum, maximum, bias),
                                random_int_between_exp(rng, minimum, maximum, bias))
        else:
            model.set_resources(star,
                                random_int_between_exp(rng, minimum, maximum, bias))


def balance_by_channel(stars: Sequence[dict], capitals: Sequence[dict],
                       horizon: float, *, minimum: int = MIN_RESOURCES,
                       maximum: int = MAX_RESOURCES, rounds: int = 40,
                       damping: float = 0.5, tolerance: float = 0.2) -> None:
    """Even out each resource channel across players, in place. Not upstream.

    Splitting the channels creates a second fairness problem on top of the one
    grown maps already have. Equal *totals* within reach stop being enough: a
    player whose neighbourhood is all industry and no science is behind on
    research however healthy the sum looks, and no impartial pricing rule fixes
    it, because the imbalance is in how much of each kind happens to be nearby.

    So run the balancing per channel. For each channel independently, nudge the
    neutral stars until every player's neighbourhood holds about the same amount
    of it. A star inside several players' horizons is pulled by all of them and
    settles on the geometric mean of their demands; the pull is damped so one
    very poor player cannot slam every shared star to the ceiling in a single
    pass; and values stay inside `minimum..maximum` throughout, so a badly enough
    seated player is not compensated all the way. That residue is real and
    belongs in a check rather than hidden here.

    Only stars with no `playerId` move, so run it after players are assigned and
    a fixed opening survives untouched.
    """
    reach: dict[str, list[int]] = {}
    for star in stars:
        if star.get("playerId") is not None:
            continue
        here = geometry.star_point(star)
        reach[star["id"]] = [i for i, c in enumerate(capitals)
                             if geometry.dist(here, geometry.star_point(c)) <= horizon]
    neutrals = [s for s in stars if s["id"] in reach]
    if not neutrals or not capitals:
        return

    for channel in rules.RESOURCE_CHANNELS:
        values = {s["id"]: float(s["naturalResources"][channel]) for s in neutrals}
        for _ in range(rounds):
            totals = [0.0] * len(capitals)
            for star in neutrals:
                for index in reach[star["id"]]:
                    totals[index] += values[star["id"]]
            target = sum(totals) / len(totals)
            if not target:
                break
            if (max(totals) - min(totals)) / target <= tolerance:
                break
            for star in neutrals:
                pulling = [i for i in reach[star["id"]] if totals[i]]
                if not pulling:
                    continue
                factor = math.prod(target / totals[i]
                                   for i in pulling) ** (1.0 / len(pulling))
                nudged = values[star["id"]] * (1.0 + (factor - 1.0) * damping)
                values[star["id"]] = min(max(nudged, float(minimum)), float(maximum))
        for star in neutrals:
            star["naturalResources"][channel] = round(values[star["id"]])


# --------------------------------------------------------------------------
# Terrain
# --------------------------------------------------------------------------


def randomise_terrain(stars: Sequence[dict], rng: generate.Rng,
                      **percentages: float) -> dict[str, int]:
    """Scatter terrain over a percentage of eligible stars. The editor's way.

    RandomiseMenu.vue: `count = floor(eligible / 100 * percentage)`, shuffle,
    take that many. Keys are Solaris field names - `isNebula`, `isAsteroidField`,
    `isBinaryStar`, `isBlackHole`, `isPulsar`, `warpGate`.

    Uniform and independent, which means salt-and-pepper: a nebula here, another
    four hundred units away, no two adjacent. Terrain scattered this way is
    texture you notice one star at a time and never navigate around. Prefer
    `terrain_from_noise` for anything a player is meant to plan against; this is
    the right tool for genuinely incidental flavour, and it is what upstream does.

    Home stars are excluded - terrain on a capital is a balance question, not
    flavour. Dead stars are excluded from `warpGate`, which Solaris rejects there.
    """
    counts: dict[str, int] = {}
    for key, percentage in percentages.items():
        if key not in TERRAIN_KEYS or percentage <= 0:
            continue
        eligible = [s for s in stars if not s.get("homeStar")]
        if key == "warpGate":
            eligible = [s for s in eligible if not rules.is_dead_star(s)]
        count = math.floor(len(eligible) / 100.0 * percentage)
        rng.shuffle(eligible)
        for star in eligible[:count]:
            star[key] = True
        counts[key] = count
    return counts


def terrain_spread(stars: Sequence[dict], fraction: float = 0.45) -> float:
    """The noise spread that makes terrain arrive in belts, from the galaxy's size.

    **Terrain wants a much wider field than the voids do**, and getting this
    wrong is the difference between the feature working and not working at all.
    `generate.noise_spread` is tuned for carving voids, where you want many
    pockets scattered through the galaxy - about 142 units on a small map. Reuse
    it for terrain and the top slice of the field is a scatter of small peaks,
    which is salt-and-pepper again by a more expensive route.

    Measured on an eight-player map, holding the nebula count fixed at 28 and
    varying only the spread, mean distance from a nebula to its nearest nebula:

        spread  142u    115u    2% tighter than uniform random - no effect
        spread  250u    100u   15% tighter
        spread  400u     67u   43% tighter
        spread  600u     60u   49% tighter, and now at the star-to-star gap,
                               which is what a contiguous belt looks like

    So the useful range is a substantial fraction of the whole galaxy, not a
    fraction of the star spacing. This returns `fraction` of the galaxy's larger
    dimension, defaulting to a little under half - a handful of big regions.
    """
    if not stars:
        return 1.0
    xs = [geometry.star_point(s)[0] for s in stars]
    ys = [geometry.star_point(s)[1] for s in stars]
    return max(max(xs) - min(xs), max(ys) - min(ys)) * fraction or 1.0


def quantile_bands(stars: Sequence[dict], field: generate.Noise, spread: float,
                   wanted: Sequence[tuple[str, float]],
                   offset: Point = (0.0, 0.0)) -> list[tuple[str, float, float]]:
    """Turn "I want N% nebula" into the `bands` thresholds that deliver it.

    Absolute thresholds on a noise field are not portable: the same 0.4 cutoff
    gives a different share of the stars at every spread, seed and galaxy size,
    so tuning a band by hand is trial and error that has to be redone whenever
    anything else moves. This solves for the cutoff instead, by sorting the
    actual field values at the actual star positions and cutting at the quantile.

    `wanted` is `(field_name, percentage)`. Positive percentages are taken from
    the **high** end of the field and negative from the **low** end, so
    `[("isNebula", 17.5), ("isAsteroidField", -12.5)]` puts nebulas in the peaks
    and asteroid fields in the troughs, which keeps them in separate regions
    rather than interleaved.
    """
    eligible = [s for s in stars if not s.get("homeStar")]
    if not eligible:
        return []
    values = sorted(field((geometry.star_point(s)[0] + offset[0]) / spread,
                          (geometry.star_point(s)[1] + offset[1]) / spread)
                    for s in eligible)
    bands: list[tuple[str, float, float]] = []
    for name, percentage in wanted:
        count = max(1, min(len(values), round(len(values) * abs(percentage) / 100.0)))
        if percentage >= 0:
            bands.append((name, values[len(values) - count], math.inf))
        else:
            bands.append((name, -math.inf, values[count - 1]))
    return bands


def terrain_from_noise(stars: Sequence[dict], field: generate.Noise, *,
                       spread: float, bands: Sequence[tuple[str, float, float]],
                       offset: Point = (0.0, 0.0)) -> dict[str, int]:
    """Paint terrain in coherent regions by thresholding a noise field. Not upstream.

    `bands` is a list of `(field_name, low, high)`: a star whose noise value falls
    in `[low, high)` gets that field set. Because the field is continuous,
    neighbouring stars get similar values, so terrain arrives as a **belt or a
    cluster** rather than as isolated stars. That is the whole difference. A
    nebula belt is a place - carriers hide in it, you route around it, you fight
    for the gap in it. Forty nebulas sprinkled at random are forty separate minor
    facts about forty separate stars.

    Use a **different field from the one that carved the voids**, or an `offset`
    far enough away to decorrelate them. Sharing a field means terrain can only
    ever appear where the stars are already thickest, which is backwards.

    Bands should not overlap unless you want stars carrying two kinds of terrain.
    Returns the count placed per field, which is what a check wants.

    Home stars are skipped, and `warpGate` is skipped on dead stars.
    """
    counts = {name: 0 for name, _, _ in bands}
    for star in stars:
        if star.get("homeStar"):
            continue
        x, y = geometry.star_point(star)
        value = field((x + offset[0]) / spread, (y + offset[1]) / spread)
        for name, low, high in bands:
            if low <= value < high:
                if name == "warpGate" and rules.is_dead_star(star):
                    continue
                star[name] = True
                counts[name] += 1
    return counts


def link_wormholes(stars: Sequence[dict], rng: generate.Rng,
                   percentage: float) -> int:
    """Pair up stars with wormholes at random. The editor's way.

    RandomiseMenu.vue: `count = stars.length / 2 / 100 * percentage` pairs, set
    bidirectionally. Returns the number of pairs made.

    Random pairing is the wrong shape for a grown galaxy: the interesting thing
    to do is span the voids the noise prune created, which turns a wall into a
    door. This is the faithful port; spanning is a map-level decision.
    """
    from . import model

    eligible = [s for s in stars if not s.get("wormHoleToStarId")]
    rng.shuffle(eligible)
    pairs = math.floor(len(stars) / 2.0 / 100.0 * percentage)
    made = 0
    for index in range(pairs):
        a, b = index * 2, index * 2 + 1
        if b >= len(eligible):
            break
        model.link_wormhole(eligible[a], eligible[b])
        made += 1
    return made


# --------------------------------------------------------------------------
# Fronts
#
# Not upstream at all. The idea: a player's game is shaped less by how much is
# near them than by how many directions they can be attacked from. On a grown
# map that number is an accident - measured over six seeds, `irregular` seats 9%
# of players with a single neighbouring capital and 6% with six. Distance to the
# nearest rival is identical for everyone, so the usual isolation check sees
# nothing wrong; the asymmetry is in the *topology*, and it is invisible.
#
# Fronts make it deliberate instead. Decide which capital-to-capital corridors
# are open and which are walled, hold the *count* of open fronts equal across
# players, and let *which* directions differ. Every player then has the same
# number of ways in - the same amount of game to play - while facing a different
# situation. That is the thing a rotationally symmetric map cannot do.
# --------------------------------------------------------------------------


def capital_graph(capitals: Sequence[Point], tolerance: float = 1.05
                  ) -> list[tuple[int, int]]:
    """Which capitals are lattice neighbours. Edges as index pairs, i < j.

    Takes the shortest capital-to-capital distance as the lattice pitch and
    calls anything within `tolerance` of it an edge. On the triangular lattice
    the generators grow capitals on, that is exact rather than a heuristic.
    """
    if len(capitals) < 2:
        return []
    pitch = min(geometry.dist(a, b)
                for i, a in enumerate(capitals) for b in capitals[i + 1:])
    return [(i, j) for i, a in enumerate(capitals)
            for j, b in enumerate(capitals) if i < j
            and geometry.dist(a, b) <= pitch * tolerance]


def front_plan(capitals: Sequence[Point], rng: generate.Rng,
               target_open: int = 3, tolerance: float = 1.05,
               restarts: int = 200) -> dict:
    """Choose which corridors stay open, keeping the count per player even.

    This is a degree-constrained subgraph problem: pick a set of edges in which
    every capital has `target_open` of them. A perfect answer needs the graph to
    have a `target_open`-factor, and it usually does not - a capital the growth
    left with two lattice neighbours cannot have three open fronts however the
    edges are chosen. So this gets as close as the graph allows and reports the
    gap rather than pretending.

    Greedy with a repair pass: shuffle the edges, take any whose endpoints both
    still have room, then walk the under-served capitals and give them any
    remaining edge that does not push its other end over. What is left over is
    genuine and shows up in `shortfall`.

    Returns `open`, `closed`, `degree` (open fronts per capital), `shortfall`
    (capitals that missed a target they could have reached), `capped` (capitals
    with too few lattice neighbours to reach it at all) and `balanced`.

    **Pair it with `irregular_n_limit`.** Plain `irregular` produces capitals
    with one neighbour, and one neighbour is a hard ceiling on open fronts -
    no edge choice recovers it. The n-limit generator bounds the degree at
    source, which is what makes an even plan reachable.
    """
    edges = capital_graph(capitals, tolerance)
    ceiling = [sum(1 for a, b in edges if node in (a, b))
               for node in range(len(capitals))]

    def attempt() -> tuple[list[tuple[int, int]], list[int]]:
        degree = [0] * len(capitals)
        chosen: list[tuple[int, int]] = []
        order = list(edges)
        rng.shuffle(order)
        for i, j in order:
            if degree[i] < target_open and degree[j] < target_open:
                chosen.append((i, j))
                degree[i] += 1
                degree[j] += 1
        # Repair: hand any remaining edge to an under-served capital.
        for _ in range(2):
            for node in range(len(capitals)):
                while degree[node] < target_open:
                    spare = next(((i, j) for i, j in edges
                                  if (i, j) not in chosen and node in (i, j)
                                  and degree[i] < target_open
                                  and degree[j] < target_open), None)
                    if spare is None:
                        break
                    chosen.append(spare)
                    degree[spare[0]] += 1
                    degree[spare[1]] += 1
        return chosen, degree

    def cost(degree: list[int]) -> tuple[int, int]:
        # Capitals short of the target, then total shortfall - and only counting
        # capitals that *could* have reached it. A capital with two lattice
        # neighbours cannot have three open fronts however the edges are picked,
        # so counting it as a failure would make every plan look equally bad and
        # hide the ones that are genuinely leaving room on the table.
        missed = [max(0, min(target_open, ceiling[n]) - degree[n])
                  for n in range(len(capitals))]
        return sum(1 for m in missed if m), sum(missed)

    # A single greedy pass strands capitals whose neighbours all filled up first
    # - on an eight-player map it left one with a single open front while three
    # of its edges went unused. The selection is cheap and the graph is tiny, so
    # rather than a cleverer algorithm this just tries many shuffles and keeps
    # the best. Deterministic, because the shuffles come from the seeded stream.
    best, best_degree = attempt()
    best_cost = cost(best_degree)
    for _ in range(restarts - 1):
        candidate, degrees = attempt()
        if cost(degrees) < best_cost:
            best, best_degree, best_cost = candidate, degrees, cost(degrees)
    chosen, degree = best, best_degree

    shortfall, _ = cost(degree)
    capped = sum(1 for n in range(len(capitals)) if ceiling[n] < target_open)
    return {
        "open": chosen,
        "closed": [e for e in edges if e not in chosen],
        "degree": degree,
        "shortfall": shortfall,
        "capped": capped,
        "balanced": shortfall == 0,
        "edges": edges,
    }


def corridor_bias(capitals: Sequence[Point], closed: Sequence[tuple[int, int]], *,
                  width: float, strength: float = 1.0, reach: float = 0.5,
                  waviness: float = 0.0, field: generate.Noise | None = None,
                  wavelength: float = 260.0):
    """A bias field that hollows out the walled corridors. Pairs with `front_plan`.

    Hand the result to `generate.irregular(..., front_bias=...)`, where the noise
    prune adds it to each candidate's score. Points in the middle of a closed
    corridor score high, get deleted first, and the gap between those two
    capitals becomes a void.

    This is the only honest way to wall a front. Solaris has no impassable
    terrain - a nebula changes scanning and combat but nothing stops a carrier
    flying through it - so the only real barrier is an absence of stars, and the
    only way to get one where you want it is to aim the prune. Terrain then
    *labels* the wall so a player can see it (a nebula belt along the edge of the
    void reads as a frontier), but the terrain is decoration and the void is the
    mechanism.

    `width` is how wide the corridor is in world units; `reach` is the fraction
    of the corridor's length it covers, centred on the midpoint, so the ends stay
    populated and each capital keeps its own neighbourhood. `strength` scales the
    bias against the noise field, which runs -1..1 - at 1.0 a corridor centre
    outweighs almost any noise value.

    **`waviness` is the interesting parameter.** At 0 the corridor is a straight
    segment, and a straight void has smooth edges: measured over a hundred maps,
    planning fronts this way cost a third of the galaxy's chokepoints, because
    the narrow necks that make a map defensible come from *irregular* voids and a
    ruled line produces none. Above 0 the centre line is displaced sideways by
    `waviness * width` times a noise field sampled along the corridor, so the void
    snakes. It walls the same front and leaves a ragged edge behind it.

    Pass a `field` (any `generate.Noise`) when `waviness` is set; each corridor
    samples it along its own length, offset by its index so no two corridors get
    the same wiggle.
    """
    segments = [(capitals[i], capitals[j]) for i, j in closed]

    def bias(point: Point) -> float:
        worst = 0.0
        for index, (a, b) in enumerate(segments):
            abx, aby = b[0] - a[0], b[1] - a[1]
            length_sq = abx * abx + aby * aby
            if length_sq <= 0.0:
                continue
            # Where the point projects onto the corridor, 0 at a and 1 at b.
            t = ((point[0] - a[0]) * abx + (point[1] - a[1]) * aby) / length_sq
            if abs(t - 0.5) > reach / 2.0:
                continue                    # near an endpoint; leave it alone
            px, py = a[0] + abx * t, a[1] + aby * t
            if waviness and field is not None:
                # Signed perpendicular offset, so the centre line can move to
                # either side rather than the corridor just getting fatter.
                length = math.sqrt(length_sq)
                nx, ny = -aby / length, abx / length
                lateral = (point[0] - px) * nx + (point[1] - py) * ny
                centre = waviness * width * field(t * length / wavelength,
                                                 index * 3.7)
                gap = abs(lateral - centre)
            else:
                gap = math.hypot(point[0] - px, point[1] - py)
            if gap >= width:
                continue
            # Full strength on the centre line, tapering to nothing at `width`.
            worst = max(worst, strength * (1.0 - gap / width))
        return worst

    return bias


def balance_terrain(stars: Sequence[dict], capitals: Sequence[dict],
                    horizon: float, field_name: str, *,
                    tolerance: float = 1.0, max_moves: int = 400,
                    preserve: str = "scatter") -> dict:
    """Even out how much of one terrain each player has nearby, in place.

    The fairness lever that `terrain_from_noise` needs, and it needs one badly.
    A wide noise field is what makes terrain arrive in belts instead of specks -
    that is the entire point of using a field - but a belt is a big object, and a
    big object lands *somewhere*. Measured on the default map, painting 15%
    nebula from a wide field gave one player 2 within three jumps and another 32.
    The texture worked and the fairness broke, in the same step, for the same
    reason.

    Nudging is not available here the way it is for resources: terrain is a
    boolean, so the only move is to take it off one star and put it on another.
    This does that as a trade. Repeatedly: find the best-served and worst-served
    player, strip the terrain from whichever of the leader's stars has the
    *fewest* terrain neighbours, and grant it to a star near the trailer that has
    the *most*. Both halves of that choice protect the belts - it removes from
    the ragged edge and grows the densest front - so the terrain stays regional
    while the counts converge.

    `preserve` decides which shape the trade protects, and the two are mirror
    images of each other:

    - `"scatter"` (default) keeps features spread out - it takes from whichever
      of the leader's examples has the *most* neighbours of its kind, and gives
      to the star near the trailer with the *fewest*. Special features read as
      individual landmarks rather than as regions, which is how Solaris itself
      places them and how they are easiest to play around.
    - `"belts"` keeps features contiguous - the exact opposite choice at both
      ends. Only worth using with `terrain_from_noise`, which puts terrain in
      regions in the first place.

    Balancing scattered terrain is cheap because uniform placement is already
    close to even; balancing belts fights the field that made them.

    Stops when the spread is inside `tolerance` (a fraction of the mean) or when
    no legal move is left. Skips home stars, and will not put a warp gate on a
    dead star. Returns the counts per player and how many moves it took.
    """
    if preserve not in ("scatter", "belts"):
        raise ValueError(f"preserve must be 'scatter' or 'belts', not {preserve!r}")
    if not capitals:
        return {"counts": [], "moves": 0}

    def nearby(index: int) -> list[dict]:
        here = geometry.star_point(capitals[index])
        return [s for s in stars if not s.get("homeStar")
                and geometry.dist(here, geometry.star_point(s)) <= horizon]

    pools = [nearby(i) for i in range(len(capitals))]
    neighbourhood = max(rules.MIN_STAR_SEPARATION * 2.5, 1.0)

    def terrain_neighbours(star: dict) -> int:
        here = geometry.star_point(star)
        return sum(1 for s in stars if s is not star and s.get(field_name)
                   and geometry.dist(here, geometry.star_point(s)) <= neighbourhood)

    moves = 0
    for _ in range(max_moves):
        counts = [sum(1 for s in pool if s.get(field_name)) for pool in pools]
        mean = sum(counts) / len(counts)
        if not mean or (max(counts) - min(counts)) / mean <= tolerance:
            break
        richest = counts.index(max(counts))
        poorest = counts.index(min(counts))

        # Strip from the leader's most isolated example - the one whose loss
        # costs the least clustering.
        givers = [s for s in pools[richest] if s.get(field_name)
                  and not any(s in pools[i] for i in range(len(pools))
                              if i != richest and counts[i] <= mean)]
        givers = givers or [s for s in pools[richest] if s.get(field_name)]
        if not givers:
            break
        # Belts: strip the most isolated example, so the belt keeps its core.
        # Scatter: strip the most crowded one, so clumps get broken up.
        giver = (min(givers, key=terrain_neighbours) if preserve == "belts"
                 else max(givers, key=terrain_neighbours))

        # Grant to the trailer's star with the most terrain already around it,
        # so the belt grows rather than a speck appearing.
        takers = [s for s in pools[poorest] if not s.get(field_name)]
        if field_name == "warpGate":
            takers = [s for s in takers if not rules.is_dead_star(s)]
        if not takers:
            break
        taker = (max(takers, key=terrain_neighbours) if preserve == "belts"
                 else min(takers, key=terrain_neighbours))

        giver[field_name] = False
        taker[field_name] = True
        moves += 1

    counts = [sum(1 for s in pool if s.get(field_name)) for pool in pools]
    return {"counts": counts, "moves": moves}


def pair_wormholes(stars: Sequence[dict], capitals: Sequence[dict],
                   closed: Sequence[tuple[int, int]], *,
                   near: float, rng: generate.Rng | None = None) -> list[tuple[str, str]]:
    """Put one wormhole across each walled corridor. Pairs with `front_plan`.

    A walled front is a void, and a void is a dead end. That is fine for one or
    two of a player's borders and dull for all of them - the wall removes a whole
    direction from the game rather than changing what happens there. A wormhole
    across it puts the direction back as a **single fixed crossing**: everyone
    knows where it is, it cannot be widened, and whoever holds both ends controls
    it. A chokepoint is a better border than a wall.

    One pair per walled corridor, each end on the nearest ordinary star to the
    capital on its own side of the gap. Since `front_plan` already equalises how
    many corridors each player has open, it equalises the walled ones too, so
    endpoints come out even without a separate balancing pass - which is the
    point of doing this after the front plan rather than at random.

    `near` is how close to a capital an endpoint may sit; keep it under the
    opening jump so the crossing is usable from turn one. Skips home stars and
    anything already holding a wormhole. Returns the pairs it made.
    """
    from . import model

    taken: set[str] = {s["id"] for s in stars if s.get("wormHoleToStarId")}
    made: list[tuple[str, str]] = []

    def endpoint(capital: dict) -> dict | None:
        here = geometry.star_point(capital)
        options = [s for s in stars
                   if not s.get("homeStar") and s["id"] not in taken
                   and geometry.dist(here, geometry.star_point(s)) <= near]
        if not options:
            return None
        if rng is not None:
            rng.shuffle(options)
        return min(options, key=lambda s: geometry.dist(here, geometry.star_point(s)))

    for i, j in closed:
        if i >= len(capitals) or j >= len(capitals):
            continue
        a, b = endpoint(capitals[i]), endpoint(capitals[j])
        if a is None or b is None or a["id"] == b["id"]:
            continue
        model.link_wormhole(a, b)
        taken.add(a["id"])
        taken.add(b["id"])
        made.append((a["id"], b["id"]))
    return made


def balance_openings(stars: Sequence[dict], capitals: Sequence[dict],
                     reach: float, *, tolerance: float = 0.6,
                     max_swaps: int = 60, search_radius: float = 2.5) -> dict:
    """Even out how many neutral stars each player can reach on turn one.

    The most consequential fairness metric on a grown map, and the one with the
    least obvious lever. How much frontier a player opens with depends on the
    star density around their pod, which is decided by a noise field nobody
    controls; at the game's own lattice pitch the count runs from about 2 to
    about 9 across players, a spread of roughly 1.4.

    Moving stars to fix it would fight the separation floor and the
    pull-into-range pass. But **which** stars a player starts with is free. The
    generator hands out the nearest ones, and nearest is not the only legal
    choice: swapping one pod star for another nearby star changes nothing about
    the galaxy and can change a player's opening frontier substantially, because
    a pod star at the edge of a cluster sees much more than one in the middle.

    So: repeatedly take the worst-served player and try every swap of one
    non-capital pod star for a neutral star still within `reach` of the rest of
    their pod, keeping whichever swap opens the most frontier. Stop when the
    spread is inside `tolerance`, when no swap helps, or after `max_swaps`.

    Ownership only - no star moves. The two stars exchange their resources along
    with the ownership, so a player's opening total is exactly unchanged and a
    fixed, identical opening survives this pass. The pod stays connected at the
    starting jump because every candidate must be in reach of what remains.
    Returns the counts per player and the swaps made.
    """
    from . import geometry as geo

    def pod_of(capital):
        return [s for s in stars if s.get("playerId") == capital["playerId"]]

    def options(pod):
        return sum(1 for s in geo.reachable_from_any(pod, stars, reach)
                   if s.get("playerId") is None)

    def connected(pod, capital):
        """Can the player fly to every star in this pod, hopping through it?

        The pod is a chain, not a star, so dropping one member can strand
        everything behind it - checking only that the *incoming* star is
        reachable is not enough, and produces pods a player cannot use.
        """
        seen = [capital]
        rest = [s for s in pod if s is not capital]
        changed = True
        while changed:
            changed = False
            for star in list(rest):
                if any(geo.dist(geo.star_point(star), geo.star_point(k)) <= reach
                       for k in seen):
                    seen.append(star)
                    rest.remove(star)
                    changed = True
        return not rest

    swaps = 0
    for _ in range(max_swaps):
        pods = [pod_of(c) for c in capitals]
        counts = [options(p) for p in pods]
        mean = sum(counts) / len(counts)
        if not mean or (max(counts) - min(counts)) / mean <= tolerance:
            break
        worst = counts.index(min(counts))
        capital = capitals[worst]
        pod = pods[worst]
        movable = [s for s in pod if not s.get("homeStar")]
        # Only stars near the pod are worth trying: a swap has to leave the pod
        # connected, so anything beyond a couple of jumps can never qualify, and
        # scanning the whole galaxy for each swap is what made this the slowest
        # thing in the toolkit.
        limit = reach * search_radius
        candidates = [s for s in stars
                      if s.get("playerId") is None and not s.get("homeStar")
                      and any(geo.dist(geo.star_point(s), geo.star_point(k)) <= limit
                              for k in pod)]

        best = None
        for drop in movable:
            keep = [s for s in pod if s is not drop]
            for take in candidates:
                # The incoming star must be reachable from what the pod keeps,
                # or the player starts with something they cannot fly to.
                if not any(geo.dist(geo.star_point(take), geo.star_point(k)) <= reach
                           for k in keep):
                    continue
                if not connected(keep + [take], capital):
                    continue
                score = options(keep + [take])
                if best is None or score > best[0]:
                    best = (score, drop, take)
        if best is None or best[0] <= counts[worst]:
            break

        _, drop, take = best
        # Exchange the resources along with the ownership, not just the flag.
        # A pod star carries whatever fixed value the builder gave it, and the
        # incoming neutral carries a rolled one; hand the incoming star the
        # pod's profile and give its own to the star leaving the pod. The
        # player's opening total is then exactly what it was, which is the
        # invariant every other fairness pass here is built to preserve.
        take["naturalResources"], drop["naturalResources"] = (
            drop["naturalResources"], take["naturalResources"])
        take["playerId"] = capital["playerId"]
        take["shipsActual"], take["ships"] = drop["shipsActual"], drop["ships"]
        drop["playerId"] = None
        drop["shipsActual"] = 0
        drop["ships"] = 0
        swaps += 1

    counts = [options(pod_of(c)) for c in capitals]
    return {"counts": counts, "swaps": swaps}


def balance_vision(stars: Sequence[dict], capitals: Sequence[dict],
                   base_scanning: int) -> dict:
    """Guarantee every player one black hole in their starting pod. Not upstream.

    A black hole is worth +3 scanning (`rules.BLACK_HOLE_SCANNING_BONUS`), which
    at scanning 3 is the difference between seeing 200 units and seeing 350 - by
    far the largest single lever on what a player can see at tick 0. Scattered at
    a few percent of stars they land where they land, so some players open with
    one and most do not, and that is a bigger information asymmetry than anything
    the resource passes touch.

    So hand each player exactly one, converting a non-capital star they already
    own rather than adding stars or moving anything. Exactly one each is the
    point: it is the only distribution that is provably equal, and it costs
    nothing to guarantee because the pod is already theirs.

    Capitals are left alone - a black hole capital would put every player's most
    valuable star under a permanent modifier and change the opening for reasons
    that have nothing to do with vision. Returns how many were granted and how
    many players already had one.
    """
    granted = already = 0
    for capital in capitals:
        pod = [s for s in stars if s.get("playerId") == capital["playerId"]]
        if any(s.get("isBlackHole") for s in pod):
            already += 1
            continue
        options = [s for s in pod if not s.get("homeStar")]
        if not options:
            continue
        # The pod star furthest from home sees most new sky.
        here = geometry.star_point(capital)
        chosen = max(options, key=lambda s: geometry.dist(here, geometry.star_point(s)))
        chosen["isBlackHole"] = True
        granted += 1
    return {"granted": granted, "already_had": already,
            "base_scanning": base_scanning}


def pair_wormholes_evenly(stars: Sequence[dict], capitals: Sequence[dict], *,
                          near: float, pairs: int | None = None,
                          rng: generate.Rng | None = None) -> list:
    """One wormhole endpoint per player, paired across the field. Not upstream.

    Wormholes are the most dangerous object on a generated map, because a
    traversed wormhole costs exactly **one tick regardless of distance**. A
    player who happens to have one near their pod can touch a rival on the far
    side of the galaxy immediately; a player without one takes forty ticks to
    reach anybody. Scattered at random - which is what the game does, and what
    `link_wormholes` reproduces - that is pure luck, and it is by far the largest
    unfairness this toolkit has measured. On a 32-player map, random placement
    took the spread in time-to-first-contact from 1.6 to 5.4 and the spread in
    capital exposure from 1.3 to 2.2, losing to plain random generation on
    essentially every seed.

    So place them deliberately and **sparingly**. `pairs` caps how many are made;
    each takes an endpoint near one player's pod and joins it to a player far
    across the list, so a wormhole is a long jump rather than a local shortcut.
    Which players get one rotates with the seed, so it is not always the same
    seats.

    **A wormhole is flair, not a repair.** It is tempting to lean on them to fix
    a geometric problem - reachability, contested ground out of range - because
    one wormhole moves those numbers a long way. That is the wrong use: it fixes
    the statistic by adding an exception rather than by fixing the layout, and
    every wormhole is one more piece of the map whose behaviour a player cannot
    read off its position. Set `pairs` low, and only raise it if a measurement
    says the map needs it.

    Returns the pairs made. Run it *instead of* `link_wormholes`, not after it.
    """
    from . import model

    taken: set[str] = {s["id"] for s in stars if s.get("wormHoleToStarId")}
    order = list(range(len(capitals)))
    if rng is not None:
        rng.shuffle(order)
    wanted = len(capitals) if pairs is None else min(pairs * 2, len(capitals))
    # Rotate which seats get one, rather than always the first few.
    chosen_seats = sorted(order[:wanted])
    endpoints = []
    for seat, capital in enumerate(capitals):
        if seat not in chosen_seats:
            endpoints.append(None)
            continue
        here = geometry.star_point(capital)
        options = [s for s in stars
                   if not s.get("homeStar") and s["id"] not in taken
                   and geometry.dist(here, geometry.star_point(s)) <= near]
        if not options:
            endpoints.append(None)
            continue
        if rng is not None:
            rng.shuffle(options)
        chosen = min(options, key=lambda s: geometry.dist(here, geometry.star_point(s)))
        taken.add(chosen["id"])
        endpoints.append(chosen)

    # Pair the endpoints that exist with each other, not by seat index - capping
    # the count leaves most seats empty, and pairing seat i with seat i+half then
    # silently produces almost no wormholes at all.
    live = [e for e in endpoints if e is not None]
    made = []
    half = len(live) // 2
    for index in range(half):
        a, b = live[index], live[index + half]
        if a["id"] == b["id"]:
            continue
        model.link_wormhole(a, b)
        made.append((a["id"], b["id"]))
    return made
