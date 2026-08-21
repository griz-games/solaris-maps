"""Procedural galaxy layouts - the editor's six generators, in Python.

Everything in `geometry` and in `maps/spy_v_spy.py` assumes symmetry: a wedge is
built once and rotated, and fairness follows from congruence. This module is the
other half. It grows a galaxy that has no symmetry at all and makes it fair by
construction and by measurement instead - which is how Solaris's own galaxies are
built, and how the editor's Generate menu builds one.

Ported from `src/scripts/generators/*.ts` in
IHateAttackMaps/solaris-custom-galaxy-editor. Provenance comments name the
upstream file and function. Two upstream npm dependencies have no standard
library equivalent and are reimplemented here:

    simplex-noise   `noise2d` below - the same algorithm, a permutation table
                    shuffled out of the seeded stream, so it behaves the same.
    random-seed     `Rng` below wraps `random.Random` instead of GRC's UHE PRNG.

Both are structurally faithful and neither is bit-compatible, so **a seed here
reproduces this module's galaxy, not the editor's**. Reproducibility is within
this repo, which is what the determinism regression actually needs.

Two upstream bugs are deliberately not reproduced, and both are noted at the
site: `helper.getClosestLocations` excludes candidates sharing *either*
coordinate with the reference rather than excluding the reference itself, and
`irregular.ts::_generateHomeLocations` evaluates its noise rejection inside the
loop over existing homes, so it cannot fire for the first one.

A layout is not a map. This module emits points and says who starts where;
turning that into stars is `model`'s job and picking the resource curve is the
builder's. See `maps/irregular.py` for the whole loop.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from . import geometry, rules

Point = tuple[float, float]
Noise = Callable[[float, float], float]

TAU = 2.0 * math.pi
_SIXTH_TAU = TAU / 6.0


# --------------------------------------------------------------------------
# Randomness
# --------------------------------------------------------------------------


class Rng:
    """A deterministic random stream, seeded from a string.

    The surface mirrors the editor's `util/seededRandomGen.ts` so the generators
    below read like their originals: `integer` and `between` are **inclusive** on
    both ends, matching `getRandomNumber` and `getRandomNumberBetween`.

    The editor wraps npm `random-seed`; this wraps `random.Random`. Same
    contract, different numbers - see the module docstring.
    """

    def __init__(self, seed: str | int | None = None) -> None:
        # An unseeded generator still records the seed it chose, so a run that
        # produced a galaxy worth keeping can be reproduced from its report.
        if seed is None:
            seed = str(random.Random().getrandbits(53))
        self.seed = str(seed)
        self._rng = random.Random(self.seed)

    def random(self) -> float:
        """A float in [0, 1)."""
        return self._rng.random()

    def integer(self, maximum: int) -> int:
        """An integer in [0, maximum], both ends inclusive."""
        return self._rng.randint(0, maximum)

    def between(self, minimum: int, maximum: int) -> int:
        """An integer in [minimum, maximum], both ends inclusive."""
        return self._rng.randint(minimum, maximum)

    def angle(self) -> float:
        """A bearing in radians, [0, TAU)."""
        return self._rng.random() * TAU

    def shuffle(self, items: list) -> None:
        self._rng.shuffle(items)

    def __repr__(self) -> str:
        return f"Rng({self.seed!r})"


# --------------------------------------------------------------------------
# Noise
#
# 2D simplex noise. The editor calls `createNoise2D(rand.random)` from npm
# simplex-noise, which builds its permutation table by shuffling with the
# supplied random function; this does the same with `Rng.shuffle`.
# --------------------------------------------------------------------------

_F2 = 0.5 * (math.sqrt(3.0) - 1.0)
_G2 = (3.0 - math.sqrt(3.0)) / 6.0

# The twelve 2D gradients simplex-noise uses, projected from the classic 3D set.
_GRAD2 = (
    (1.0, 1.0), (-1.0, 1.0), (1.0, -1.0), (-1.0, -1.0),
    (1.0, 0.0), (-1.0, 0.0), (1.0, 0.0), (-1.0, 0.0),
    (0.0, 1.0), (0.0, -1.0), (0.0, 1.0), (0.0, -1.0),
)


def noise2d(rng: Rng) -> Noise:
    """A 2D simplex noise field, values in roughly [-1, 1].

    Deterministic for a given `Rng`, and continuous - which is the whole point.
    A galaxy pruned against white noise looks like static; pruned against this,
    it grows connected voids and connected clusters, because neighbouring points
    get similar values.

    Call it with coordinates already divided by a spread: a larger spread means
    larger, smoother features. See `noise_spread` for the editor's scaling.
    """
    perm = list(range(256))
    rng.shuffle(perm)
    perm = perm + perm                          # doubled so index wrapping is free
    perm12 = [p % 12 for p in perm]

    def noise(x: float, y: float) -> float:
        # Skew the input onto the simplex lattice, and find which of the two
        # triangles in this cell the point landed in.
        skew = (x + y) * _F2
        i = math.floor(x + skew)
        j = math.floor(y + skew)
        unskew = (i + j) * _G2
        x0 = x - (i - unskew)
        y0 = y - (j - unskew)
        i1, j1 = (1, 0) if x0 > y0 else (0, 1)

        corners = (
            (x0, y0, perm12[(i & 255) + perm[j & 255]]),
            (x0 - i1 + _G2, y0 - j1 + _G2,
             perm12[((i + i1) & 255) + perm[(j + j1) & 255]]),
            (x0 - 1.0 + 2.0 * _G2, y0 - 1.0 + 2.0 * _G2,
             perm12[((i + 1) & 255) + perm[(j + 1) & 255]]),
        )

        total = 0.0
        for dx, dy, gi in corners:
            falloff = 0.5 - dx * dx - dy * dy
            if falloff > 0.0:
                gx, gy = _GRAD2[gi]
                falloff *= falloff
                total += falloff * falloff * (gx * dx + gy * dy)
        return 70.0 * total                     # scales the sum into [-1, 1]

    return noise


# `const SPREAD = 2.5`, hardcoded inside generateLocations in **both**
# server/services/maps/irregular.ts (the game) and the editor's port of it. This
# is the value a real Solaris match uses, and it is the default here.
EDITOR_SPREAD = 2.5
GAME_SPREAD = EDITOR_SPREAD          # same constant; the game is the authority

_MIN_SPREAD = 1.15                   # below this the pitch closes on the floor


def fit_spread(hyperspace: int, separation: float = rules.MIN_STAR_SEPARATION,
               headroom: float = 0.8) -> float:
    """A tighter lattice pitch, for authors who want a denser galaxy. **Optional.**

    Solves for the pitch at which lattice ring 2 sits inside a single jump:

        L * (2.5 * spread - 0.5) <= hyperspace_range(hyperspace),  L = separation * 0.75

    discounted by `headroom` for the ring-2 slots the noise prune deletes. At the
    standard 50u separation it gives about 1.23 at hyperspace 1 and 1.65 at 2,
    against the game's 2.5.

    **This is a preference, not a correction, and an earlier version of this file
    said otherwise.** The claim was that the game's 2.5 leaves players with no
    reachable neutral star on turn one. That was measured wrongly - from the
    capital alone, when a player starts with several stars and may launch from
    any of them. Measured correctly at the official `standard.json` settings
    (irregular, 10 players, 20 stars each, 6 starting stars, hyperspace 1), the
    game's own value strands nobody:

        spread   pitch    reachable neutrals per player      galaxy joins up at
        1.23     46u      min 14, median 20                  hyperspace 2
        1.60     60u      min  9, median 14                  hyperspace 2
        2.50     94u      min  2, median  5   <- the game    hyperspace 5

    So what a lower spread buys is a *denser, better connected* galaxy with more
    opening choices - a different map, not a fixed one. The game's value is the
    default because the game is the reference; reach for this when you want the
    denser variant and have decided you want it.
    """
    lattice = separation * 0.75
    cap = (rules.hyperspace_range(hyperspace) / lattice + 0.5) / 2.5
    return min(max(cap * headroom, _MIN_SPREAD), EDITOR_SPREAD)


def noise_spread(stars_per_player: float, base: float = 32.0) -> float:
    """How wide the noise features should be for a galaxy of this density.

    irregular.ts: `NOISE_BASE_SPREAD * ((STARS_PER_PLAYER + 20) / 9.0)`. Voids
    then scale with the galaxy instead of staying a fixed size, so a 40-stars-
    per-player map does not end up as lace.
    """
    return base * ((stars_per_player + 20.0) / 9.0)


# --------------------------------------------------------------------------
# Points
# --------------------------------------------------------------------------


def _rotate(point: Point, radians: float) -> Point:
    """Rotate about the origin. Radians, not degrees.

    `geometry.rotate` takes degrees, which is right for hand-placed geometry.
    Everything here steps in sixths of a turn, so radians avoid a conversion on
    every lattice step. The editor's `_rotatedLocation` negates its angle, which
    only mirrors the galaxy; this does not, and nothing downstream cares.
    """
    ca, sa = math.cos(radians), math.sin(radians)
    return point[0] * ca - point[1] * sa, point[0] * sa + point[1] * ca


def _add(a: Point, b: Point) -> Point:
    return a[0] + b[0], a[1] + b[1]


def _polar(radius: float, radians: float) -> Point:
    return radius * math.cos(radians), radius * math.sin(radians)


def hex_rings(base: Point, ring_count: int, distance: float) -> list[Point]:
    """Concentric hexagonal rings of points around `base`, on a triangular grid.

    irregular.ts::_generateConcentricHexRingsLocations. The outer ring is
    deliberately incomplete - only three of its six edges, and two of its corners
    - so that rings grown around adjacent centres tile without overlapping. Those
    numbers are structural, not tuning.
    """
    out: list[Point] = []
    for ring in range(ring_count):
        for slice_index in range(6):
            if ring == ring_count - 1 and slice_index < 3:
                continue                        # outer ring keeps its first 3 edges only
            corner = _add(base, _rotate((distance * (ring + 1), 0.0),
                                        slice_index * _SIXTH_TAU))
            if ring != ring_count - 1 or slice_index in (3, 4):
                out.append(corner)              # outer ring keeps 2 of its corners
            for step in range(ring):
                out.append(_add(corner, _rotate((distance * (step + 1), 0.0),
                                                (slice_index + 2) * _SIXTH_TAU)))
    return out


def jitter(points: Sequence[Point], threshold: float, rng: Rng) -> list[Point]:
    """Displace every point by 0.75-1.0 x `threshold` at a random bearing.

    irregular.ts::_randomlyDislocateLocations. This is what stops a generated
    galaxy from reading as a lattice: the hex grid does the spacing work, and
    then every star is knocked off it far enough that no row survives.
    """
    out = []
    for point in points:
        amount = threshold * (0.75 + 0.25 * rng.random())
        out.append(_add(point, _polar(amount, rng.angle())))
    return out


def metaball_field(point: Point, centres: Sequence[Point], radius: float,
                   falloff: float = 8.0) -> float:
    """Summed field strength at `point` from a blob around each centre.

    irregular.ts::_pruneLocationsOutsideMetaball, `sum((radius / d) ** falloff)`.
    At 1.0 the point is inside the union of the blobs. The high exponent makes
    the edge sharp, so the galaxy gets a definite outline that still bulges where
    two players sit close together - that bulge is the whole reason to use a
    metaball rather than a circle.
    """
    total = 0.0
    for centre in centres:
        gap = geometry.dist(centre, point)
        if gap <= 0.0:
            return math.inf
        total += (radius / gap) ** falloff
        if total >= 1.0:
            return total                        # saturated; also caps the exponent
    return total


def prune_by_noise(points: Sequence[Point], keep: int, noise: Noise,
                   spread: float, bias: Callable[[Point], float] | None = None
                   ) -> list[Point]:
    """Keep the `keep` points sitting lowest in the noise field.

    irregular.ts::_pruneLocationsWithNoise. Because the field is continuous, the
    points that go are contiguous, and what is left has voids with shape rather
    than uniform thinning. Order is preserved among the survivors so the result
    does not depend on sort stability across versions.

    `bias` adds to a point's score before sorting, which is how a caller aims the
    voids somewhere in particular instead of taking whatever the noise gives.
    Positive means "delete here first". `randomise.corridor_bias` uses it to open
    and close the fronts between capitals; anything that wants a void in a chosen
    place goes through here rather than deleting points itself, so the star count
    still comes out exactly right.
    """
    if keep >= len(points):
        return list(points)
    def score(point: Point) -> float:
        value = noise(point[0] / spread, point[1] / spread)
        return value + (bias(point) if bias else 0.0)
    scored = sorted(enumerate(points), key=lambda pair: score(pair[1]))
    survivors = sorted(index for index, _ in scored[:keep])
    return [points[index] for index in survivors]


def field_bias(field: Noise, spread: float, strength: float = 1.0,
               offset: Point = (0.0, 0.0)) -> Callable[[Point], float]:
    """Turn any noise field into a prune bias for `prune_by_noise`.

    A second, independent field layered onto the one the generator already uses.
    The first field decides the galaxy's voids; adding a second at a different
    scale and offset means density stops being the product of a single wavelength
    - clusters inside clusters, voids with islands in them - which is the
    difference between a galaxy with two kinds of place in it and one with one.

    Positive `strength` deepens where the second field is high. Keep it well below
    1.0: the base field runs -1..1 and the bias adds to it, so a strength near 1
    stops being a modulation and becomes the only thing deciding the outcome.

    Composes by addition - `lambda p: field_bias(...)(p) + corridor_bias(...)(p)`
    layers a designed structure on top of an organic one.
    """
    def bias(point: Point) -> float:
        return strength * field((point[0] + offset[0]) / spread,
                                (point[1] + offset[1]) / spread)
    return bias


def relax_separation(points: list[Point], separation: float,
                     pinned: Sequence[int] = (), rounds: int = 12) -> list[Point]:
    """Push overlapping points apart until they clear `separation`.

    spiral.ts::applyPadding, generalised. Pinned indices never move, which is how
    you keep capitals and their claimed stars where the reachability pass put
    them while still fixing crowding elsewhere. Best effort: it returns after
    `rounds` whether or not it converged, so check the result rather than trusting
    it - `geometry.nearest_neighbour_gaps` is the check.
    """
    out = list(points)
    frozen = set(pinned)
    for _ in range(rounds):
        moved = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                if i in frozen and j in frozen:
                    continue
                dx = out[j][0] - out[i][0]
                dy = out[j][1] - out[i][1]
                gap = math.hypot(dx, dy)
                if gap >= separation:
                    continue
                moved = True
                if gap == 0.0:                  # coincident: pick a direction
                    dx, dy, gap = 1.0, 0.0, 1.0
                push = (separation - gap) / gap
                # Split the correction unless one end is pinned, in which case
                # the free end takes all of it.
                share_i = 0.0 if i in frozen else (1.0 if j in frozen else 0.5)
                share_j = 0.0 if j in frozen else (1.0 if i in frozen else 0.5)
                out[i] = (out[i][0] - dx * push * share_i,
                          out[i][1] - dy * push * share_i)
                out[j] = (out[j][0] + dx * push * share_j,
                          out[j][1] + dy * push * share_j)
        if not moved:
            break
    return out


# --------------------------------------------------------------------------
# The layout
# --------------------------------------------------------------------------


@dataclass
class Layout:
    """A generated star field, and who starts where.

    `homes` and `starting` index into `points`. Deliberately free of anything
    Solaris-shaped: a layout is geometry plus an assignment, and a builder turns
    it into stars with `model.new_star`. Keeping the split means a generator can
    be tested without a validator and a resource curve can be changed without
    regenerating.
    """

    points: list[Point]
    homes: list[int]
    starting: list[list[int]] = field(default_factory=list)
    seed: str = ""
    generator: str = ""

    @property
    def player_count(self) -> int:
        return len(self.homes)

    @property
    def star_count(self) -> int:
        return len(self.points)

    def owners(self) -> dict[int, int]:
        """Point index -> player index, for every point somebody starts on."""
        owned = {home: player for player, home in enumerate(self.homes)}
        for player, claimed in enumerate(self.starting):
            for index in claimed:
                owned[index] = player
        return owned

    def home_points(self) -> list[Point]:
        return [self.points[i] for i in self.homes]


# --------------------------------------------------------------------------
# Shared post-processing
#
# Every generator ends the same way: pick capitals, hand each of them their
# starting stars, and drag those stars close enough that the player can actually
# fly to them on turn one. The editor duplicates this across four generators with
# a `TODO` saying it should be shared; here it is shared.
# --------------------------------------------------------------------------

HOME_DISTRIBUTIONS = ("circular", "random")


def place_homes(points: Sequence[Point], player_count: int, rng: Rng,
                distribution: str = "circular", reach: float | None = None,
                shortlist: int = 12) -> list[int]:
    """Choose which points are capitals, for generators that do not say.

    `circular` spaces ideal capitals evenly around a ring at half the galaxy's
    radius and snaps each onto a real star - even spacing without forcing the
    *layout* symmetric. `random` picks them at random subject to staying as far
    apart as the ring would have put them: less fair, more interesting.

    circular.ts, doughnut.ts and spiral.ts emit no capitals at all; the editor
    applies its `playerDistribution` setting afterwards. This is that step, plus
    one thing the editor does not do. Rejection-sampled fields are uniform in
    expectation and lumpy in fact, so snapping to the single nearest star seats
    somebody in a sparse patch with nowhere to expand about one map in three.
    Given a `reach`, each capital is instead chosen from the `shortlist` stars
    nearest the ideal point, preferring the one with the most neighbours inside
    one jump - which costs a little ring regularity and buys every player an
    opening. Without a `reach` it falls back to plain nearest.
    """
    if distribution not in HOME_DISTRIBUTIONS:
        raise ValueError(f"unknown distribution {distribution!r}; "
                         f"expected one of {HOME_DISTRIBUTIONS}")
    if player_count > len(points):
        raise ValueError(f"{player_count} players will not fit in {len(points)} stars")

    centroid = (sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points))
    # The radius that splits the galaxy in half by star count, not half the
    # outer radius. On a disc the two are close; on a doughnut half the outer
    # radius is *inside the hole*, so every capital snaps onto whatever scraps
    # of inner rim happen to be nearest and the even spacing is lost. Taking the
    # median makes the ring self-tuning for whatever shape the generator made.
    radii = sorted(geometry.dist(centroid, p) for p in points)
    radius = radii[len(radii) // 2]
    homes: list[int] = []

    def neighbours(index: int) -> int:
        assert reach is not None
        here = points[index]
        return sum(1 for other in points if 0.0 < geometry.dist(here, other) <= reach)

    # The chord between adjacent capitals on the ideal ring. Capitals are held
    # this far apart even while trading position for local density, because two
    # capitals that drift together is a worse unfairness than a thin patch: the
    # pair fight each other from turn one while everybody else builds.
    chord = 2.0 * radius * math.sin(math.pi / player_count)
    floor = chord * 0.6

    def clear_of_homes(index: int) -> bool:
        return all(geometry.dist(points[index], points[h]) >= floor for h in homes)

    def best_near(ideal: Point) -> int:
        free = [i for i in range(len(points)) if i not in homes]
        free.sort(key=lambda i: geometry.dist(ideal, points[i]))
        spaced = [i for i in free if clear_of_homes(i)] or free
        if reach is None:
            return spaced[0]
        # Ties on neighbour count fall back to proximity: `spaced` is already in
        # distance order and `max` keeps the first of equals.
        return max(spaced[:shortlist], key=neighbours)

    if distribution == "circular":
        start = rng.angle()                     # so the ring is not always axis-aligned
        for index in range(player_count):
            ideal = _add(centroid,
                         _polar(radius, start + index * TAU / player_count))
            homes.append(best_near(ideal))
        return homes

    # random, but never closer together than the ring would have been
    for _ in range(player_count):
        candidates = [i for i in range(len(points)) if i not in homes]
        rng.shuffle(candidates)
        viable = [i for i in candidates if clear_of_homes(i)]
        if not viable:                          # nothing clears the floor; take the best
            homes.append(max(candidates,
                             key=lambda i: min((geometry.dist(points[i], points[h])
                                                for h in homes), default=math.inf)))
            continue
        homes.append(viable[0] if reach is None
                     else max(viable[:shortlist], key=neighbours))
    return homes


def claim_starting_stars(points: Sequence[Point], homes: Sequence[int],
                         starting_stars: int) -> list[list[int]]:
    """Give every capital its `starting_stars - 1` nearest unclaimed neighbours.

    Round robin, one star per player per pass, so no player is finished before
    another has begun and the draft order costs at most one star of advantage.
    irregular.ts and circularBalanced.ts both do this inline.

    Upstream picks the nearest star with `helper.getClosestLocations`, whose
    self-exclusion filter is `a.x !== loc.x && a.y !== loc.y` - an AND, which
    drops every candidate sharing *either* coordinate with the capital rather
    than dropping the capital itself. Excluding by index instead, as here, is
    both the intent and correct.
    """
    if starting_stars < 1:
        raise ValueError("starting_stars must be at least 1 (the capital itself)")
    claimed: set[int] = set(homes)
    starting: list[list[int]] = [[] for _ in homes]

    for _ in range(starting_stars - 1):
        for player, home in enumerate(homes):
            free = [i for i in range(len(points)) if i not in claimed]
            if not free:
                raise RuntimeError(
                    f"ran out of stars handing player {player} their "
                    f"{starting_stars} starting stars")
            nearest = min(free, key=lambda i: geometry.dist(points[home], points[i]))
            claimed.add(nearest)
            starting[player].append(nearest)
    return starting


def pull_into_range(points: list[Point], homes: Sequence[int],
                    starting: Sequence[Sequence[int]], hyperspace: int) -> list[Point]:
    """Move each player's starting stars until the whole pod is connected.

    irregular.ts, the block after the linking loop. A player whose starting stars
    are scattered beyond their opening jump cannot use them, so each one is
    dragged straight towards the nearest already-reachable star in the pod until
    it is exactly one jump away. Nearest first, so the pod grows outwards and
    each drag is as short as it can be.

    The pulled stars can end up crowding their new neighbours - this pass knows
    nothing about the rest of the galaxy. Follow it with `relax_separation`
    pinning the pods, or check `geometry.nearest_neighbour_gaps` and accept it.
    """
    out = list(points)
    reach = rules.hyperspace_range(hyperspace) - 2.0    # -2 dodges float imprecision

    for home, pod in zip(homes, starting):
        reachable = [home]
        unreachable = list(pod)
        while unreachable:
            # The unreachable star closest to anything already connected.
            best_index, best_anchor, best_gap = None, None, math.inf
            for index in unreachable:
                for anchor in reachable:
                    gap = geometry.dist(out[index], out[anchor])
                    if gap < best_gap:
                        best_index, best_anchor, best_gap = index, anchor, gap
            assert best_index is not None and best_anchor is not None
            if best_gap > reach:
                out[best_index] = _towards(out[best_index], out[best_anchor], reach)
            unreachable.remove(best_index)
            reachable.append(best_index)
    return out


def _towards(point: Point, anchor: Point, min_distance: float) -> Point:
    """Slide `point` along the line to `anchor` until it is `min_distance` away.

    helper.moveLocationTowards - editor helper.ts. A no-op if already closer.
    """
    dx, dy = anchor[0] - point[0], anchor[1] - point[1]
    gap = math.hypot(dx, dy)
    if gap <= min_distance or gap == 0.0:
        return point
    amount = 1.0 - (min_distance / gap)
    return point[0] + dx * amount, point[1] + dy * amount


def _finish(points: list[Point], homes: list[int], starting_stars: int,
            hyperspace: int, seed: str, generator: str) -> Layout:
    """Claim, pull, and package. The tail every generator shares."""
    starting = claim_starting_stars(points, homes, starting_stars)
    points = pull_into_range(points, homes, starting, hyperspace)
    return Layout(points=points, homes=homes, starting=starting,
                  seed=seed, generator=generator)


# --------------------------------------------------------------------------
# The generators
#
# All six take the same arguments and return a Layout, so a builder can swap one
# for another by name. `separation` is the editor's minDistanceBetweenStars.
# --------------------------------------------------------------------------


def circular(player_count: int, stars_per_player: int, *, seed: str | None = None,
             starting_stars: int = 1, hyperspace: int = 1,
             separation: float = rules.MIN_STAR_SEPARATION,
             distribution: str = "circular", **_: object) -> Layout:
    """Uniform stars in a disc. circular.ts.

    Rejection sampling: throw a dart, keep it if it clears `separation`, repeat.
    The density constant is the editor's, and fixes the radius for a given star
    count so galaxies of different sizes feel equally crowded.

    The upstream radius sampler is `getRandomRadius(maxRadius, offset)` with
    offset 0.5, which is `maxRadius * u ** 0.5` - the exponent that makes area
    density uniform. That reading is inferred from the default rather than read
    off the source, so treat `offset` as tunable: below 0.5 crowds the middle.
    """
    rng = Rng(seed)
    star_count = player_count * stars_per_player
    max_radius = _disc_radius(star_count)
    points = _reject_sample(star_count, separation, rng,
                            lambda: _polar(max_radius * rng.random() ** 0.5, rng.angle()))
    homes = place_homes(points, player_count, rng, distribution,
                        reach=rules.hyperspace_range(hyperspace))
    return _finish(points, homes, starting_stars, hyperspace, rng.seed, "circular")


def doughnut(player_count: int, stars_per_player: int, *, seed: str | None = None,
             starting_stars: int = 1, hyperspace: int = 1,
             separation: float = rules.MIN_STAR_SEPARATION,
             distribution: str = "circular", **_: object) -> Layout:
    """Uniform stars in an annulus, inner radius half the outer. doughnut.ts.

    Same sampler as `circular` with the middle cut out, and the radius scaled by
    4/3 to keep the same density over the smaller area. The hole is the point:
    nobody starts in the centre, so there is no single dominant position.
    """
    rng = Rng(seed)
    star_count = player_count * stars_per_player
    max_radius = ((4.0 * star_count) / (3.0 * math.pi * _STAR_DENSITY)) ** 0.5
    min_radius = 0.5 * max_radius

    def sample() -> Point:
        # Uniform over the annulus, not over the radius.
        u = rng.random()
        r = math.sqrt(min_radius ** 2 + u * (max_radius ** 2 - min_radius ** 2))
        return _polar(r, rng.angle())

    points = _reject_sample(star_count, separation, rng, sample)
    homes = place_homes(points, player_count, rng, distribution,
                        reach=rules.hyperspace_range(hyperspace))
    return _finish(points, homes, starting_stars, hyperspace, rng.seed, "doughnut")


def circular_balanced(player_count: int, stars_per_player: int, *,
                      seed: str | None = None, starting_stars: int = 1,
                      hyperspace: int = 1,
                      separation: float = rules.MIN_STAR_SEPARATION,
                      **_: object) -> Layout:
    """One sector, rotated into all of them. circularBalanced.ts.

    The odd one out in this module: the only generator here that produces a
    *symmetric* galaxy. Every star is placed once in a sector of angle
    `TAU / player_count` and then copied into every other sector, so each player
    faces an exact rotation of what their neighbours face.

    Included for completeness, and because it is worth knowing that this is
    structurally what `maps/spy_v_spy.py` does by hand - with the difference that
    a hand-built map can choose *what* sits on each midline, and this cannot.
    Reach for it when you want guaranteed fairness with no design; reach for
    `irregular` when you want a galaxy with places in it.
    """
    rng = Rng(seed)
    star_count = player_count * stars_per_player
    sector = TAU / player_count
    points: list[Point] = []
    radius = separation
    step = separation

    while len(points) < star_count:
        placed = False
        for _attempt in range(2):               # maxTries, upstream
            angle = rng.random() * sector
            distance = radius / 2.0 + rng.random() * radius * 2.0
            base = (math.sin(angle) * distance, math.cos(angle) * distance)
            candidates = [_rotate(base, index * sector) for index in range(player_count)]
            if any(geometry.too_close(c, points, separation) for c in candidates):
                continue
            if any(geometry.dist(a, b) < separation
                   for i, a in enumerate(candidates) for b in candidates[i + 1:]):
                continue
            points.extend(candidates)
            placed = True
            break
        if not placed:
            radius += step                      # nothing fits at this radius; grow

    homes = _balanced_homes(points, player_count)
    return _finish(points, homes, starting_stars, hyperspace, rng.seed,
                   "circular_balanced")


def spiral(player_count: int, stars_per_player: int, *, seed: str | None = None,
           starting_stars: int = 1, hyperspace: int = 1,
           separation: float = rules.MIN_STAR_SEPARATION,
           arms: int = 2, distribution: str = "circular", **_: object) -> Layout:
    """Stars along spiral arms, roughened and spaced out. spiral.ts.

    The upstream pipeline is spiral -> simplex noise -> padding -> rescale, and
    that is what this does. Arms give a galaxy natural chokepoints: crossing from
    one arm to another is a real decision, where on a disc every direction is the
    same decision. Radius grows as sqrt(index) so stars do not bunch at the hub.
    """
    rng = Rng(seed)
    star_count = player_count * stars_per_player
    noise = noise2d(rng)
    spread = noise_spread(stars_per_player)

    points: list[Point] = []
    for index in range(star_count):
        arm = index % arms
        along = index / arms
        angle = along * _SPIRAL_ANGLE_STEP + arm * TAU / arms
        points.append(_polar(separation * math.sqrt(along) * 1.5, angle))

    # Roughen: displace along the noise gradient so the arms wobble as a whole
    # rather than each star wobbling independently.
    points = [(x + noise(x / spread, y / spread) * separation,
               y + noise((x + spread) / spread, y / spread) * separation)
              for x, y in points]

    # Scale before relaxing, not after. Scaling sets the *mean* gap and relaxing
    # enforces the *floor*; done the other way round the scale-down undoes the
    # relax and stars end up inside the floor again.
    points = _scale_to_separation(points, separation)
    points = relax_separation(points, separation)
    homes = place_homes(points, player_count, rng, distribution,
                        reach=rules.hyperspace_range(hyperspace))
    return _finish(points, homes, starting_stars, hyperspace, rng.seed, "spiral")


def irregular(player_count: int, stars_per_player: int, *, seed: str | None = None,
              starting_stars: int = 1, hyperspace: int = 1,
              separation: float = rules.MIN_STAR_SEPARATION,
              spread: float | None = None, overshoot: float = 1.3,
              falloff: float = 8.0, centre_spacing: float = 1.0,
              front_bias: Callable[[Point], float] | None = None,
              **_: object) -> Layout:
    """The flagship. irregular.ts, and the editor's own default.

    Nine steps, and the order matters:

      1. size the hex lattice so it overshoots the target by `overshoot`
      2. grow capitals outwards on a triangular lattice, avoiding noise peaks
      3. add supplementary lattice centres between them
      4. fill hex rings around every centre
      5. prune outside the metaball of the capitals - gives the galaxy an outline
      6. jitter every star off the lattice
      7. prune against the noise field down to the target - carves the voids
      8. hand each capital its starting stars
      9. pull those stars into opening jump range

    Steps 5 and 7 do different jobs and are both needed: the metaball decides the
    galaxy's *shape*, the noise decides its *texture*. Drop 5 and you get a
    hexagon; drop 7 and you get an even field with no places in it.
    """
    if player_count < 1:
        raise ValueError("player_count must be at least 1")
    rng = Rng(seed)
    star_count = player_count * stars_per_player
    noise = noise2d(rng)
    field_spread = noise_spread(stars_per_player)

    # Upstream shrinks the separation floor by a quarter for the lattice so that
    # the pull-into-range pass at the end has room to work.
    # Defaults to the game's own hardcoded SPREAD. `fit_spread(hyperspace)`
    # gives a denser variant; that is a preference, not a correction.
    if spread is None:
        spread = GAME_SPREAD
    lattice_separation = separation * 0.75
    ring_count = _ring_count(stars_per_player, stars_per_player * overshoot)
    star_distance = lattice_separation * spread
    dislocation = lattice_separation * ((spread - 1.0) / 2.0)
    # `centre_spacing` pushes the cluster centres apart **without** stretching the
    # clusters themselves: `star_distance` is untouched, so each player's own
    # neighbourhood keeps the density it had while the space between
    # neighbourhoods thins out. Scaling everything uniformly instead - a bigger
    # `separation` - thins the pods too, which is what puts contested ground out
    # of reach and costs a player their opening vision.
    pivot_distance = ring_count * star_distance * centre_spacing

    home_points = _grow_homes(pivot_distance, player_count, rng, noise, field_spread)
    centres = home_points + _supplementary_homes(pivot_distance, home_points)

    points: list[Point] = []
    for centre in centres:
        points.extend(hex_rings(centre, ring_count, star_distance))

    points = _prune_metaball(points, home_points, pivot_distance, rng,
                             falloff, star_count - player_count)
    points = jitter(points, dislocation, rng)
    points = prune_by_noise(points, star_count - player_count, noise,
                            field_spread, front_bias)

    # Capitals are appended last and never jittered or pruned - they anchor the
    # lattice, and moving them would undo step 2's noise avoidance.
    homes = list(range(len(points), len(points) + player_count))
    points = points + home_points
    return _finish(points, homes, starting_stars, hyperspace, rng.seed, "irregular")


def irregular_n_limit(player_count: int, stars_per_player: int, *,
                      seed: str | None = None, starting_stars: int = 1,
                      hyperspace: int = 1,
                      separation: float = rules.MIN_STAR_SEPARATION,
                      spread: float | None = None, overshoot: float = 1.3,
                      falloff: float = 8.0, min_neighbours: int = 3,
                      max_neighbours: int = 5,
                      front_bias: Callable[[Point], float] | None = None,
                      **_: object) -> Layout:
    """`irregular`, with the capitals' neighbour count bounded. irregularNLimit.ts.

    The free growth in `irregular` can seat a player with one neighbour or with
    five, and one-neighbour players have a much quieter opening. Here capitals are
    carved out of a full hex grid instead: take a capital, delete a random
    `min_neighbours`..`max_neighbours` of its six lattice neighbours, and repeat
    outwards - so every capital ends up with a bounded number of adjacent rivals.
    Two fix-up rounds then swap any capital still outside the band into a hole
    that satisfies it.

    Only the capital-selection step differs from `irregular`; everything after is
    identical. The upstream selection is described by its own comments rather than
    reproduced line for line here, so treat the neighbour band as this repo's
    reading of the intent.
    """
    if min_neighbours > max_neighbours:
        raise ValueError("min_neighbours must not exceed max_neighbours")
    rng = Rng(seed)
    star_count = player_count * stars_per_player
    noise = noise2d(rng)
    field_spread = noise_spread(stars_per_player)

    # Defaults to the game's own hardcoded SPREAD. `fit_spread(hyperspace)`
    # gives a denser variant; that is a preference, not a correction.
    if spread is None:
        spread = GAME_SPREAD
    lattice_separation = separation * 0.75
    ring_count = _ring_count(stars_per_player, stars_per_player * overshoot)
    star_distance = lattice_separation * spread
    dislocation = lattice_separation * ((spread - 1.0) / 2.0)
    pivot_distance = ring_count * star_distance

    home_points = _carve_homes(pivot_distance, player_count, rng,
                               min_neighbours, max_neighbours)
    centres = home_points + _supplementary_homes(pivot_distance, home_points)

    points: list[Point] = []
    for centre in centres:
        points.extend(hex_rings(centre, ring_count, star_distance))

    points = _prune_metaball(points, home_points, pivot_distance, rng,
                             falloff, star_count - player_count)
    points = jitter(points, dislocation, rng)
    points = prune_by_noise(points, star_count - player_count, noise,
                            field_spread, front_bias)

    homes = list(range(len(points), len(points) + player_count))
    points = points + home_points
    return _finish(points, homes, starting_stars, hyperspace, rng.seed,
                   "irregular_n_limit")


GENERATORS: dict[str, Callable[..., Layout]] = {
    "circular": circular,
    "doughnut": doughnut,
    "circular_balanced": circular_balanced,
    "spiral": spiral,
    "irregular": irregular,
    "irregular_n_limit": irregular_n_limit,
}


def generate(name: str, player_count: int, stars_per_player: int, **kwargs) -> Layout:
    """Run a generator by name. `GENERATORS` lists them."""
    try:
        generator = GENERATORS[name]
    except KeyError:
        raise ValueError(f"unknown generator {name!r}; "
                         f"expected one of {sorted(GENERATORS)}") from None
    return generator(player_count, stars_per_player, **kwargs)


# --------------------------------------------------------------------------
# Generator internals
# --------------------------------------------------------------------------

# circular.ts and doughnut.ts. The editor's comment says this "can really be a
# setting, once it is turned into an intuitive variable". It has not been.
_STAR_DENSITY = 1.3e-4

# How fast a spiral arm turns per star placed along it. Not upstream - upstream
# exposes a distance and an angle factor; this is one turn per ~28 stars, which
# gives arms you can see at every galaxy size tried.
_SPIRAL_ANGLE_STEP = TAU / 28.0

# irregular.ts: a candidate capital sitting above this in the noise field is in
# a region step 7 will hollow out, so it is rejected - but only so many times,
# or a noisy seed never terminates.
_HOME_NOISE_CEILING = 0.65
_HOME_NOISE_ATTEMPTS = 6


def _disc_radius(star_count: int) -> float:
    return (star_count / (math.pi * _STAR_DENSITY)) ** 0.5


def _reject_sample(star_count: int, separation: float, rng: Rng,
                   sample: Callable[[], Point], max_tries: int = 20000) -> list[Point]:
    """Throw darts until `star_count` of them land clear of each other."""
    points: list[Point] = []
    while len(points) < star_count:
        for _ in range(max_tries):
            candidate = sample()
            if not geometry.too_close(candidate, points, separation):
                points.append(candidate)
                break
        else:
            raise RuntimeError(
                f"could not place star {len(points) + 1} of {star_count} in "
                f"{max_tries} tries - separation {separation:g} is too wide for "
                f"the area this generator uses")
    return points


def _scale_to_separation(points: Sequence[Point], separation: float) -> list[Point]:
    """Scale the whole field so the mean nearest-neighbour gap is `separation`.

    spiral.ts::scaleUp. Scaling is safe where nudging is not: it cannot change
    which stars are near which, only how far apart everything is.
    """
    if len(points) < 2:
        return list(points)
    gaps = geometry.nearest_neighbour_gaps(list(points))
    mean = sum(gaps) / len(gaps)
    if mean <= 0.0:
        return list(points)
    factor = separation / mean
    return [(x * factor, y * factor) for x, y in points]


def _balanced_homes(points: Sequence[Point], player_count: int) -> list[int]:
    """Capitals for `circular_balanced`: the same slot in every sector.

    Stars are appended one full rotation at a time, so any `player_count`
    consecutive indices starting on a rotation boundary are the same star in each
    sector - which is exactly what makes the starts congruent.
    """
    centroid = (sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points))
    radius = max(geometry.dist(centroid, p) for p in points) / 2.0
    ideal = _polar(radius, TAU / (2.0 * player_count))
    nearest = min(range(len(points)), key=lambda i: geometry.dist(ideal, points[i]))
    base = (nearest // player_count) * player_count      # snap to a rotation boundary
    return list(range(base, base + player_count))


def _stars_in_rings(ring_count: int) -> int:
    """Stars a hex-ring cluster of this many rings holds.

    irregular.ts::_getStarCountInRings. Ring *r* carries `6 + 6r`, but whichever
    ring is outermost is pruned by `4 + 3r` to let neighbouring clusters tile -
    so growing the cluster refunds the previous outer ring's pruning.
    """
    total = 0
    pruning = 0
    for ring in range(ring_count):
        total += pruning
        total += 6 + ring * 6
        pruning = 4 + ring * 3
        total -= pruning
    return total


def _necessary_ring_count(stars_per_player: float) -> int:
    """Fewest rings holding at least this many stars.

    irregular.ts::_getNecessaryRingCount.
    """
    total = 0
    pruning = 0
    ring = 0
    while total < stars_per_player:
        total += pruning
        total += 6 + ring * 6
        pruning = 4 + ring * 3
        total -= pruning
        ring += 1
    return ring


def _ring_count(minimum: float, maximum: float) -> int:
    """Most rings that stay under `maximum` while clearing `minimum`.

    irregular.ts::_getRingCount.
    """
    count = _necessary_ring_count(minimum) + 1
    while _stars_in_rings(count) < maximum:
        count += 1
    return max(count - 1, 1)


def _grow_homes(pivot_distance: float, player_count: int, rng: Rng,
                noise: Noise, spread: float) -> list[Point]:
    """Grow capitals outwards on a triangular lattice. irregular.ts.

    From an existing capital, step `pivot_distance` at some multiple of 60 degrees
    and then `pivot_distance` again at 60 degrees either side of that. The result
    lands on a triangular lattice of pitch `sqrt(3) * pivot_distance`, so the
    "closer than pivot_distance" rejection upstream can only ever fire on an
    exact duplicate - which is what it is really for.

    Upstream evaluates the noise rejection inside its loop over existing capitals,
    so it cannot fire while there is only one and it consumes an attempt per
    capital examined. Here it is one test per candidate, which is the intent.
    """
    homes: list[Point] = [(0.0, 0.0)]
    while len(homes) < player_count:
        attempts = 0
        while True:
            base = homes[rng.integer(len(homes) - 1)]
            pivot_rotation = _SIXTH_TAU * rng.integer(5)
            pivot = _add(base, _rotate((pivot_distance, 0.0), pivot_rotation))
            turn = -_SIXTH_TAU if rng.random() < 0.5 else _SIXTH_TAU
            candidate = _add(pivot, _rotate((pivot_distance, 0.0),
                                            pivot_rotation + turn))

            if any(geometry.dist(candidate, home) < pivot_distance for home in homes):
                continue                        # duplicate lattice point
            if (attempts < _HOME_NOISE_ATTEMPTS
                    and noise(candidate[0] / spread,
                              candidate[1] / spread) > _HOME_NOISE_CEILING):
                attempts += 1                   # sits in what will become a void
                continue
            homes.append(candidate)
            break
    return homes


def _supplementary_homes(pivot_distance: float, homes: Sequence[Point]) -> list[Point]:
    """Extra lattice centres filling the gaps between capitals.

    irregular.ts::_generateSupplementaryHomeLocations. Without these the galaxy is
    a set of disconnected blobs, one per player; with them the space *between*
    players is populated too, which is where a map's contested ground lives.
    """
    out: list[Point] = []
    for home in homes:
        for index in range(6):
            pivot = _add(home, _rotate((pivot_distance, 0.0), _SIXTH_TAU * index))
            candidate = _add(pivot, _rotate((pivot_distance, 0.0),
                                            _SIXTH_TAU * (index + 1)))
            if any(geometry.dist(home_point, candidate) < pivot_distance
                   for home_point in homes):
                continue
            if any(geometry.dist(other, candidate) < pivot_distance for other in out):
                continue
            out.append(candidate)
    return out


# A hex lattice addressed in axial integer coordinates. Doing the bookkeeping in
# integers rather than in points is what makes "is this cell already taken"
# exact - walking a ring in floats accumulates error until adjacency tests need
# a tolerance, and a tolerance on a lattice is a bug waiting to happen.
Cell = tuple[int, int]
_AXIAL_NEIGHBOURS: tuple[Cell, ...] = ((1, 0), (1, -1), (0, -1),
                                       (-1, 0), (-1, 1), (0, 1))


def _cell_point(cell: Cell, pitch: float) -> Point:
    """Axial cell to a point, on the same lattice `_grow_homes` walks.

    The half-turn-sixth rotation is load bearing. Free growth reaches its
    neighbours at bearings 30, 90, 150... while a bare axial mapping puts them at
    0, 60, 120..., and `hex_rings` corners its clusters at 0, 60, 120. Get this
    wrong and the clusters interleave instead of tiling, which shows up as stars
    landing on top of each other rather than as anything obvious.
    """
    q, r = cell
    base = (pitch * (q + r * 0.5), pitch * (r * math.sqrt(3.0) / 2.0))
    return _rotate(base, _SIXTH_TAU / 2.0)


def _cell_norm(cell: Cell) -> int:
    """How many lattice steps this cell is from the origin."""
    q, r = cell
    return (abs(q) + abs(q + r) + abs(r)) // 2


def _cell_ring(radius: int) -> list[Cell]:
    """The cells exactly `radius` steps from the origin, walked in order."""
    if radius == 0:
        return [(0, 0)]
    q, r = _AXIAL_NEIGHBOURS[4][0] * radius, _AXIAL_NEIGHBOURS[4][1] * radius
    out: list[Cell] = []
    for direction in range(6):
        dq, dr = _AXIAL_NEIGHBOURS[direction]
        for _ in range(radius):
            out.append((q, r))
            q, r = q + dq, r + dr
    return out


def _carve_homes(pivot_distance: float, player_count: int, rng: Rng,
                 min_neighbours: int, max_neighbours: int) -> list[Point]:
    """Capitals carved out of a hex grid under a neighbour bound. irregularNLimit.ts.

    Breadth-first from the origin: accept a lattice cell as a capital, then
    delete a random `min_neighbours`..`max_neighbours` of its free neighbours so
    they can never become capitals themselves, and queue the rest. Culling most
    of a cell's neighbours is what bounds how many rivals a capital ends up
    adjacent to - which is the whole difference from `irregular`, where a player
    can be seated with one neighbour or with five.

    Aggressive culling starves the queue, so when it empties the walk restarts
    from the unclaimed cell nearest the origin rather than giving up. That keeps
    the cluster growing outwards and makes the generator total for any band.

    Two fix-up rounds then swap any capital whose neighbour count still falls
    outside the band into a culled hole that satisfies it.
    """
    pitch = pivot_distance * math.sqrt(3.0)
    accepted: list[Cell] = []
    removed: set[Cell] = set()
    seen: set[Cell] = set()
    queue: list[Cell] = [(0, 0)]

    while len(accepted) < player_count:
        if not queue:
            # Queue dry - every free neighbour got culled. Restart from the cell
            # touching the existing cluster, not from the nearest free cell
            # anywhere: searching outwards from the origin finds somewhere far
            # off across a gap, which seats one player in exile with nobody
            # within reach. Reviving a culled cell costs the neighbour bound at
            # one capital; exiling a player costs them the game.
            adjacent = [(cell[0] + dq, cell[1] + dr)
                        for cell in accepted for dq, dr in _AXIAL_NEIGHBOURS]
            adjacent = [c for c in adjacent if c not in seen]
            if not adjacent:
                raise RuntimeError(
                    f"could not seat {player_count} capitals at neighbour band "
                    f"{min_neighbours}-{max_neighbours}")
            # Prefer a cell nobody culled, then the one nearest the middle.
            revived = min(adjacent, key=lambda c: (c in removed, _cell_norm(c), c))
            removed.discard(revived)
            queue.append(revived)

        cell = queue.pop(0)
        if cell in seen or cell in removed:
            continue
        seen.add(cell)
        accepted.append(cell)

        free = [(cell[0] + dq, cell[1] + dr) for dq, dr in _AXIAL_NEIGHBOURS]
        free = [c for c in free if c not in seen and c not in removed]
        rng.shuffle(free)
        cull = min(rng.between(min_neighbours, max_neighbours), len(free))
        removed.update(free[:cull])
        queue.extend(free[cull:])

    # Fix-up: a capital outside the band swaps into a hole that satisfies it.
    def neighbours_of(cell: Cell, among: Sequence[Cell]) -> int:
        pool = set(among)
        return sum(1 for dq, dr in _AXIAL_NEIGHBOURS
                   if (cell[0] + dq, cell[1] + dr) in pool)

    for _round in range(2):
        for index, home in enumerate(accepted):
            others = accepted[:index] + accepted[index + 1:]
            if min_neighbours <= neighbours_of(home, others) <= max_neighbours:
                continue
            better = next((hole for hole in sorted(removed)
                           if min_neighbours <= neighbours_of(hole, others)
                           <= max_neighbours), None)
            if better is not None:
                removed.discard(better)
                removed.add(home)
                accepted[index] = better

    return [_cell_point(cell, pitch) for cell in accepted]


def _prune_metaball(points: Sequence[Point], homes: Sequence[Point], radius: float,
                    rng: Rng, falloff: float, minimum: int) -> list[Point]:
    """Drop points outside the blob around the capitals, keeping at least `minimum`.

    irregular.ts::_pruneLocationsOutsideMetaball, plus a top-up upstream lacks:
    an unlucky roll can leave fewer points than the noise prune later needs, and
    the editor simply produces a smaller galaxy than asked for. Here the points
    with the strongest field are put back, in order, until the count is met - so
    a short run fills in from the galaxy's core outwards rather than at random.
    """
    kept: list[tuple[int, Point]] = []
    dropped: list[tuple[float, int, Point]] = []
    for index, point in enumerate(points):
        intensity = metaball_field(point, homes, radius, falloff)
        if rng.random() >= 1.0 - intensity:
            kept.append((index, point))
        else:
            dropped.append((intensity, index, point))

    if len(kept) < minimum:
        dropped.sort(key=lambda row: (-row[0], row[1]))
        for intensity, index, point in dropped[:minimum - len(kept)]:
            kept.append((index, point))
        kept.sort(key=lambda row: row[0])
    return [point for _, point in kept]
