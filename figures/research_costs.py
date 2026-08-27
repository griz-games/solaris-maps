#!/usr/bin/env python3
"""What the cumulative research cost progression actually does.

Two figures, plain SVG in the study house style, sharing one set of axes so
they can be read against each other:

    research-costs.svg           standard against cumulative at x1
    research-costs-scaling.svg   standard against all four scaling factors,
                                 one colour per factor

`y` is the cost of the *next* level, not the running total spent. That is what
`ResearchProgressService.getRequiredResearchProgress` returns, and it is the
number on the research screen.

Run:  python figures/research_costs.py [--tier standard] [--levels 10]
"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from study_figs import GRID, GROUND, INK, MUTED  # noqa: E402

FONT = "system-ui,-apple-system,sans-serif"

# --------------------------------------------------------------------------
# The rules, from the game
# --------------------------------------------------------------------------

# `researchProgressSamples` builds a minimal game to sample the real service,
# and the constants it fills in are the live ones: progressMultiplier 50, and
# the infrastructure expense multiplier of the tier the technology is priced at.
# Their product is `progressMultiplierConfig` - the cost of level 1, and the
# amount every later level is scaled against.
PROGRESS_MULTIPLIER = 50
EXPENSE_MULTIPLIERS = {"cheap": 1, "standard": 2, "expensive": 4,
                       "veryExpensive": 8, "crazyExpensive": 16}

# GAME_CREATION_OPTIONS.technology.researchCostProgressionScalingFactor. Four
# entries, and this is the whole menu - the setting is a dropdown, not a number
# box, so these are the only curves anyone can actually pick.
SCALING_FACTORS = (0.25, 0.5, 0.75, 1.0)

MAX_LEVEL = 10
Y_STEP = 500.0

# The factors are an ordered set, not four unrelated things, so they get a
# single hue stepped light to dark rather than four categorical colours: the
# ramp position *is* the scaling factor. Lightness is monotonic and each step
# is ~1.8x the last, which keeps them apart under colour blindness too, where
# the ramp survives as a lightness ordering. Standard is a different
# progression rather than another point on this scale, so it leaves the ramp
# for the house orange, and is dashed as well as coloured.
FACTOR_COLOURS = {0.25: "#7fb0e8", 0.5: "#3f80d4",
                  0.75: "#18549a", 1.0: "#0a2d5c"}
STANDARD_COLOUR = "#eb6834"


def standard_cost(level: int, base: float) -> float:
    """`progression: "standard"` - technologyLevel * progressMultiplierConfig.

    Each level costs one base more than the one before it, forever.
    """
    return level * base


def cumulative_cost(level: int, base: float, scaling: float) -> float:
    """`progression: "cumulative"`, transcribed term for term from upstream.

    Read as [sum of every level up to L] * [increase per level] + [what level 1
    is short by], the third term existing only because level 1 is charged the
    flat base cost whatever the scaling factor says.
    """
    return (0.5 * base * scaling * (level * (level + 1))
            + base * (1 - scaling))


def cumulative_cost_longhand(level: int, base: float, scaling: float) -> float:
    """The same number reached the other way: X + ([sum of levels] - 1) * X * S.

    Kept because it is the form that explains the upstream one rather than the
    form the upstream one is written in. The sum of every level up to N is
    N(N+1)/2; the -1 drops level 1 back out, since it is not scaled. `main`
    asserts the two agree at every level, factor and tier.
    """
    levels_sum = level * (level + 1) / 2
    return base + (levels_sum - 1) * (base * scaling)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


def _t(x, y, s, size=12, fill=INK, anchor="start", weight=400):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}">{s}</text>')


def _svg(w, h, body, title=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
            f'width="100%" font-family="{FONT}" role="img" aria-label="{title}">'
            f'<rect width="{w:.0f}" height="{h:.0f}" fill="{GROUND}"/>{body}</svg>')


def _money(v: float) -> str:
    return f"{v:,.0f}"


def chart(title: str, series: Sequence[tuple[str, str, bool, list[float]]],
          max_level: int = MAX_LEVEL, y_step: float = Y_STEP) -> str:
    """One line chart, one point per level, each line labelled at its end.

    `series` is (label, colour, dashed, costs). Nothing is annotated beyond the
    title, the tick numbers and those end labels - the grid is fine enough to
    read a value off directly, so a caption would only repeat it.
    """
    width, height = 820.0, 470.0
    left, right, top, bottom = 78.0, 76.0, 56.0, 52.0
    plot_w = width - left - right
    plot_h = height - top - bottom

    levels = list(range(1, max_level + 1))
    peak = max(max(costs) for _, _, _, costs in series)
    y_top = math.ceil(peak / y_step) * y_step

    def px(level: int) -> float:
        return left + (level - 1) / (max_level - 1) * plot_w

    def py(cost: float) -> float:
        return top + plot_h - cost / y_top * plot_h

    body = [_t(0, 20, title, 14, INK, weight=600)]

    # Horizontal grid every `y_step`, labelled on every line. Vertical grid at
    # every level too: with a point per level the reader is reading individual
    # levels off, not a trend, so the columns earn their keep here.
    v = 0.0
    while v <= y_top + 1e-6:
        y = py(v)
        body.append(f'<line x1="{left:.1f}" y1="{y:.1f}" x2="{left + plot_w:.1f}" '
                    f'y2="{y:.1f}" stroke="{GRID}"/>')
        body.append(_t(left - 10, y + 4, _money(v), 11, MUTED, "end"))
        v += y_step
    for level in levels:
        x = px(level)
        body.append(f'<line x1="{x:.1f}" y1="{top:.1f}" x2="{x:.1f}" '
                    f'y2="{top + plot_h:.1f}" stroke="{GRID}"/>')
        body.append(_t(x, top + plot_h + 20, str(level), 11, MUTED, "middle"))

    body.append(f'<line x1="{left:.1f}" y1="{top + plot_h:.1f}" '
                f'x2="{left + plot_w:.1f}" y2="{top + plot_h:.1f}" '
                f'stroke="{MUTED}"/>')
    body.append(_t(left + plot_w / 2, top + plot_h + 40, "level", 11.5, MUTED,
                   "middle"))

    for label, colour, dashed, costs in series:
        points = [(px(l), py(c)) for l, c in zip(levels, costs)]
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        body.append(f'<polyline points="{pts}" fill="none" stroke="{colour}" '
                    f'stroke-width="2" stroke-linejoin="round" '
                    f'stroke-linecap="round"{dash}/>')
        # Every level is a discrete purchase, so every level gets a mark. The
        # paper ring keeps them apart at level 1, where all five coincide.
        for x, y in points:
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.2" '
                        f'fill="{colour}" stroke="{GROUND}" stroke-width="1.4"/>')
        ex, ey = points[-1]
        body.append(_t(ex + 10, ey + 4, label, 12, colour, weight=600))

    return _svg(width, height, "".join(body), title)


# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", default="standard",
                        choices=sorted(EXPENSE_MULTIPLIERS),
                        help="expense tier the technology is priced at")
    parser.add_argument("--levels", type=int, default=MAX_LEVEL,
                        help="highest technology level to draw")
    args = parser.parse_args()

    base = EXPENSE_MULTIPLIERS[args.tier] * PROGRESS_MULTIPLIER
    levels = list(range(1, args.levels + 1))

    # The claim the figures rest on: the two ways of writing the cumulative
    # cost are the same number, at every tier, factor and level.
    for tier_base in (m * PROGRESS_MULTIPLIER
                      for m in EXPENSE_MULTIPLIERS.values()):
        for factor in SCALING_FACTORS:
            for level in range(1, 101):
                a = cumulative_cost(level, tier_base, factor)
                b = cumulative_cost_longhand(level, tier_base, factor)
                assert math.isclose(a, b, rel_tol=1e-12), (level, factor, a, b)

    flat = ("Standard", STANDARD_COLOUR, True,
            [standard_cost(l, base) for l in levels])
    cumulative = [(f"x{f:g}", FACTOR_COLOURS[f], False,
                   [cumulative_cost(l, base, f) for l in levels])
                  for f in SCALING_FACTORS]

    title = "Cumulative research costs compared to standard"
    figures = {
        "research-costs.svg": chart(title, [flat, cumulative[-1]], args.levels),
        "research-costs-scaling.svg": chart(title, [flat, *cumulative],
                                            args.levels),
    }

    out = Path(__file__).resolve().parent
    for name, svg in figures.items():
        (out / name).write_text(svg, encoding="utf-8")
        print(f"wrote {out / name}")

    print(f"\n{args.tier} tier, progressMultiplierConfig = {_money(base)}")
    header = "level".rjust(6) + "standard".rjust(11)
    header += "".join(f"x{f:g}".rjust(11) for f in SCALING_FACTORS)
    print(header)
    for level in levels:
        row = str(level).rjust(6) + _money(standard_cost(level, base)).rjust(11)
        row += "".join(_money(cumulative_cost(level, base, f)).rjust(11)
                       for f in SCALING_FACTORS)
        print(row)


if __name__ == "__main__":
    main()
