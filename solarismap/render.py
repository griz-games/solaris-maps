"""Draw a custom galaxy to SVG using the game's own map art.

Rendering with the editor's assets rather than inventing shapes means the picture
speaks the same visual language as the game: the same star glyphs, the same player
rings, the same nebula and asteroid textures, tinted the way Pixi tints them.
Somebody looking at the SVG is looking at what they will see in Solaris.

`draw()` renders any valid map with no map-specific knowledge at all. A map that
wants callouts on top passes `annotate_under` / `annotate_over` hooks; see
maps/spy_v_spy.py for a worked example.
"""

from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import rules

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent / "assets"

# --------------------------------------------------------------------------
# Sizes, mirrored from the editor so a render is to scale
# --------------------------------------------------------------------------

STAR_SIZE = 12.0                    # graphics_star, editor star.ts
SHAPE_SIZE = 28.0                   # graphics_shape_*, editor star.ts
NEBULA_SIZE = 64.0                  # editor star.ts
ASTEROID_SIZE = 64.0                # editor star.ts
WORMHOLE_SIZE = 40.0                # editor star.ts
SPECIALIST_SIZE = 16.0

LIGHT_YEAR = rules.LIGHT_YEAR

# --------------------------------------------------------------------------
# Asset paths
# --------------------------------------------------------------------------

SHAPE_FILES = {
    "circle": ASSETS / "map-objects" / "256x256_circle.svg",
    "square": ASSETS / "map-objects" / "256x256_square.svg",
    "hexagon": ASSETS / "map-objects" / "256x256_hexagon.svg",
    "diamond": ASSETS / "map-objects" / "256x256_diamond.svg",
    # A warp gate is not a mark of its own upstream - it selects a different
    # player-shape sprite. star.ts drawColour indexes
    # PLAYER_SYMBOLS[player.shape][2 + wgFlag], so the gate rides on the ring
    # that already says who owns the star.
    "circle_warp_gate": ASSETS / "map-objects" / "256x256_circle_warp_gate.svg",
    "square_warp_gate": ASSETS / "map-objects" / "256x256_square_warp_gate.svg",
    "hexagon_warp_gate": ASSETS / "map-objects" / "256x256_hexagon_warp_gate.svg",
    "diamond_warp_gate": ASSETS / "map-objects" / "256x256_diamond_warp_gate.svg",
}

STAR_FILES = {
    "scannable": ASSETS / "map-objects" / "128x128_star_scannable.svg",
    "binary": ASSETS / "map-objects" / "128x128_star_scannable_binary.svg",
    "home": ASSETS / "map-objects" / "128x128_star_home.svg",
    "black_hole": ASSETS / "map-objects" / "128x128_star_black_hole.svg",
    "black_hole_binary": ASSETS / "map-objects" / "128x128_star_black_hole_binary.svg",
    "pulsar": ASSETS / "stars" / "128x128_star_pulsar.svg",
}

NEBULA_PNGS = [ASSETS / "nebula" / f"star-nebula-{i}.png" for i in range(3)]
ASTEROID_PNGS = [ASSETS / "stars" / f"star-asteroid-field-{i}.png" for i in range(3)]
VORTEX_PNG = ASSETS / "stars" / "vortex.png"


def specialist_icon(key: str) -> Path:
    """Path to a specialist's icon, by its store key (e.g. 'radar-dish')."""
    return ASSETS / "specialists" / f"{key}.svg"


# --------------------------------------------------------------------------
# Assets to inline SVG
# --------------------------------------------------------------------------


def _strip(node: ET.Element) -> None:
    """Drop Inkscape/RDF cruft and retint the asset's hardcoded white."""
    for child in list(node):
        tag = child.tag.split("}")[-1]
        if tag in ("metadata", "namedview", "RDF", "Work"):
            node.remove(child)
            continue
        _strip(child)
    for key in [k for k in node.attrib if "}" in k and not k.startswith(f"{{{SVG_NS}}}")]:
        del node.attrib[key]
    for key in ("style", "fill", "stroke"):
        if key in node.attrib:
            value = node.attrib[key]
            value = re.sub(r"#(?:ffffff|fcfcfc)\b", "currentColor", value, flags=re.I)
            value = re.sub(r"rgb\(\s*255,\s*255,\s*255\s*\)", "currentColor", value, flags=re.I)
            node.attrib[key] = value


