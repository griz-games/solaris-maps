#!/usr/bin/env python3
"""Render a spy-v-spy map JSON to zoomable SVG, drawn with the editor's own assets.

Emits self-contained files into docs/assets/, named after the variant:

  <prefix>-map.svg    the whole galaxy ring - every star, its resources and
                      garrison, every wormhole, every scan bubble. No title
                      block: the page that embeds it does the captioning.
  <prefix>-map.json   normalised jump targets, which the page's viewer picks up
                      on its own to offer a button per galaxy.
  <prefix>-pod.svg    one player's pod, annotated (only with --pod)

Star glyphs, player shape rings and the Telescope Array badge are lifted
straight out of src/assets/ and become <symbol>s; the nebula, asteroid-field and
wormhole textures are embedded as data URIs and tinted with the same player
colour Pixi would tint them. A star carrying a specialist shows its badge in
place of its glyph, as the editor does, so every post wears its array. So the
render speaks the same visual language as the editor and as Solaris itself.

Every number that appears as text is read from the map JSON. Nothing about the
map is restated here by hand.

Run:  python scripts/render_spy_v_spy.py 36p
      python scripts/render_spy_v_spy.py 8p
"""

import argparse
import base64
import collections
import json
import math
import os
import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = ROOT / "maps"
OUT_DIR = ROOT / "docs" / "assets"

# variant -> (map JSON in maps/, output basename in docs/assets/)
VARIANTS = {
    "36p": ("spy_v_spy.json", "spy-v-spy"),
    "8p": ("spy_v_spy_8p.json", "spy-v-spy-8p"),
}

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

# --------------------------------------------------------------------------
# Constants mirrored from the editor, so the render is to scale
# --------------------------------------------------------------------------

LIGHT_YEAR = 50.0                       # src/scripts/map.ts:28
STAR_SIZE = 12.0                        # graphics_star, src/scripts/star.ts:270
SHAPE_SIZE = 28.0                       # graphics_shape_*, src/scripts/star.ts:666
NEBULA_SIZE = 64.0                      # src/scripts/star.ts:324
ASTEROID_SIZE = 64.0                    # src/scripts/star.ts:392
WORMHOLE_SIZE = 40.0                    # src/scripts/star.ts:362

PLAYERS_PER_GALAXY = 4
START_SCANNING = 2
BLACK_HOLE_BONUS = 3                    # helper.getEffectiveTechs, src/scripts/helper.ts:346
TELESCOPE_BONUS = 3                     # Telescope Array, src/stores/specialists.ts:721
SPECIALIST_TELESCOPE_ARRAY = 13
POST_CLEARANCE = (START_SCANNING + BLACK_HOLE_BONUS + 1) * LIGHT_YEAR              # 300
POST_SCAN = (START_SCANNING + BLACK_HOLE_BONUS + TELESCOPE_BONUS + 1) * LIGHT_YEAR # 450
HYPERSPACE_2 = (2 + 1.5) * LIGHT_YEAR                              # 175
HYPERSPACE_3 = (3 + 1.5) * LIGHT_YEAR                              # 225
CARRIER_SPEED = 10.0

NR_MIN, NR_MAX = 10, 100                # the fringe-to-core gradient, ex features

# Editor / Solaris UI palette, from src/assets/root.css
INK = "#000000"
GREEN = "#3cd2a5"
AMBER = "#ff9f0c"
RED = "#ff6060"
PAPER = "#e8eef5"
MUTED = "#8fa3b8"
FAINT = "#5b6b7f"

FONT = "ui-monospace, 'SF Mono', 'Cascadia Mono', Menlo, Consolas, monospace"

def find_assets() -> Path:
    """Locate the editor's src/assets, which this repo does not vendor.

    The glyphs, shape rings and textures are the Solaris editor's own, so a
    render needs a checkout of it. Looked for in $SOLARIS_SRC, then inside this
    repo, then in a sibling clone - which is where it usually sits.
    """
    candidates = []
    if os.environ.get("SOLARIS_SRC"):
        candidates.append(Path(os.environ["SOLARIS_SRC"]) / "src" / "assets")
    candidates.append(ROOT / "src" / "assets")
    candidates.append(ROOT.parent / "solaris-map" / "src" / "assets")
    for path in candidates:
        if (path / "map-objects").is_dir():
            return path
    raise SystemExit(
        "could not find the editor's src/assets - point $SOLARIS_SRC at a "
        "checkout of the solaris map editor. Looked in:\n  "
        + "\n  ".join(str(c) for c in candidates))


