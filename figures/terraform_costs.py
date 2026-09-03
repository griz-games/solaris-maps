#!/usr/bin/env python3
"""What terraforming does to the price of infrastructure.

    terraform-costs.svg   a 3x4 grid: natural resources across, infrastructure
                          type down, one colour per terraforming level

Terraforming does not discount anything directly. It raises the star's
terraformed resources, and terraformed resources sit in the *denominator* of
the upgrade cost, so every point of terraforming makes every future purchase on
that star cheaper. The grid is the same curve seen at three starting resource
levels and four infrastructure types.

Run:  python figures/terraform_costs.py [--tier standard] [--purchases 10]
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

from solarismap import rules  # noqa: E402
from study_figs import GRID, GROUND, INK, MUTED  # noqa: E402

FONT = "system-ui,-apple-system,sans-serif"
# The formula and the table are read a character at a time and a column at a
# time, so they get a monospace stack rather than the chart's UI face.
# Single quotes inside: this goes into a double-quoted SVG attribute, and a
# family name in double quotes would close it and break the document.
MONO = "ui-monospace,'Cascadia Mono',Consolas,'DejaVu Sans Mono',monospace"

# --------------------------------------------------------------------------
# The rules, from the game
# --------------------------------------------------------------------------

# `starUpgrade._calculateInfrastructureCost`:
#
#     max(1, floor( baseCost * expenseConfig * (current + 1)
#                   / (terraformedResources / 100) ))
#
# baseCost is per infrastructure type; expenseConfig is the tier the game was
# created at. Defaults from `db/models/schemas/game.ts`.
INFRASTRUCTURE_BASE = {"economy": 2.5, "industry": 5.0, "science": 20.0,
                       "warpGate": 50.0}

# `developmentCost` only offers these four - unlike research, there is no
# veryExpensive or crazyExpensive tier for infrastructure. Default is standard.
EXPENSE_MULTIPLIERS = {"cheap": 1, "standard": 2, "expensive": 4}

ROWS = (("economy", "Economy", None),
        ("industry", "Industry", None),
        ("science", "Science", None),
        ("warpGate", "Warp gate", "one purchase only"))

NATURAL_RESOURCES = (25, 50, 100)
TERRAFORMING_LEVELS = (1, 5, 10, 15)
PURCHASES = 10

# Terraforming level is an ordered quantity, so it gets one hue stepped light
# to dark rather than four unrelated colours - ramp position is the level.
# Green rather than the blue the research figure uses, so the two are not
# mistaken for the same variable. Lightness is monotonic and each step is
# ~1.8x the last, which keeps the ordering readable under colour blindness.
TERRAFORM_COLOURS = {1: "#74c9a6", 5: "#209b70", 10: "#146b4c", 15: "#083828"}


def infrastructure_cost(kind: str, expense: int, current: int,
                        terraformed: int) -> int | None:
    """`starUpgrade._calculateInfrastructureCost`, for one purchase.

    `current` is how much of that infrastructure the star already has, so the
    n-th purchase is priced at `current = n - 1`. Returns None for a dead star,
    which cannot be upgraded at all.
    """
    if terraformed <= 0:
        return None
    return max(1, math.floor(INFRASTRUCTURE_BASE[kind] * expense
                             * (current + 1) / (terraformed / 100)))


def warp_gate_cost(expense: int, terraformed: int) -> int | None:
    """`starUpgrade.calculateWarpGateCost`.

    Two things make this row different. `current` is hardcoded to 0 - a star
    either has a warp gate or it does not, so the price never rises. And it
    prices off `calculateAverageTerraformedResources`, the mean of the three
    channels, rather than any one of them. This figure gives every star equal
    resources in all three, so the mean is just the same number.
    """
    return infrastructure_cost("warpGate", expense, 0, terraformed)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


def _t(x, y, s, size=12, fill=INK, anchor="start", weight=400, font=None,
       spacing=None):
    extra = f' font-family="{font}"' if font else ""
    if spacing:
        extra += f' letter-spacing="{spacing}"'
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" '
            f'font-weight="{weight}" text-anchor="{anchor}"{extra}>{s}</text>')


def _heading(x, y, s):
    """A section rule and its label, in the page style the figures share."""
    return _t(x, y, s.upper(), 11, MUTED, weight=600, font=MONO, spacing="1.2")


def _svg(w, h, body, title=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
            f'width="100%" font-family="{FONT}" role="img" aria-label="{title}">'
            f'<rect width="{w:.0f}" height="{h:.0f}" fill="{GROUND}"/>{body}</svg>')


def _money(v: float) -> str:
    return f"{v:,.0f}"


def _percent_label(v: float) -> str:
    return f"{v:.0f}%"


def _percent_saving(baseline: Sequence[int],
                    priced: Sequence[int]) -> list[float]:
    """How much cheaper `priced` is than `baseline`, purchase by purchase.

    Worth doing against the floored integers rather than algebraically. On
    paper the saving is `1 - baseline_resources / priced_resources` and nothing
    else: baseCost and the expense tier cancel, and so does `current + 1`, so
    the same percentage holds for every infrastructure type at every purchase.
    The `floor` and the `max(1, ...)` in the real formula break that exactly
    where the credits are small, and those breaks are the only reason the
    percentage panels are not four flat lines.
    """
    return [100.0 * (1.0 - after / before) if before else 0.0
            for before, after in zip(baseline, priced)]


def _step(span: float, target: int = 6) -> float:
    """A round gridline interval giving roughly `target` lines across `span`."""
    raw = span / target
    magnitude = 10.0 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5):
        if raw <= magnitude * mult:
            return magnitude * mult
    return magnitude * 10


WIDTH = 960.0

# Breathing room on all four sides. The drawing code lays out against WIDTH and
# ignores this; `_document` translates the finished body into place and grows
# the canvas to match, so nothing inside has to know the margin exists.
MARGIN = 32.0


def _document(parts: list[str], content_height: float, title: str) -> str:
    body = (f'<g transform="translate({MARGIN:.0f},{MARGIN:.0f})">'
            f'{"".join(parts)}</g>')
    return _svg(WIDTH + MARGIN * 2, content_height + MARGIN * 2, body, title)


def grid_parts(expense: int, tier: str, purchases: int = PURCHASES,
               chrome: bool = True,
               percent: bool = False) -> tuple[list[str], float]:
    """The 3x4 grid: resources across, infrastructure down, terraforming in hue.

    Returns the markup and the y it finished at, so the reference sections
    below can start from there.

    `chrome` carries the title, the conditions line and the caption. Without it
    the grid is just the panels, their labels and the legend - what goes into a
    document that supplies its own words around the picture.

    `percent` re-expresses every panel as the saving against terraforming 1 on
    the same star, rather than a price. See `_percent_saving` for why that is
    a different figure and not just a rescaled one.
    """
    width = WIDTH
    left, right = 136.0, 18.0
    top = 84.0 if chrome else 40.0
    col_gap, row_gap = 34.0 , 48.0
    panel_w = (width - left - right - col_gap * 2) / 3
    panel_h = 132.0
    grid_bottom = top + 3 * (panel_h + row_gap) + panel_h
    # The legend sits under the grid either way - hue is the only thing telling
    # the four lines in a panel apart, so it is not optional furniture.
    height = grid_bottom + (108.0 if chrome else 66.0)
    legend_y = height - 32.0 if chrome else grid_bottom + 52.0

    purchase_numbers = list(range(1, purchases + 1))

    def costs(kind: str, natural: int, terraforming: int) -> list[int]:
        terraformed = rules.terraformed_resource(natural, terraforming)
        if kind == "warpGate":
            return [warp_gate_cost(expense, terraformed)] * purchases
        return [infrastructure_cost(kind, expense, n - 1, terraformed)
                for n in purchase_numbers]

    def values(kind: str, natural: int, terraforming: int) -> list[float]:
        if not percent:
            return costs(kind, natural, terraforming)
        return _percent_saving(costs(kind, natural, TERRAFORMING_LEVELS[0]),
                               costs(kind, natural, terraforming))

    label_of = _percent_label if percent else _money

    body = []
    if chrome:
        heading = ("What terraforming saves, as a percentage" if percent
                   else "How terraforming changes infrastructure costs")
        conditions = (
            f"Saving against terraforming {TERRAFORMING_LEVELS[0]} on the same "
            "star. Every panel on one scale."
            if percent else
            f"{tier.capitalize()} development cost. Cost of the next purchase; "
            "terraformed resources = natural + 5 x terraforming.")
        body += [_t(0, 20, heading, 14, INK, weight=600),
                 _t(0, 40, conditions, 11.5, MUTED)]

    # Column headers, once. Every panel in a column is the same starting star.
    for j, natural in enumerate(NATURAL_RESOURCES):
        x0 = left + j * (panel_w + col_gap)
        body.append(_t(x0 + panel_w / 2, top - 16,
                       f"{natural} natural resources", 12, INK, "middle",
                       weight=600))

    for i, (kind, label, note) in enumerate(ROWS):
        y0 = top + i * (panel_h + row_gap)

        # In credits, one y scale per row. Rows differ by up to eight times in
        # magnitude - science against economy - so a scale shared down the grid
        # would press the economy row flat. Shared across the row is the
        # comparison that matters: what the starting resources are worth.
        #
        # In percent, one scale for the whole grid. The unit is the same
        # everywhere and the panels are supposed to be compared, not just read.
        if percent:
            peak = max(max(values(k, natural, t))
                       for k, _, _ in ROWS
                       for t in TERRAFORMING_LEVELS
                       for natural in NATURAL_RESOURCES)
        else:
            peak = max(max(values(kind, natural, t))
                       for t in TERRAFORMING_LEVELS
                       for natural in NATURAL_RESOURCES)
        step = _step(peak)
        y_top = math.ceil(peak / step) * step

        def py(cost: float, y0: float = y0, y_top: float = y_top) -> float:
            return y0 + panel_h - cost / y_top * panel_h

        # Row label in the left margin, vertically centred on the row.
        body.append(_t(0, y0 + panel_h / 2 + (0 if note is None else -4), label,
                       12.5, INK, weight=600))
        if note:
            body.append(_t(0, y0 + panel_h / 2 + 13, note, 11, MUTED))

        for j, natural in enumerate(NATURAL_RESOURCES):
            x0 = left + j * (panel_w + col_gap)

            def px(n: int, x0: float = x0) -> float:
                return x0 + (n - 1) / (purchases - 1) * panel_w

            v = 0.0
            while v <= y_top + 1e-6:
                y = py(v)
                body.append(f'<line x1="{x0:.1f}" y1="{y:.1f}" '
                            f'x2="{x0 + panel_w:.1f}" y2="{y:.1f}" '
                            f'stroke="{GRID}"/>')
                if j == 0:
                    body.append(_t(left - 12, y + 4, label_of(v), 10.5,
                                   MUTED, "end"))
                v += step
            # A gridline per purchase, in every panel: the tick numbers only
            # run under the bottom row, and these are what makes them countable
            # further up.
            for n in purchase_numbers:
                x = px(n)
                body.append(f'<line x1="{x:.1f}" y1="{y0:.1f}" x2="{x:.1f}" '
                            f'y2="{y0 + panel_h:.1f}" stroke="{GRID}"/>')
                if i == len(ROWS) - 1:
                    body.append(_t(x, y0 + panel_h + 20, str(n), 10.5, MUTED,
                                   "middle"))
            body.append(f'<line x1="{x0:.1f}" y1="{y0 + panel_h:.1f}" '
                        f'x2="{x0 + panel_w:.1f}" y2="{y0 + panel_h:.1f}" '
                        f'stroke="{MUTED}"/>')

            for terraforming in TERRAFORMING_LEVELS:
                series = values(kind, natural, terraforming)
                colour = TERRAFORM_COLOURS[terraforming]
                points = [(px(n), py(c))
                          for n, c in zip(purchase_numbers, series)]
                pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
                body.append(f'<polyline points="{pts}" fill="none" '
                            f'stroke="{colour}" stroke-width="2" '
                            f'stroke-linejoin="round" stroke-linecap="round"/>')
                # Every purchase is discrete, so every purchase gets a mark.
                # The paper ring keeps them apart where lines converge.
                for x, y in points:
                    body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4" '
                                f'fill="{colour}" stroke="{GROUND}" '
                                f'stroke-width="1.2"/>')

    if chrome:
        body.append(_t(left + (width - right - left) / 2, grid_bottom + 42,
                       "purchase number on this star", 11.5, MUTED, "middle"))

    # One legend for the whole grid: hue is the only thing separating the four
    # lines inside a panel, and there are twelve panels to key.
    body.append(_t(0, legend_y, "Terraforming level", 11, MUTED))
    cursor = 118.0
    for terraforming in TERRAFORMING_LEVELS:
        body.append(f'<circle cx="{cursor + 5:.1f}" cy="{legend_y - 4:.1f}" '
                    f'r="4.2" fill="{TERRAFORM_COLOURS[terraforming]}"/>')
        body.append(_t(cursor + 15, legend_y, str(terraforming), 11.5, INK,
                       weight=600))
        cursor += 15 + len(str(terraforming)) * 7 + 26

    if chrome:
        body.append(_t(0, height - 10,
                       "Terraformed resources divide the cost rather than "
                       "subtracting from it. Each row shares one scale, so the "
                       "flattening to the right is the star's own resources "
                       "doing the same job.", 11, MUTED))

    return body, height


# The four terms, each short enough to sit on one line at this width. Anything
# that needed wrapping would need hand-measured line breaks, which is a poor
# trade against just saying less.
TERMS = (
    ("baseCost", "2.5 economy, 5 industry, 20 science, 50 warp gate. Fixed "
                 "constants, not a setting."),
    ("expense", "the game's developmentCost tier: cheap 1, standard 2, "
                "expensive 4. No very- or crazy-expensive here."),
    ("current", "what the star already has, so the n-th purchase is priced at "
                "current = n - 1. Hardcoded to 0 for a warp gate."),
    ("terraformed", "the channel's own terraformed resource. A warp gate uses "
                    "the mean of all three - equal here, so the same number."),
)


def formula_parts(y: float) -> tuple[list[str], float]:
    """The two rules the grid is drawn from, and what each term is."""
    body = [f'<line x1="0" y1="{y:.1f}" x2="{WIDTH:.0f}" y2="{y:.1f}" '
            f'stroke="{GRID}"/>']
    y += 30
    body.append(_heading(0, y, "The formula"))
    y += 26

    plate_top = y - 4
    plate_h = 92.0
    body.append(f'<rect x="0" y="{plate_top:.1f}" width="{WIDTH:.0f}" '
                f'height="{plate_h:.1f}" fill="#f3f1ea"/>')
    body.append(f'<rect x="0" y="{plate_top:.1f}" width="2" '
                f'height="{plate_h:.1f}" fill="{INK}"/>')

    y += 18
    body.append(_t(20, y, "STARUPGRADE._CALCULATEINFRASTRUCTURECOST", 10, MUTED,
                   font=MONO, spacing="1"))
    y += 20
    body.append(_t(20, y, "max( 1, floor( baseCost · expense · (current + 1) "
                          "÷ (terraformed ÷ 100) ) )", 14, INK,
                   weight=500, font=MONO))
    y += 22
    body.append(_t(20, y, "STAR.CALCULATETERRAFORMEDRESOURCE", 10, MUTED,
                   font=MONO, spacing="1"))
    y += 20
    body.append(_t(20, y, "floor( natural + 5 · terraforming )", 14, INK,
                   weight=500, font=MONO))

    y = plate_top + plate_h + 28
    for name, description in TERMS:
        body.append(_t(0, y, name, 12.5, INK, weight=600, font=MONO))
        body.append(_t(112, y, description, 12.5, MUTED))
        y += 22
    return body, y + 12


TABLE_COLUMNS = (("Natural", 0.0, "start"), ("Terraforming", 178.0, "end"),
                 ("Terraformed", 300.0, "end"), ("Economy", 470.0, "end"),
                 ("Industry", 630.0, "end"), ("Science", 790.0, "end"),
                 # Aligned with the right edge of the panels above, not the
                 # canvas, so the last column does not sit flush to the crop.
                 ("Warp gate", 942.0, "end"))


def table_parts(expense: int, purchases: int,
                y: float) -> tuple[list[str], float]:
    """Every cell the grid plots, as numbers, banded by natural resources."""
    body = [f'<line x1="0" y1="{y:.1f}" x2="{WIDTH:.0f}" y2="{y:.1f}" '
            f'stroke="{GRID}"/>']
    y += 30
    body.append(_heading(0, y, f"Every cell, 1st purchase → {purchases}th"))
    y += 30

    for label, x, anchor in TABLE_COLUMNS:
        body.append(_t(x, y, label.upper(), 10, MUTED, anchor, weight=600,
                       font=MONO, spacing="0.8"))
    y += 8
    body.append(f'<line x1="0" y1="{y:.1f}" x2="{WIDTH:.0f}" y2="{y:.1f}" '
                f'stroke="{INK}"/>')

    row_h = 21.0
    for natural in NATURAL_RESOURCES:
        for n, terraforming in enumerate(TERRAFORMING_LEVELS):
            y += row_h
            terraformed = rules.terraformed_resource(natural, terraforming)
            cells = [str(natural), str(terraforming), str(terraformed)]
            for kind in ("economy", "industry", "science"):
                first = infrastructure_cost(kind, expense, 0, terraformed)
                last = infrastructure_cost(kind, expense, purchases - 1,
                                           terraformed)
                cells.append(f"{_money(first)} → {_money(last)}")
            cells.append(_money(warp_gate_cost(expense, terraformed)))

            for i, ((_, x, anchor), value) in enumerate(zip(TABLE_COLUMNS,
                                                            cells)):
                # Column 1 is the terraforming level - the variable the grid
                # colours by, so it carries that colour here too and the table
                # can be read against the panels without a key.
                terraform_column = i == 1
                body.append(_t(x, y - 6, value, 12.5,
                               TERRAFORM_COLOURS[terraforming]
                               if terraform_column else INK,
                               anchor, weight=600 if terraform_column else 400,
                               font=MONO))
            last_of_band = n == len(TERRAFORMING_LEVELS) - 1
            body.append(f'<line x1="0" y1="{y:.1f}" x2="{WIDTH:.0f}" '
                        f'y2="{y:.1f}" '
                        f'stroke="{MUTED if last_of_band else GRID}"/>')
    return body, y + 26


TITLE = "How terraforming changes infrastructure costs"
PERCENT_TITLE = "What terraforming saves, as a percentage"


def figure(expense: int, tier: str, purchases: int = PURCHASES,
           percent: bool = False) -> str:
    """The grid and its legend - no title, axis titles or caption. The default."""
    body, height = grid_parts(expense, tier, purchases, chrome=False,
                              percent=percent)
    return _document(body, height, PERCENT_TITLE if percent else TITLE)


def sheet(expense: int, tier: str, purchases: int = PURCHASES) -> str:
    """The whole thing as one standalone SVG: grid, formula, then the numbers."""
    body, y = grid_parts(expense, tier, purchases)
    formula, y = formula_parts(y)
    table, height = table_parts(expense, purchases, y)
    return _document(body + formula + table, height, TITLE)


# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", default="standard",
                        choices=sorted(EXPENSE_MULTIPLIERS),
                        help="the game's developmentCost setting")
    parser.add_argument("--purchases", type=int, default=PURCHASES,
                        help="how many purchases on the star to price")
    view = parser.add_mutually_exclusive_group()
    view.add_argument("--sheet", action="store_true",
                      help="add the formula and the full table beneath")
    view.add_argument("--percent", action="store_true",
                      help="plot the saving against terraforming "
                           f"{TERRAFORMING_LEVELS[0]} instead of the price")
    args = parser.parse_args()

    expense = EXPENSE_MULTIPLIERS[args.tier]

    if args.sheet:
        svg, name = (sheet(expense, args.tier, args.purchases),
                     "terraform-costs-sheet.svg")
    elif args.percent:
        svg, name = (figure(expense, args.tier, args.purchases, percent=True),
                     "terraform-costs-percent.svg")
    else:
        svg, name = (figure(expense, args.tier, args.purchases),
                     "terraform-costs.svg")
    out = Path(__file__).resolve().parent / name
    out.write_text(svg, encoding="utf-8")
    print(f"wrote {out}")

    print(f"\n{args.tier} development cost, purchase 1 and "
          f"purchase {args.purchases}")
    header = "natural".rjust(8) + "terraf".rjust(8) + "res".rjust(6)
    for _, label, _ in ROWS:
        header += f"{label}".rjust(14)
    print(header)
    for natural in NATURAL_RESOURCES:
        for terraforming in TERRAFORMING_LEVELS:
            terraformed = rules.terraformed_resource(natural, terraforming)
            row = (str(natural).rjust(8) + str(terraforming).rjust(8)
                   + str(terraformed).rjust(6))
            for kind, _, _ in ROWS:
                if kind == "warpGate":
                    cost = warp_gate_cost(expense, terraformed)
                    cell = _money(cost)
                else:
                    first = infrastructure_cost(kind, expense, 0, terraformed)
                    last = infrastructure_cost(kind, expense,
                                               args.purchases - 1, terraformed)
                    cell = f"{_money(first)}-{_money(last)}"
                row += cell.rjust(14)
            print(row)


if __name__ == "__main__":
    main()