def symbol_from_svg(path: Path, symbol_id: str, fill: str | None = None) -> str:
    """Turn one of the repo's asset SVGs into a reusable <symbol>.

    Specialist icons are bare game-icons paths with no fill of their own, so
    they need `fill` set on the symbol to inherit; map objects carry their own
    hardcoded white, which _strip rewrites to currentColor instead.
    """
    root = ET.parse(path).getroot()
    view_box = root.attrib["viewBox"]
    _strip(root)
    body = "".join(ET.tostring(child, encoding="unicode") for child in root)
    body = body.replace(f' xmlns="{SVG_NS}"', "")
    attrs = f' fill="{fill}"' if fill else ""
    return (f'<symbol id="{symbol_id}" viewBox="{view_box}" overflow="visible"'
            f'{attrs}>{body}</symbol>')


def data_uri(path: Path) -> str:
    """Embed a PNG so the SVG stays self-contained."""
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def tint_filter(colour: str) -> str:
    """Tint a texture by flooding its alpha, which is how Pixi tints a sprite."""
    return (f'<filter id="tint{colour.lstrip("#")}" x="-20%" y="-20%" width="140%" '
            f'height="140%" color-interpolation-filters="sRGB">'
            f'<feFlood flood-color="{colour}" result="flood"/>'
            f'<feComposite in="flood" in2="SourceAlpha" operator="in"/></filter>')


# --------------------------------------------------------------------------
# Element primitives
# --------------------------------------------------------------------------

FONT = "ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas, monospace"


def n(v: float) -> str:
    """Trim a coordinate: SVGs of a 900-star galaxy are mostly digits."""
    return f"{v:.2f}".rstrip("0").rstrip(".")


def esc(body: str) -> str:
    return body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def use(symbol: str, cx: float, cy: float, size: float,
        colour: str = "#ffffff", opacity: float = 1.0) -> str:
    tag = (f'<use href="#{symbol}" x="{n(cx - size / 2)}" y="{n(cy - size / 2)}" '
           f'width="{n(size)}" height="{n(size)}" color="{colour}"')
    if opacity != 1.0:
        tag += f' opacity="{n(opacity)}"'
    return tag + "/>"


def texture(png_id: str, cx: float, cy: float, size: float,
            opacity: float, rotate: float, colour: str) -> str:
    return (f'<g transform="rotate({n(rotate)} {n(cx)} {n(cy)})">'
            f'<use href="#{png_id}" x="{n(cx - size / 2)}" y="{n(cy - size / 2)}" '
            f'width="{n(size)}" height="{n(size)}" opacity="{n(opacity)}" '
            f'filter="url(#tint{colour.lstrip("#")})"/></g>')


def circle(cx: float, cy: float, r: float, stroke: str, width: float,
           opacity: float = 1.0, dash: str | None = None, fill: str = "none") -> str:
    tag = (f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(r)}" fill="{fill}" '
           f'stroke="{stroke}" stroke-width="{n(width)}" opacity="{n(opacity)}"')
    if dash:
        tag += f' stroke-dasharray="{dash}"'
    return tag + "/>"


def text(x: float, y: float, body: str, size: float, colour: str,
         anchor: str = "middle", opacity: float = 1.0, weight: str = "400") -> str:
    return (f'<text x="{n(x)}" y="{n(y)}" font-size="{n(size)}" fill="{colour}" '
            f'text-anchor="{anchor}" font-family="{FONT}" font-weight="{weight}" '
            f'opacity="{n(opacity)}">{esc(body)}</text>')