ASSETS = find_assets()
SHAPE_FILES = {
    "circle": ASSETS / "map-objects" / "256x256_circle.svg",
    "square": ASSETS / "map-objects" / "256x256_square.svg",
    "hexagon": ASSETS / "map-objects" / "256x256_hexagon.svg",
    "diamond": ASSETS / "map-objects" / "256x256_diamond.svg",
}
STAR_FILES = {
    "star": ASSETS / "map-objects" / "128x128_star_scannable.svg",
    "star-binary": ASSETS / "map-objects" / "128x128_star_scannable_binary.svg",
    "star-home": ASSETS / "map-objects" / "128x128_star_home.svg",
}
NEBULA_PNGS = [ASSETS / "nebula" / f"star-nebula-{i}.png" for i in range(3)]
ASTEROID_PNGS = [ASSETS / "stars" / f"star-asteroid-field-{i}.png" for i in range(3)]
VORTEX_PNG = ASSETS / "stars" / "vortex.png"
# The only specialist on the map. Drawn in place of the star glyph, as the
# editor does (src/scripts/star.ts:954), so every post wears its array.
SPECIALIST_FILE = ASSETS / "specialists" / "radar-dish.svg"
SPECIALIST_SIZE = 16.0


# --------------------------------------------------------------------------
# Asset extraction
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

    The specialist icons are bare game-icons paths with no fill of their own, so
    they need `fill` set on the symbol for them to inherit; the map objects carry
    their own hardcoded white, which _strip rewrites to currentColor instead.
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
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


# --------------------------------------------------------------------------
# Map model
# --------------------------------------------------------------------------


def classify(s: dict) -> str:
    """Role from the star's own terrain. Position-based roles come later.

    `isBinaryStar` is no use as a marker: the map hands it to every star over 50
    resources, which is the core, the midline binaries and the bridge stars
    alike. The pulsar is the marker for a core, and the black hole for a post.
    """
    if s["isPulsar"]:
        return "core"
    if s["homeStar"]:
        return "capital"
    if s["wormHoleToStarId"] is not None:
        return "post" if s["isBlackHole"] else "gateway"
    if s["isNebula"]:
        return "nebula"
    if s["isAsteroidField"]:
        return "asteroid"
    if s["playerId"] is not None:
        return "satellite"
    return "filler"                     # the rest are re-labelled by position in load()


def load(source: Path):
    data = json.loads(source.read_text(encoding="utf-8"))
    stars = data["stars"]
    players = {p["id"]: p for p in data["players"]}
    by_id = {s["id"]: s for s in stars}

    for s in stars:
        s["x"] = s["location"]["x"]
        s["y"] = s["location"]["y"]
        s["role"] = classify(s)

    cores = [s for s in stars if s["role"] == "core"]
    for s in stars:
        s["core"] = min(cores, key=lambda c: (c["x"] - s["x"]) ** 2 + (c["y"] - s["y"]) ** 2)
        s["radius"] = math.hypot(s["x"] - s["core"]["x"], s["y"] - s["core"]["y"])

    # Galaxy and wedge indices come from the player ids, which the build script
    # allocates as g * 4 + w + 1. Deriving them from geometry instead would only
    # agree with the build by luck.
    for core in cores:
        members = [s for s in stars if s["core"] is core]
        capitals = [s for s in members if s["role"] == "capital"]
        core["galaxy"] = (min(int(c["playerId"]) for c in capitals) - 1) // PLAYERS_PER_GALAXY
        for capital in capitals:
            capital["wedge"] = (int(capital["playerId"]) - 1) % PLAYERS_PER_GALAXY
        bearings = [(math.atan2(c["y"] - core["y"], c["x"] - core["x"]), c["wedge"])
                    for c in capitals]
        for s in members:
            s["galaxy"] = core["galaxy"]
            if s is core:
                s["wedge"] = None
            elif s["role"] != "capital":
                theta = math.atan2(s["y"] - core["y"], s["x"] - core["x"])
                s["wedge"] = min(bearings, key=lambda b: abs(
                    (theta - b[0] + math.pi) % (2 * math.pi) - math.pi))[1]

        # Everything contested sits on a midline, which is where the two nearest
        # capitals are equidistant - the only way to tell a midline star from an
        # ordinary neutral one without the build script's scratch fields. The
        # richest is the binary; the other is the inner ring's midline star. A
        # midline star belongs to no wedge.
        capital_r = max(c["radius"] for c in capitals)
        for s in members:
            gaps = sorted(math.hypot(s["x"] - c["x"], s["y"] - c["y"]) for c in capitals)
            if s is core or abs(gaps[0] - gaps[1]) > 1e-3:
                continue
            s["wedge"] = None
            if s["role"] == "filler":
                s["role"] = "binary" if s["radius"] > capital_r / 2 else "inner"

        # The bridge star is the one plain star left on a capital's own bearing,
        # between the core and that pod's asteroid field.
        for capital in capitals:
            bearing = math.atan2(capital["y"] - core["y"], capital["x"] - core["x"])
            for s in members:
                if s["role"] != "filler":
                    continue
                theta = math.atan2(s["y"] - core["y"], s["x"] - core["x"])
                if abs((theta - bearing + math.pi) % (2 * math.pi) - math.pi) < 1e-6:
                    s["role"] = "bridge"

        # The fringe arc is the rest of what a post sees on its black hole
        # alone: neutral stars off the midline itself, in mirror pairs either
        # side of the binary.
        for post in (s for s in members if s["role"] == "post"):
            for s in members:
                if s["role"] == "filler" and math.hypot(s["x"] - post["x"],
                                                        s["y"] - post["y"]) <= POST_CLEARANCE:
                    s["role"] = "fringe"
                    s["wedge"] = None
                    s["post"] = post

    cores.sort(key=lambda c: c["galaxy"])
    return stars, players, by_id, cores


