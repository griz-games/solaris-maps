#!/usr/bin/env python3
"""Figures in the study house style: dot-and-range charts, flat vector maps.

Matches `study-fairness.svg` and `study-maps.svg`. Both are plain SVG on a light
ground with no CSS custom properties, so they survive being embedded as a data
URI in a Markdown page, where the chart is its own document and cannot see the
page's tokens.

Two forms only:

    dot_range()  one row per statistic per arm; dot is the median across draws,
                 bar is the range. No probabilities - the reader is shown where
                 the draws actually landed and in what units.

    map_grid()   galaxies as flat scatter plots. Ordinary stars in grey, terrain
                 and capitals picked out, no game art. At grid size the game
                 renderer's textures turn to mud and the shape is the thing.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from solarismap import geometry, metrics

# The study palette, from study-fairness.svg / study-maps.svg.
GROUND = "#fcfcfb"
INK = "#0b0b0b"
MUTED = "#898781"
GRID = "#e1e0d9"
STAR = "#c9c8c2"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]

FONT = "system-ui,-apple-system,sans-serif"


def _t(x, y, s, size=12, fill=INK, anchor="start", weight=400):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{s}</text>')


def _svg(w, h, body, title=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
            f'width="100%" font-family="{FONT}" role="img" aria-label="{title}">'
            f'<rect width="{w:.0f}" height="{h:.0f}" fill="{GROUND}"/>{body}</svg>')


def _nice(value: float) -> str:
    if abs(value) >= 100:
        return f"{value:.0f}"
    if abs(value) >= 10:
        return f"{value:.1f}"
    if abs(value) >= 0.1:
        return f"{value:.2f}"
    return f"{value:.3f}"


# --------------------------------------------------------------------------
# Dot and range
# --------------------------------------------------------------------------


def dot_range(arms: Sequence[str], labels: dict, cells: dict,
              names: Sequence[str], title: str, caption: str,
              shared: bool = True, low_key: str = "q1",
              high_key: str = "q3", width: float = 820.0,
              reference: float | None = None,
              row_label=None) -> str:
    """One row per (statistic, arm). Dot = median across draws, bar = range.

    `cells[arm][name]` is a `metrics.summarise` dict. `shared` puts every
    statistic on one x scale, which only makes sense when they share a unit -
    true for the six fairness spreads, false for compactness and novelty.
    """
    left, right = 190.0, 132.0
    top, bottom = 34.0, 66.0
    # An unshared chart carries a little axis under every block, so it needs
    # more room between blocks than a shared one - otherwise the axis reads as
    # belonging to the row beneath it.
    row_h = 16.0
    gap = 16.0 if shared else 34.0
    plot_w = width - left - right
    block_h = len(arms) * row_h + gap
    height = top + len(names) * block_h + bottom

    body = [_t(0, 16, title, 13, INK, weight=600)]

    if shared:
        lows = [cells[a][n][low_key] for n in names for a in arms if cells[a][n]]
        highs = [cells[a][n][high_key] for n in names for a in arms if cells[a][n]]
        span = (min(lows), max(highs))
        if reference is not None:
            span = (min(span[0], reference), max(span[1], reference))
        pad = (span[1] - span[0]) * 0.04
        span = (span[0] - pad, span[1] + pad)
        for k in range(5):
            v = span[0] + (span[1] - span[0]) * k / 4
            x = left + (v - span[0]) / (span[1] - span[0]) * plot_w
            body.append(f'<line x1="{x:.1f}" y1="{top - 2:.1f}" x2="{x:.1f}" '
                        f'y2="{top + len(names) * block_h - gap + 4:.1f}" '
                        f'stroke="{GRID}"/>')
            body.append(_t(x, top + len(names) * block_h - gap + 22, _nice(v),
                           11, MUTED, "middle"))
        if reference is not None:
            rx = left + (reference - span[0]) / (span[1] - span[0]) * plot_w
            body.append(f'<line x1="{rx:.1f}" y1="{top - 2:.1f}" x2="{rx:.1f}" '
                        f'y2="{top + len(names) * block_h - gap + 4:.1f}" '
                        f'stroke="{INK}" stroke-width="1.5" stroke-dasharray="5 4"/>')

    for i, name in enumerate(names):
        block = top + i * block_h
        if not shared:
            valid = [cells[a][name] for a in arms if cells[a][name]]
            lo = min(c[low_key] for c in valid)
            hi = max(c[high_key] for c in valid)
            pad = (hi - lo) * 0.12 or (abs(hi) * 0.1 or 1.0)
            span = (lo - pad, hi + pad)
            axis_y = block + len(arms) * row_h + 4
            body.append(f'<line x1="{left:.1f}" y1="{axis_y:.1f}" '
                        f'x2="{left + plot_w:.1f}" y2="{axis_y:.1f}" '
                        f'stroke="{GRID}"/>')
            body.append(_t(left, axis_y + 13, _nice(span[0]), 10, MUTED))
            body.append(_t(left + plot_w, axis_y + 13, _nice(span[1]), 10,
                           MUTED, "end"))

        text = row_label(name) if row_label else metrics.LABELS.get(name, name)
        body.append(_t(left - 12, block + row_h - 4, text, 12, INK, "end"))

        for j, arm in enumerate(arms):
            cell = cells[arm][name]
            y = block + j * row_h + row_h / 2
            if not cell:
                continue
            colour = SERIES[j % len(SERIES)]

            def x_of(v):
                return left + (v - span[0]) / (span[1] - span[0]) * plot_w

            x1, x2 = x_of(cell[low_key]), x_of(cell[high_key])
            body.append(f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{max(x2, x1 + 1):.1f}" '
                        f'y2="{y:.1f}" stroke="{colour}" stroke-width="2.5" '
                        f'stroke-linecap="round" opacity="0.5"/>')
            body.append(f'<circle cx="{x_of(cell["median"]):.1f}" cy="{y:.1f}" '
                        f'r="4.2" fill="{colour}"/>')
            body.append(_t(width - right + 10 + j * 42, block + row_h - 4,
                           _nice(cell["median"]), 11, colour))

    # Legend, then the caption that says what the marks mean.
    ly = height - bottom + 34
    cursor = left - 12
    for j, arm in enumerate(arms):
        body.append(f'<circle cx="{cursor + 5:.1f}" cy="{ly - 4:.1f}" r="4.2" '
                    f'fill="{SERIES[j % len(SERIES)]}"/>')
        body.append(_t(cursor + 14, ly, labels[arm], 11, INK))
        cursor += 14 + len(labels[arm]) * 5.9 + 22
    body.append(_t(0, height - 8, caption, 11, MUTED))
    return _svg(width, height, "".join(body), title)


# --------------------------------------------------------------------------
# Maps
# --------------------------------------------------------------------------

TERRAIN = [("isNebula", "#2a78d6", "nebula"),
           ("isAsteroidField", "#eb6834", "asteroid field"),
           ("isBinaryStar", "#1baf7a", "binary / black hole"),
           ("isBlackHole", "#1baf7a", None)]


def _panel(galaxy: dict, x0: float, y0: float, size: float) -> str:
    """One galaxy as a flat scatter, fitted into a square."""
    stars = galaxy["stars"]
    pts = [geometry.star_point(s) for s in stars]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    span = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    scale = (size - 12.0) / span
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0

    out = []
    # Plain stars first, so terrain and capitals sit on top of them.
    for star, (px, py) in zip(stars, pts):
        sx = x0 + size / 2 + (px - cx) * scale
        sy = y0 + size / 2 + (py - cy) * scale
        colour, radius = STAR, 1.6
        for field, hue, _ in TERRAIN:
            if star.get(field):
                colour, radius = hue, 2.3
                break
        if star.get("homeStar"):
            colour, radius = INK, 3.0
        out.append((0 if colour is STAR else 1,
                    f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{radius}" '
                    f'fill="{colour}"/>'))
    out.sort(key=lambda pair: pair[0])
    return "".join(markup for _, markup in out)


def map_grid(rows: Sequence[tuple[str, Sequence[dict]]], title: str,
             caption: str, cell: float = 250.0) -> str:
    """A row of galaxies per condition. One SVG, so it cannot break up."""
    label_w = 210.0
    pad = 10.0
    columns = max(len(g) for _, g in rows)
    width = label_w + columns * (cell + pad)
    scale = width / 820.0
    height = 30.0 + len(rows) * (cell + pad) + 52.0 * scale

    # This figure is far wider than the charts, so the page scales it down
    # harder. Type is sized in its own coordinate space to land at roughly the
    # same rendered size as everything else.
    body = [_t(0, 16 * scale, title, 13 * scale, INK, weight=600)]
    # The label column is fixed, the type scales with the figure, so the
    # descriptor has to wrap or it runs under the first panel.
    def wrapped(text: str, chars: int = 15) -> list[str]:
        lines, current = [], ""
        for word in text.split():
            if current and len(current) + 1 + len(word) > chars:
                lines.append(current)
                current = word
            else:
                current = f"{current} {word}".strip()
        return lines + ([current] if current else [])

    for i, (label, galaxies) in enumerate(rows):
        y0 = 30.0 + i * (cell + pad)
        head, _, tail = label.partition("\n")
        lines = [(head, INK, 600)] + [(l, MUTED, 400) for l in wrapped(tail)]
        step = 15 * scale
        start = y0 + cell / 2 - (len(lines) - 1) * step / 2
        for n, (line, hue, weight) in enumerate(lines):
            body.append(_t(0, start + n * step, line, 11.5 * scale, hue,
                           weight=weight))
        for j, galaxy in enumerate(galaxies):
            body.append(_panel(galaxy, label_w + j * (cell + pad), y0, cell))

    ly = height - 30.0 * scale
    cursor = 0.0
    seen = set()
    legend = [(hue, name) for _, hue, name in TERRAIN if name and name not in seen
              and not seen.add(name)] + [(INK, "capital")]
    for hue, name in legend:
        body.append(f'<circle cx="{cursor + 4 * scale:.1f}" cy="{ly - 4 * scale:.1f}" '
                    f'r="{3.4 * scale:.1f}" fill="{hue}"/>')
        body.append(_t(cursor + 12 * scale, ly, name, 11 * scale, INK))
        cursor += (12 + len(name) * 5.9 + 20) * scale
    body.append(_t(0, height - 8 * scale, caption, 11 * scale, MUTED))
    return _svg(width, height, "".join(body), title)