def line(x1: float, y1: float, x2: float, y2: float, stroke: str,
         width: float, opacity: float = 1.0, dash: str | None = None) -> str:
    tag = (f'<line x1="{n(x1)}" y1="{n(y1)}" x2="{n(x2)}" y2="{n(y2)}" '
           f'stroke="{stroke}" stroke-width="{n(width)}" opacity="{n(opacity)}"')
    if dash:
        tag += f' stroke-dasharray="{dash}"'
    return tag + "/>"


# --------------------------------------------------------------------------
# Frame
# --------------------------------------------------------------------------


def bounds(stars: list[dict], margin: float = 0.0) -> tuple[float, float, float, float]:
    """(min_x, min_y, width, height) covering every star, plus a margin."""
    xs = [s["location"]["x"] for s in stars]
    ys = [s["location"]["y"] for s in stars]
    min_x, max_x = min(xs) - margin, max(xs) + margin
    min_y, max_y = min(ys) - margin, max(ys) + margin
    return min_x, min_y, max_x - min_x, max_y - min_y


def document(body: str, view_box: tuple[float, float, float, float],
             defs: str = "", background: str | None = None) -> str:
    """Wrap drawn content in a self-contained SVG document."""
    x, y, w, h = view_box
    ground = (f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" '
              f'fill="{background}"/>') if background else ""
    return (f'<svg xmlns="{SVG_NS}" viewBox="{n(x)} {n(y)} {n(w)} {n(h)}" '
            f'width="{n(w)}" height="{n(h)}">'
            f'<defs>{defs}</defs>{ground}{body}</svg>')


# --------------------------------------------------------------------------
# Stars
# --------------------------------------------------------------------------


def star_glyph(star: dict) -> str:
    """Which of the editor's star glyphs this star draws as."""
    if star.get("isPulsar"):
        return "pulsar"
    if star.get("isBlackHole"):
        return "black_hole_binary" if star.get("isBinaryStar") else "black_hole"
    if star.get("homeStar"):
        return "home"
    return "binary" if star.get("isBinaryStar") else "scannable"


def scan_radius(star: dict, scanning_level: int, specialist_scanning: int = 0) -> float:
    """How far this star sees, in world units, terrain and specialist included."""
    effective = rules.effective_scanning(scanning_level, star, specialist_scanning)
    return rules.scanning_range(effective) if effective > 0 else 0.0


# --------------------------------------------------------------------------
# Palette
#
# The editor's own UI colours, so a render sits next to a screenshot without
# clashing. Player colours come from the map when it carries them (the editor's
# extra `colour` field) and are generated otherwise - Solaris reassigns them at
# game creation either way, so they are a reading aid, not a spec.
# --------------------------------------------------------------------------


class Palette:
    ink = "#000000"
    paper = "#e8eef5"
    muted = "#8fa3b8"
    faint = "#5b6b7f"
    green = "#3cd2a5"
    amber = "#ff9f0c"
    red = "#ff6060"
    neutral = "#ffffff"


PALETTE = Palette()

# Distinct hues for maps whose players carry no colour of their own.
FALLBACK_COLOURS = [
    "#ff6060", "#3cd2a5", "#ff9f0c", "#6f9fff", "#c678dd", "#e5c07b",
    "#56b6c2", "#98c379", "#e06c75", "#61afef", "#d19a66", "#b48ead",
]


def player_colours(data: dict) -> dict[str, str]:
    """Map player id to a hex colour, preferring what the map already says."""
    out: dict[str, str] = {}
    for index, player in enumerate(data.get("players") or []):
        colour = (player.get("colour") or {}).get("value")
        out[player.get("id")] = colour or FALLBACK_COLOURS[index % len(FALLBACK_COLOURS)]
    # A map may own stars without declaring players (basic mode).
    for star in data["stars"]:
        pid = star.get("playerId")
        if pid is not None and pid not in out:
            out[pid] = FALLBACK_COLOURS[len(out) % len(FALLBACK_COLOURS)]
    return out


def player_shapes(data: dict) -> dict[str, str]:
    shapes = ["circle", "square", "hexagon", "diamond"]
    out: dict[str, str] = {}
    for index, player in enumerate(data.get("players") or []):
        out[player.get("id")] = player.get("shape") or shapes[index % len(shapes)]
    return out