def fringe_radius(stars) -> float:
    """Radius of a galaxy: its outermost star's distance from its core."""
    return max(s["radius"] for s in stars)


def fit_gradient(stars):
    """Recover R and the exponent of NR = 10 + 90 * (1 - r/R)^k from the stars.

    The build script solves the exponent at runtime and does not record it, so
    the only honest way to draw resource contours is to read it back off the map.
    """
    fringe = fringe_radius(stars)
    samples = []
    for s in stars:
        if s["role"] not in ("filler", "satellite", "gateway", "post", "fringe"):
            continue      # core, capital and the features all override the curve
        nr = s["naturalResources"]["economy"]
        t = 1.0 - s["radius"] / fringe
        if not (NR_MIN < nr < NR_MAX) or t <= 0.0:
            continue
        samples.append(math.log((nr - NR_MIN) / (NR_MAX - NR_MIN)) / math.log(t))
    return fringe, statistics.median(samples)


def contour_radius(nr: float, fringe: float, k: float) -> float:
    return fringe * (1.0 - ((nr - NR_MIN) / (NR_MAX - NR_MIN)) ** (1.0 / k))


def colour_of(s: dict, players: dict) -> str:
    return "#ffffff" if s["playerId"] is None else players[s["playerId"]]["colour"]["value"]


def shape_of(s: dict, players: dict):
    return None if s["playerId"] is None else players[s["playerId"]]["shape"]


def jitter(seed: str, salt: int = 0) -> float:
    """Deterministic 0..360, so re-running the script never churns the output."""
    return ((int(seed) * 2654435761 + salt * 40503) & 0xFFFFFFFF) % 3600 / 10.0


def nr_text(s: dict) -> str:
    nr = s["naturalResources"]
    return f'{nr["economy"]}/{nr["industry"]}/{nr["science"]}'


# --------------------------------------------------------------------------
# Drawing primitives
# --------------------------------------------------------------------------


def n(v: float) -> str:
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
# Shared defs
# --------------------------------------------------------------------------


def build_defs(players: dict) -> str:
    parts = ["<defs>"]
    for name, path in STAR_FILES.items():
        parts.append(symbol_from_svg(path, name))
    for name, path in SHAPE_FILES.items():
        parts.append(symbol_from_svg(path, f"shape-{name}"))
    parts.append(symbol_from_svg(SPECIALIST_FILE, "spec-array", fill="currentColor"))
    # Wrapped in <symbol> rather than referenced as a bare <image>: <use> only
    # honours width/height when the referent is a <symbol> or an <svg>.
    def png_symbol(symbol_id: str, path: Path) -> str:
        return (f'<symbol id="{symbol_id}" viewBox="0 0 1 1" preserveAspectRatio="none">'
                f'<image href="{data_uri(path)}" width="1" height="1" '
                f'preserveAspectRatio="none"/></symbol>')

    for index, path in enumerate(NEBULA_PNGS):
        parts.append(png_symbol(f"neb{index}", path))
    for index, path in enumerate(ASTEROID_PNGS):
        parts.append(png_symbol(f"ast{index}", path))
    parts.append(png_symbol("vortex", VORTEX_PNG))

    for colour in sorted({p["colour"]["value"] for p in players.values()} | {"#ffffff"}):
        parts.append(
            f'<filter id="tint{colour.lstrip("#")}" x="-20%" y="-20%" width="140%" '
            f'height="140%" color-interpolation-filters="sRGB">'
            f'<feFlood flood-color="{colour}" result="flood"/>'
            f'<feComposite in="flood" in2="SourceAlpha" operator="in"/></filter>')

    parts.append('<radialGradient id="halo">'
                 '<stop offset="0%" stop-color="currentColor" stop-opacity="0.50"/>'
                 '<stop offset="55%" stop-color="currentColor" stop-opacity="0.09"/>'
                 '<stop offset="100%" stop-color="currentColor" stop-opacity="0"/>'
                 '</radialGradient>')
    parts.append('<radialGradient id="coreglow">'
                 '<stop offset="0%" stop-color="#ffd27f" stop-opacity="0.16"/>'
                 '<stop offset="38%" stop-color="#ff9f0c" stop-opacity="0.05"/>'
                 '<stop offset="100%" stop-color="#ff9f0c" stop-opacity="0"/>'
                 '</radialGradient>')
    parts.append("</defs>")
    return "".join(parts)