def _jitter(seed: str, salt: int = 0) -> float:
    """Deterministic rotation per star, so textures do not all line up."""
    value = 0
    for char in f"{seed}:{salt}":
        value = (value * 31 + ord(char)) & 0xFFFFFFFF
    return value % 360


# --------------------------------------------------------------------------
# Options and the hook context
# --------------------------------------------------------------------------


class Options:
    """What to draw. Every flag is independent; defaults suit a whole-galaxy view."""

    def __init__(self, labels: bool = False, resources: bool = True,
                 ships: bool = True, scan_circles: bool = False,
                 hyperspace_circles: bool = False, wormhole_links: bool = True,
                 scanning_level: int | None = None, hyperspace_level: int | None = None,
                 background: str | None = PALETTE.ink, margin: float = 120.0,
                 focus: tuple[float, float, float] | None = None,
                 star_scale: float = 1.0):
        self.labels = labels                    # star ids
        self.resources = resources              # natural resources under each star
        self.ships = ships                      # garrison beside owned stars
        self.scan_circles = scan_circles
        self.hyperspace_circles = hyperspace_circles
        self.wormhole_links = wormhole_links
        self.scanning_level = scanning_level    # None: read each owner's own tech
        self.hyperspace_level = hyperspace_level
        self.background = background
        self.margin = margin
        self.focus = focus                      # (x, y, radius) to crop to
        self.star_scale = star_scale


class Context:
    """What an annotation hook is handed.

    Carries the map, the lookups a callout needs, the palette, and the drawing
    primitives, so a hook never has to import anything: `yield ctx.circle(...)`.
    """

    def __init__(self, data: dict, options: Options,
                 view_box: tuple[float, float, float, float]):
        self.data = data
        self.stars = data["stars"]
        self.by_id = {s["id"]: s for s in self.stars}
        self.players = {p.get("id"): p for p in (data.get("players") or [])}
        self.options = options
        self.view_box = view_box
        self.palette = PALETTE
        self.colours = player_colours(data)
        self.shapes = player_shapes(data)

    # lookups
    def point(self, star_id: str) -> tuple[float, float]:
        star = self.by_id[star_id]
        return star["location"]["x"], star["location"]["y"]

    def colour_of(self, star: dict) -> str:
        pid = star.get("playerId")
        return self.colours.get(pid, PALETTE.neutral) if pid else PALETTE.neutral

    def where(self, **flags) -> list[dict]:
        """Stars matching every given field, e.g. ctx.where(isBlackHole=True)."""
        return [s for s in self.stars
                if all(s.get(key) == value for key, value in flags.items())]

    # primitives, re-exported so a hook needs no imports
    circle = staticmethod(circle)
    text = staticmethod(text)
    line = staticmethod(line)
    use = staticmethod(use)
    texture = staticmethod(texture)
    n = staticmethod(n)
    esc = staticmethod(esc)


# --------------------------------------------------------------------------
# The renderer
# --------------------------------------------------------------------------