# --------------------------------------------------------------------------
# Star rendering
# --------------------------------------------------------------------------


def draw_star(s: dict, players: dict, label: bool = True, scan: bool = True,
              marks: bool = True):
    """Return (terrain, body, detail) layers for one star.

    `label` adds the resource/id text, `marks` the rings that call out the core
    and the black hole posts, `scan` a post's scan bubble - all three are diagram
    furniture, and the full map render turns them off.
    """
    cx, cy = s["x"], s["y"]
    colour = colour_of(s, players)
    role = s["role"]
    terrain, body, detail = [], [], []

    if s["isNebula"]:
        png = f'neb{int(s["id"]) % len(NEBULA_PNGS)}'
        terrain.append(texture(png, cx, cy, NEBULA_SIZE, 0.55, jitter(s["id"]), colour))
        terrain.append(texture(png, cx, cy, NEBULA_SIZE, 0.35, jitter(s["id"], 1), colour))
    if s["isAsteroidField"]:
        png = f'ast{int(s["id"]) % len(ASTEROID_PNGS)}'
        terrain.append(texture(png, cx, cy, ASTEROID_SIZE, 0.9, jitter(s["id"], 2), colour))
    if s["wormHoleToStarId"] is not None:
        terrain.append(texture("vortex", cx, cy, WORMHOLE_SIZE, 0.4, jitter(s["id"], 3), colour))

    halo = 26.0 * (1.8 if role == "core" else 1.0)
    terrain.append(f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(halo)}" '
                   f'fill="url(#halo)" color="{colour}"/>')

    scale = 1.8 if role == "core" else 1.0
    if s["specialistId"] == SPECIALIST_TELESCOPE_ARRAY:
        # star.ts:954 - a star carrying a specialist shows its badge instead of
        # its own glyph, so every post wears its array.
        body.append(use("spec-array", cx, cy, SPECIALIST_SIZE, colour))
    else:
        # star.ts:954 - the binary glyph is the editor's own, and it marks every
        # star over 50 resources: the core, the binaries, the bridge stars.
        glyph = "star-binary" if s["isBinaryStar"] else ("star-home" if s["homeStar"] else "star")
        body.append(use(glyph, cx, cy, STAR_SIZE * scale, colour))

    if s["isPulsar"]:
        # star.ts:277 - the editor draws a pulsar as a bar through the star with
        # rings either side of it.
        body.append(line(cx, cy - 20 * scale, cx, cy + 20 * scale, colour, 1.6, 0.9))
        for radius in (5, 8):
            for side in (-1, 1):
                body.append(circle(cx + side * radius * scale, cy, radius * scale,
                                   colour, 1.4, 0.75))

    shape = shape_of(s, players)
    if shape:
        body.append(use(f"shape-{shape}", cx, cy, SHAPE_SIZE, colour, 0.9))

    if marks and role == "core":
        body.append(circle(cx, cy, 27, AMBER, 1.8, 0.95))
        body.append(circle(cx, cy, 36, AMBER, 0.9, 0.45, dash="6 5"))
    if role == "post":
        if scan:
            # What the black hole shows on its own, and how far the array reaches.
            body.append(circle(cx, cy, POST_CLEARANCE, colour, 1.6, 0.38, dash="14 10"))
            body.append(circle(cx, cy, POST_SCAN, colour, 1.4, 0.28, dash="6 12"))
        if marks:
            body.append(circle(cx, cy, 20, colour, 1.6, 0.9))

    if label:
        detail.append(text(cx, cy + 27, nr_text(s), 8, "#9fb3c8", opacity=0.8))
        detail.append(text(cx, cy - 20, s["id"], 7, FAINT, opacity=0.6))
        if s["ships"]:
            # Garrison to the right of the star, where star.ts:747 puts it, and
            # in the owner's colour - only owned stars carry ships.
            detail.append(text(cx + 16, cy + 3, str(s["ships"]), 9, colour,
                               anchor="start", weight="700", opacity=0.95))

    return "".join(terrain), "".join(body), "".join(detail)


# --------------------------------------------------------------------------
# Full map
# --------------------------------------------------------------------------


def map_frame(stars):
    xs = [s["x"] for s in stars]
    ys = [s["y"] for s in stars]
    pad = 560.0
    min_x, max_x = min(xs) - pad, max(xs) + pad
    min_y, max_y = min(ys) - pad, max(ys) + pad
    return min_x, min_y, max_x - min_x, max_y - min_y


def map_targets(stars, cores) -> dict:
    """Normalised jump targets, so the page's viewer can fly to a galaxy."""
    min_x, min_y, width, height = map_frame(stars)
    fringe = fringe_radius(stars)
    return {
        "width": round(width, 2),
        "height": round(height, 2),
        "targets": [{"label": f'Galaxy {c["galaxy"] + 1}',
                     "x": round((c["x"] - min_x) / width, 5),
                     "y": round((c["y"] - min_y) / height, 5),
                     "r": round(fringe * 1.35 / width, 5)} for c in cores],
    }


def render_map(stars, players, by_id, cores) -> str:
    """The whole ring: every star labelled, every wormhole, every scan bubble.

    Carries no title block - the figure is captioned by the page that embeds it,
    so a headline and a legend baked into the artwork would only say it twice.
    """
    min_x, min_y, width, height = map_frame(stars)
    max_y = min_y + height

    fringe, exponent = fit_gradient(stars)
    layers = {k: [] for k in ("glow", "link", "terrain", "body", "detail", "chrome")}

    # Resource escalation: a warm core glow plus contour rings at round values.
    for core in cores:
        layers["glow"].append(f'<circle cx="{n(core["x"])}" cy="{n(core["y"])}" '
                              f'r="{n(fringe * 0.9)}" fill="url(#coreglow)"/>')
        for value in (20, 40, 70):
            layers["glow"].append(circle(core["x"], core["y"],
                                         contour_radius(value, fringe, exponent),
                                         AMBER, 1.6, 0.16, dash="10 16"))

    # Wormhole web: each pair once, drawn white as WormHoleLayer draws it
    # (src/scripts/wormHole.ts:38) - both ends are neutral now, so there is no
    # owner's colour to borrow - but bowed towards the ring centre, so the 36
    # chords stay legible instead of piling into a single bundle.
    drawn = set()
    for s in stars:
        target = s["wormHoleToStarId"]
        if target is None or frozenset((s["id"], target)) in drawn:
            continue
        drawn.add(frozenset((s["id"], target)))
        other = by_id[target]
        mx, my = (s["x"] + other["x"]) / 2.0, (s["y"] + other["y"]) / 2.0
        layers["link"].append(
            f'<path d="M {n(s["x"])} {n(s["y"])} Q {n(mx * 0.55)} {n(my * 0.55)} '
            f'{n(other["x"])} {n(other["y"])}" fill="none" stroke="#ffffff" '
            f'stroke-width="2.6" opacity="0.28" stroke-linecap="round"/>')

    for s in stars:
        terrain, body, detail = draw_star(s, players)
        layers["terrain"].append(terrain)
        layers["body"].append(body)
        layers["detail"].append(detail)

    for core in cores:
        layers["chrome"].append(circle(core["x"], core["y"], fringe, FAINT, 2.4, 0.30,
                                       dash="20 16"))
        layers["chrome"].append(text(core["x"], core["y"] - fringe - 46,
                                     f'GALAXY {core["galaxy"] + 1}', 82, "#7f93a8",
                                     opacity=0.9, weight="700"))

    for s in stars:
        if s["role"] != "capital":
            continue
        away = math.atan2(s["y"] - s["core"]["y"], s["x"] - s["core"]["x"])
        layers["chrome"].append(
            text(s["x"] + math.cos(away) * 52, s["y"] + math.sin(away) * 52 + 10,
                 f'P{s["playerId"]}', 34, colour_of(s, players), opacity=0.95, weight="700"))

    # Scale bar, in the light years every range calculation is denominated in.
    bar = 10 * LIGHT_YEAR
    bx, by = min_x + 220, max_y - 240
    layers["chrome"].append(line(bx, by, bx + bar, by, MUTED, 5, 0.9))
    for end in (bx, bx + bar):
        layers["chrome"].append(line(end, by - 16, end, by + 16, MUTED, 5, 0.9))
    layers["chrome"].append(text(bx + bar / 2, by - 32,
                                 f"10 light years ({bar:.0f}u)", 38, MUTED, opacity=0.9))

    homes = sum(1 for s in stars if s["homeStar"])
    order = ["glow", "link", "terrain", "body", "detail", "chrome"]
    content = "".join(f'<g id="layer-{k}">{"".join(layers[k])}</g>' for k in order)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="{SVG_NS}" viewBox="{n(min_x)} {n(min_y)} {n(width)} {n(height)}" '
        f'width="{n(width)}" height="{n(height)}">'
        f'<title>Spy v Spy — {homes} player Solaris map</title>{build_defs(players)}'
        f'<rect x="{n(min_x)}" y="{n(min_y)}" width="{n(width)}" height="{n(height)}" '
        f'fill="{INK}"/>{content}</svg>')