def build_defs(data: dict) -> str:
    """Symbols and filters for everything this map could draw."""
    parts = []
    for name, path in STAR_FILES.items():
        parts.append(symbol_from_svg(path, f"star-{name}"))
    for name, path in SHAPE_FILES.items():
        parts.append(symbol_from_svg(path, f"shape-{name}"))

    # Only the specialists this map actually uses: there are 67 icons and
    # inlining all of them would dwarf the map.
    used = {s.get("specialistId") for s in data["stars"] if s.get("specialistId")}
    from . import specialists as _specialists
    for specialist_id in sorted(x for x in used if x is not None):
        spec = _specialists.star_specialist(specialist_id)
        if spec is None:
            continue
        icon = specialist_icon(spec["key"])
        if icon.exists():
            parts.append(symbol_from_svg(icon, f"spec-{specialist_id}", fill="currentColor"))

    # <use> only honours width/height when the referent is a <symbol> or <svg>,
    # so each PNG is wrapped rather than referenced as a bare <image>.
    def png_symbol(symbol_id: str, path: Path) -> str:
        return (f'<symbol id="{symbol_id}" viewBox="0 0 1 1" preserveAspectRatio="none">'
                f'<image href="{data_uri(path)}" width="1" height="1" '
                f'preserveAspectRatio="none"/></symbol>')

    if any(s.get("isNebula") for s in data["stars"]):
        for index, path in enumerate(NEBULA_PNGS):
            parts.append(png_symbol(f"neb{index}", path))
    if any(s.get("isAsteroidField") for s in data["stars"]):
        for index, path in enumerate(ASTEROID_PNGS):
            parts.append(png_symbol(f"ast{index}", path))
    if any(s.get("wormHoleToStarId") for s in data["stars"]):
        parts.append(png_symbol("vortex", VORTEX_PNG))

    for colour in sorted(set(player_colours(data).values()) | {PALETTE.neutral}):
        parts.append(tint_filter(colour))

    parts.append('<radialGradient id="halo">'
                 '<stop offset="0%" stop-color="currentColor" stop-opacity="0.50"/>'
                 '<stop offset="55%" stop-color="currentColor" stop-opacity="0.09"/>'
                 '<stop offset="100%" stop-color="currentColor" stop-opacity="0"/>'
                 '</radialGradient>')
    return "".join(parts)


def draw_star(star: dict, ctx: Context) -> tuple[str, str, str]:
    """One star as (terrain, body, detail) so the layers can be interleaved."""
    from . import specialists as _specialists

    options = ctx.options
    cx, cy = star["location"]["x"], star["location"]["y"]
    colour = ctx.colour_of(star)
    scale = options.star_scale
    terrain, body, detail = [], [], []

    star_id = star["id"]
    index = sum(ord(c) for c in str(star_id))

    if star.get("isNebula"):
        png = f"neb{index % len(NEBULA_PNGS)}"
        terrain.append(texture(png, cx, cy, NEBULA_SIZE, 0.55, _jitter(star_id), colour))
        terrain.append(texture(png, cx, cy, NEBULA_SIZE, 0.35, _jitter(star_id, 1), colour))
    if star.get("isAsteroidField"):
        png = f"ast{index % len(ASTEROID_PNGS)}"
        terrain.append(texture(png, cx, cy, ASTEROID_SIZE, 0.9, _jitter(star_id, 2), colour))
    if star.get("wormHoleToStarId") is not None:
        terrain.append(texture("vortex", cx, cy, WORMHOLE_SIZE, 0.4, _jitter(star_id, 3), colour))

    terrain.append(f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(26.0 * scale)}" '
                   f'fill="url(#halo)" color="{colour}"/>')

    specialist_id = star.get("specialistId")
    if specialist_id is not None and _specialists.star_specialist(specialist_id):
        # The editor draws a star's specialist badge in place of its glyph.
        body.append(use(f"spec-{specialist_id}", cx, cy, SPECIALIST_SIZE * scale, colour))
    else:
        body.append(use(f"star-{star_glyph(star)}", cx, cy, STAR_SIZE * scale, colour))

    if star.get("isPulsar"):
        # The editor draws a pulsar as a bar through the star, ringed either side.
        body.append(line(cx, cy - 20 * scale, cx, cy + 20 * scale, colour, 1.6, 0.9))
        for radius in (5, 8):
            for side in (-1, 1):
                body.append(circle(cx + side * radius * scale, cy, radius * scale,
                                   colour, 1.4, 0.75))

    # star.ts drawColour. Two things follow from it and both are deliberate.
    # The warp gate selects a different player-shape sprite rather than drawing
    # a ring of its own - this used to draw a dashed circle, which the game has
    # no equivalent of. And drawColour returns early when the star has no owner,
    # so an unowned warp gate is invisible in the game and is invisible here.
    pid = star.get("playerId")
    if pid is not None:
        shape = ctx.shapes.get(pid, "circle")
        if star.get("warpGate"):
            shape = f"{shape}_warp_gate"
        body.append(use(f"shape-{shape}", cx, cy, SHAPE_SIZE * scale, colour, 0.9))

    if options.scan_circles:
        level = (options.scanning_level
                 if options.scanning_level is not None
                 else (ctx.players.get(pid, {}).get("technologies") or {}).get("scanning", 1))
        radius = scan_radius(star, level, _specialists.scanning_bonus(specialist_id))
        if radius:
            body.append(circle(cx, cy, radius, colour, 1.2, 0.22, dash="10 10"))

    if options.hyperspace_circles and pid is not None:
        level = (options.hyperspace_level
                 if options.hyperspace_level is not None
                 else (ctx.players.get(pid, {}).get("technologies") or {}).get("hyperspace", 1))
        body.append(circle(cx, cy, rules.hyperspace_range(level), colour, 1.0, 0.16,
                           dash="4 12"))

    if options.resources:
        nr = star.get("naturalResources") or {}
        values = [nr.get(c, 0) for c in rules.RESOURCE_CHANNELS]
        body_text = str(values[0]) if len(set(values)) == 1 else "/".join(map(str, values))
        detail.append(text(cx, cy + 27 * scale, body_text, 8 * scale, "#9fb3c8", opacity=0.8))
    if options.labels:
        detail.append(text(cx, cy - 20 * scale, str(star_id), 7 * scale,
                           PALETTE.faint, opacity=0.6))
    if options.ships and (star.get("shipsActual") or 0):
        detail.append(text(cx + 16 * scale, cy + 3 * scale,
                           str(int(star["shipsActual"])), 9 * scale, colour,
                           anchor="start", weight="700", opacity=0.95))

    return "".join(terrain), "".join(body), "".join(detail)