# --------------------------------------------------------------------------
# Pod diagram
# --------------------------------------------------------------------------


def render_pod(stars, players, by_id, cores, player_id: str = "1") -> str:
    """One pod, rotated so its bisector runs left to right, with numbered callouts.

    Labels are never placed next to the stars - they go in a legend band under the
    diagram, keyed by number - so nothing can collide however the geometry falls.
    """
    player = players[player_id]
    capital = by_id[player["homeStarId"]]
    core = capital["core"]
    wedge, galaxy = capital["wedge"], capital["galaxy"]

    phi = math.atan2(capital["y"] - core["y"], capital["x"] - core["x"])
    ca, sa = math.cos(-phi), math.sin(-phi)

    def to_local(s):
        dx, dy = s["x"] - core["x"], s["y"] - core["y"]
        return dict(s, x=dx * ca - dy * sa, y=dx * sa + dy * ca)

    members = [s for s in stars if s["core"] is core]
    # The contested lane on one side of the pod: the midline this player shares
    # with the next wedge round, a quarter turn anticlockwise of their bisector.
    # Its stars are the ones whose bearing falls in that midline's half-sector.
    lane_bearing = (phi + math.pi / 4.0) % (2 * math.pi)

    def on_lane(s) -> bool:
        theta = math.atan2(s["y"] - core["y"], s["x"] - core["x"])
        return abs((theta - lane_bearing + math.pi) % (2 * math.pi) - math.pi) < math.pi / 4.0

    lane = [s for s in members if s["wedge"] is None and s is not core and on_lane(s)]
    neighbour = min((c for c in members if c["role"] == "capital" and c is not capital),
                    key=lambda c: math.hypot(c["x"] - lane[0]["x"], c["y"] - lane[0]["y"]))
    subject = [s for s in members if s["wedge"] == wedge]
    view = [to_local(s) for s in subject + lane + [core]]

    pick = {v["id"]: v for v in view}
    cap = pick[capital["id"]]
    core_v = pick[core["id"]]
    gateway = next(v for v in view if v["role"] == "gateway")
    post = next(v for v in view if v["role"] == "post")
    binary = next(v for v in view if v["role"] == "binary")
    fringe = [v for v in view if v["role"] == "fringe"]
    nebula = next(v for v in view if v["role"] == "nebula")
    asteroid = next(v for v in view if v["role"] == "asteroid")
    bridge = next(v for v in view if v["role"] == "bridge")
    ring = next(v for v in view if v["role"] == "inner")
    satellites = sorted((v for v in view if v["role"] == "satellite"),
                        key=lambda v: v["radius"])
    inner, outer = satellites[0], satellites[-2:]
    # Every distance quoted in the legend, read off the map rather than restated.
    to_capital = math.hypot(gateway["x"] - cap["x"], gateway["y"] - cap["y"])
    to_nebula = math.hypot(gateway["x"] - nebula["x"], gateway["y"] - nebula["y"])
    post_sees = math.hypot(post["x"] - binary["x"], post["y"] - binary["y"])
    arc_hop = min(math.hypot(binary["x"] - v["x"], binary["y"] - v["y"]) for v in fringe)
    ring_gap = math.hypot(ring["x"] - asteroid["x"], ring["y"] - asteroid["y"])

    # The chain the build script tunes to 30 ticks: inner satellite inwards.
    chain = [inner, asteroid, bridge, core_v]
    hops = [math.hypot(a["x"] - b["x"], a["y"] - b["y"]) for a, b in zip(chain, chain[1:])]
    ticks = sum(math.ceil(h / CARRIER_SPEED) for h in hops)

    # Bounds come from the pod's named objects and the post's scan bubble only.
    # The wedge's scattered filler stars are drawn for context but are clipped
    # rather than allowed to stretch the frame.
    named = ([core_v, bridge, asteroid, ring, cap, binary, nebula, gateway, post]
             + satellites + fringe)
    diagram_top = min(min(v["y"] for v in named) - 90, post["y"] - POST_SCAN - 60)
    diagram_bottom = max(max(v["y"] for v in named) + 90, post["y"] + POST_SCAN + 60)
    min_x = min(v["x"] for v in named) - 150
    max_x = max(post["x"] + POST_SCAN + 60, max(v["x"] for v in named) + 150)

    legend_top = diagram_bottom + 70
    parts, diagram = [], []

    # --- diagram ---------------------------------------------------------
    diagram.append(circle(cap["x"], cap["y"], HYPERSPACE_2, GREEN, 2.2, 0.45, dash="13 10"))
    diagram.append(text(cap["x"], cap["y"] - HYPERSPACE_2 - 14,
                        f"hyperspace 2 = {HYPERSPACE_2:.0f}u — the whole pod is one hop wide",
                        17, GREEN, opacity=0.9))

    # The equal-length run to the core.
    for a, b, hop in zip(chain, chain[1:], hops):
        diagram.append(line(a["x"], a["y"], b["x"], b["y"], AMBER, 2.0, 0.5, dash="9 7"))
        diagram.append(text((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2 - 12,
                            f"{hop:.0f}u", 16, AMBER, opacity=0.85))

    for v in view:
        terrain, body, _ = draw_star(v, players, label=False, scan=(v is post))
        diagram.append(terrain)
        diagram.append(body)

    # What a post sees on its black hole alone: the binary and the fringe arc.
    for v in [binary] + fringe:
        diagram.append(circle(v["x"], v["y"], 34, RED, 2.0, 0.85, dash="7 5"))

    callouts = [
        (core_v, 0, -66, "GALACTIC CORE — PULSAR",
         f'{nr_text(core_v)} · infra '
         f'{core_v["infrastructure"]["economy"]}/{core_v["infrastructure"]["industry"]}'
         f'/{core_v["infrastructure"]["science"]} · {ticks} ticks from every pod'),
        (bridge, 0, 64, "BRIDGE STAR",
         f'{nr_text(bridge)} · the only stepping stone between the pod and the core'),
        (asteroid, 0, -64, "ASTEROID FIELD",
         f'{nr_text(asteroid)} · economy ×3 · second hop on the run to the core, and '
         f'one of the eight on the inner ring'),
        (ring, 0, 64, "INNER RING — MIDLINE",
         f'{nr_text(ring)} · neutral · the same ring {ring_gap:.0f}u round from the '
         f'asteroid field, which is what leaves no hole in the middle of a galaxy'),
        (inner, 0, 64, "INNER SATELLITE",
         f'{nr_text(inner)} · the richest of the five, and the pod\'s first step '
         f'towards the core'),
        (cap, 0, -74, f"CAPITAL — P{player_id}",
         f'{nr_text(cap)} · infra '
         f'{cap["infrastructure"]["economy"]}/{cap["infrastructure"]["industry"]}'
         f'/{cap["infrastructure"]["science"]} · {cap["ships"]} ships'),
        (outer[0], 62, -40, "OUTER SATELLITES",
         f'{nr_text(outer[0])} · the far edge of the pod'),
        (nebula, 0, -62, "NEBULA",
         f'{nr_text(nebula)} · science ×3 · the pod\'s last star outward, and the step '
         f'to its gateway'),
        (gateway, 0, -62, f"GATEWAY — P{player_id}'s",
         f'{nr_text(gateway)} · neutral · {to_nebula:.0f}u on past this pod\'s own nebula, '
         f'but {to_capital:.0f}u from the capital, so past hyperspace 4 from it · wormhole '
         f'to a black hole post in galaxy '
         f'{by_id[gateway["wormHoleToStarId"]]["galaxy"] + 1}'),
        (binary, 0, 62, "CONTESTED BINARY",
         f'{nr_text(binary)} · neutral · the richest star outside the core, on the same '
         f'ring as the outermost starting stars and the same distance from every star '
         f'P{player_id} and P{neighbour["playerId"]} own'),
        (fringe[0], 58, 40, f"FRINGE ARC — {len(fringe)} STARS",
         f'{nr_text(fringe[0])} · neutral · mirror pairs either side of the binary, '
         f'{arc_hop:.0f}u apart, so the arc is one hyperspace-1 walk end to end'),
        (post, 0, -70, "BLACK HOLE POST — ARRAY",
         f'{nr_text(post)} · neutral · +{BLACK_HOLE_BONUS} scanning from the hole and '
         f'+{TELESCOPE_BONUS} from the array · the inner dashes are the {POST_CLEARANCE:.0f}u '
         f'the terrain shows alone - the binary and the arc, {post_sees:.0f}u out - the outer '
         f'the {POST_SCAN:.0f}u the array adds, which stops short of either pod · that same '
         f'{post_sees:.0f}u needs hyperspace 4, so the wormhole is the only way in'),
    ]

    # The legend sets the frame's width whenever it is wider than the diagram,
    # and its own two columns are sized off their longest line: the band is
    # monospace at a known size, so both widths are predictable, and letting
    # either overrun would just clip the text away.
    detail_x = 46 + 0.62 * 20.0 * max(len(title) for *_, title, _ in callouts) + 24
    max_x = max(max_x, min_x + 60 + detail_x + 0.62 * 16.0
                * max(len(detail) for *_, detail in callouts) + 60)

    for index, (v, dx, dy, _, _) in enumerate(callouts, start=1):
        diagram.append(line(v["x"], v["y"], v["x"] + dx, v["y"] + dy, MUTED, 1.4, 0.5))
        diagram.append(circle(v["x"] + dx, v["y"] + dy, 17, PAPER, 1.8, 0.95, fill=INK))
        diagram.append(text(v["x"] + dx, v["y"] + dy + 6, str(index), 19, PAPER,
                            weight="700"))

    parts.append(f'<clipPath id="pod-clip"><rect x="{n(min_x)}" y="{n(diagram_top)}" '
                 f'width="{n(max_x - min_x)}" height="{n(diagram_bottom - diagram_top)}"/>'
                 f'</clipPath>')
    parts.append(f'<g clip-path="url(#pod-clip)">{"".join(diagram)}</g>')

    # --- legend band -----------------------------------------------------
    parts.append(line(min_x + 40, legend_top - 34, max_x - 40, legend_top - 34,
                      FAINT, 1.6, 0.5))
    # One column: the detail lines are long enough that two would collide.
    for index, (_, _, _, title, detail) in enumerate(callouts):
        x = min_x + 60
        y = legend_top + 16 + index * 54
        parts.append(circle(x + 15, y - 6, 15, PAPER, 1.6, 0.9, fill=INK))
        parts.append(text(x + 15, y, str(index + 1), 17, PAPER, weight="700"))
        parts.append(text(x + 46, y, title, 20, PAPER, anchor="start", weight="700"))
        parts.append(text(x + detail_x, y, detail, 16, MUTED, anchor="start", opacity=0.95))

    legend_bottom = legend_top + 16 + len(callouts) * 54 + 20
    min_y = diagram_top - 118

    parts.insert(0, f'<rect x="{n(min_x)}" y="{n(min_y)}" width="{n(max_x - min_x)}" '
                    f'height="{n(legend_bottom - min_y)}" fill="{INK}"/>')
    parts.append(text(min_x + 40, min_y + 62, f"ONE POD — player {player_id}, galaxy "
                      f"{galaxy + 1}", 34, PAPER, anchor="start", weight="700"))
    pods = sum(1 for s in stars if s["homeStar"])
    parts.append(text(min_x + 40, min_y + 92,
                      f"all {pods} pods are this shape, rotated — {PLAYERS_PER_GALAXY} to a "
                      f"galaxy, {len(cores)} galaxies",
                      19, MUTED, anchor="start"))

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="{SVG_NS}" viewBox="{n(min_x)} {n(min_y)} {n(max_x - min_x)} '
        f'{n(legend_bottom - min_y)}" width="{n(max_x - min_x)}" '
        f'height="{n(legend_bottom - min_y)}">'
        f'<title>Spy v Spy — anatomy of one pod</title>'
        f'{build_defs(players)}{"".join(parts)}</svg>')


# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("variant", nargs="?", default="36p", choices=sorted(VARIANTS),
                        help="which map in maps/ to render (default: 36p)")
    parser.add_argument("--pod", action="store_true",
                        help="also render the annotated one-pod diagram")
    args = parser.parse_args()

    source_name, prefix = VARIANTS[args.variant]
    source = MAPS_DIR / source_name
    stars, players, by_id, cores = load(source)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"source             {source.relative_to(ROOT)}")
    print(f"galaxies           {len(cores)}, {PLAYERS_PER_GALAXY} players each")

    owned = sum(1 for s in stars if s["playerId"] is not None)
    terrain = collections.Counter()
    for s in stars:
        for key in ("isBinaryStar", "isBlackHole", "isPulsar", "isNebula", "isAsteroidField"):
            if s[key]:
                terrain[key[2:]] += 1
    arrays = sum(1 for s in stars if s["specialistId"] == SPECIALIST_TELESCOPE_ARRAY)
    print(f"stars              {len(stars)}  ({owned} owned at turn 0, "
          f"{len(stars) - owned} neutral)")
    print("terrain            " + ", ".join(f"{key} x{count}"
                                            for key, count in sorted(terrain.items())))
    print(f"specialists        Telescope Array x{arrays}")

    renders = [(f"{prefix}-map.svg", render_map(stars, players, by_id, cores))]
    if args.pod:
        renders.append((f"{prefix}-pod.svg", render_pod(stars, players, by_id, cores)))
    for name, svg in renders:
        path = OUT_DIR / name
        path.write_text(svg, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}  ({path.stat().st_size / 1024:.0f} KB)")

    # Sidecar the viewer picks up automatically to offer per-galaxy jumps.
    targets = OUT_DIR / f"{prefix}-map.json"
    targets.write_text(json.dumps(map_targets(stars, cores), indent=1), encoding="utf-8")
    print(f"wrote {targets.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