def frame(data: dict, options: Options) -> tuple[tuple[float, float, float, float], list[dict]]:
    """The viewBox and the stars inside it, given the options.

    Shared with the CLI so a cropped render can report how many stars it drew
    rather than how many the map has.
    """
    stars = data["stars"]
    if options.focus:
        fx, fy, radius = options.focus
        view_box = (fx - radius, fy - radius, radius * 2, radius * 2)
        visible = [s for s in stars
                   if abs(s["location"]["x"] - fx) <= radius + options.margin
                   and abs(s["location"]["y"] - fy) <= radius + options.margin]
        return view_box, visible
    return bounds(stars, options.margin), stars


def draw(data: dict, options: Options | None = None,
         annotate_under=None, annotate_over=None) -> str:
    """Render any valid custom galaxy to a self-contained SVG document.

    `annotate_under` and `annotate_over` are optional callables taking a Context
    and yielding SVG strings, drawn below the stars and above everything
    respectively. That is how a map adds its own callouts without this module
    knowing anything about it.
    """
    options = options or Options()
    view_box, visible = frame(data, options)

    ctx = Context(data, options, view_box)

    layers: list[str] = []
    if annotate_under:
        layers.extend(annotate_under(ctx))

    terrain, body, detail = [], [], []
    for star in visible:
        t, b, d = draw_star(star, ctx)
        terrain.append(t)
        body.append(b)
        detail.append(d)

    links = []
    if options.wormhole_links:
        drawn: set[frozenset] = set()
        # Both ends, not just the visible ones: a link leaving a cropped view
        # should still be drawn heading out of frame.
        for star in data["stars"]:
            target_id = star.get("wormHoleToStarId")
            if target_id is None or target_id not in ctx.by_id:
                continue
            pair = frozenset((star["id"], target_id))
            if pair in drawn:
                continue
            drawn.add(pair)
            x1, y1 = ctx.point(star["id"])
            x2, y2 = ctx.point(target_id)
            links.append(line(x1, y1, x2, y2, PALETTE.muted, 1.0, 0.28, dash="2 14"))

    layers += ["".join(terrain), "".join(links), "".join(body), "".join(detail)]

    if annotate_over:
        layers.extend(annotate_over(ctx))

    return document("".join(layers), view_box, build_defs(data), options.background)
