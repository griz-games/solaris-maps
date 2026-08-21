#!/usr/bin/env python3
"""Aggregate `fronts_study.py`'s draws and build the report.

Reads the NDJSON one record per draw, splits it into the three arms, reduces
each statistic with `metrics.summarise`, and writes a self-contained HTML page.

Figures are inline SVG written against CSS custom properties (`var(--series-1)`),
so the page's own light/dark tokens drive them and no chart carries a hardcoded
colour. Palette and mark specs follow the `dataviz` skill: thin marks, 4px
rounded data-ends, 2px gaps between adjacent fills, recessive grid, a legend for
every multi-series figure and direct labels throughout - the last of which is
also the documented relief for the aqua slot's light-mode contrast warning.

Run:  python figures/fronts_report.py --data out/fronts_study.ndjson \
          --out out/fronts_report.html
"""

from __future__ import annotations

import argparse
import html
import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from solarismap import metrics, render  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fronts_study as study  # noqa: E402
from page import build_page  # noqa: E402  (kept apart: prose, not analysis)

ARMS = ("A", "B", "C")
ARM_LABEL = {
    "A": "A — status quo",
    "B": "B — fronts 2–9",
    "C": "C — n-limit 2–4",
}
ARM_SERIES = {"A": "1", "B": "2", "C": "3"}
TARGET = 1000

# Statistic groups, in the order the report reads them.
GROUPS = (("Fairness — spread across players, 0 = identical, lower is fairer",
           metrics.FAIRNESS),
          ("Compactness — a description, not a score", metrics.COMPACTNESS),
          ("Novelty — higher is more varied", metrics.NOVELTY))


# --------------------------------------------------------------------------
# Load and split
# --------------------------------------------------------------------------


def load(path: Path) -> dict[str, list[dict]]:
    """Split the stream into the three arms.

    A is the first `TARGET` draws of the irregular stream, B the first `TARGET`
    of that same stream clearing the band, C the n-limit draws. A and B overlap
    by construction - B is a subset of the population A is sampled from, which
    is the point: every difference between them is the selection.
    """
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    stream = [r for r in rows if r["arm"] == "AB"]
    stream.sort(key=lambda r: int(r["seed"].split("-")[1]))
    arm_c = [r for r in rows if r["arm"] == "C"]
    arm_c.sort(key=lambda r: int(r["seed"].split("-")[1]))
    return {
        "A": stream[:TARGET],
        "B": [r for r in stream if r["in_band"]][:TARGET],
        "C": arm_c[:TARGET],
        "stream": stream,
    }


def aggregate(arms: dict[str, list[dict]]) -> dict:
    out: dict = {"arms": {}}
    for arm in ARMS:
        rows = arms[arm]
        entry: dict = {"n": len(rows), "stats": {}, "pooled": {}}
        for name in metrics.ALL:
            entry["stats"][name] = metrics.summarise([r[name] for r in rows])
        for name in metrics.FAIRNESS:
            pooled = [v for r in rows for v in r[f"raw_{name}"] if v is not None]
            entry["pooled"][name] = {
                "worst": min(pooled) if pooled else None,
                "typical": statistics.median(pooled) if pooled else None,
                "best": max(pooled) if pooled else None,
                "mean": statistics.mean(pooled) if pooled else None,
            }
        entry["diversity"] = metrics.between_seed_diversity(
            [r["descriptor"] for r in rows])
        entry["connect"] = Counter(
            "never" if r["connect_level"] is None else str(r["connect_level"])
            for r in rows)
        entry["connected_at_start"] = sum(r["connected_at_start"] for r in rows)
        entry["invalid"] = sum(1 for r in rows if r["validation_errors"])
        entry["marooned"] = sum(r["marooned"] for r in rows)
        entry["fronts_pool"] = Counter(v for r in rows for v in r["raw_fronts"])
        entry["capdeg_pool"] = Counter(v for r in rows for v in r["capital_degree"])
        out["arms"][arm] = entry

    stream = arms["stream"]
    out["acceptance"] = {
        "n": len(stream),
        "accepted": sum(r["in_band"] for r in stream),
        "rate": sum(r["in_band"] for r in stream) / len(stream) if stream else 0.0,
    }
    out["c_acceptance"] = {
        "n": len(arms["C"]),
        "accepted": sum(r["in_band"] for r in arms["C"]),
        "rate": (sum(r["in_band"] for r in arms["C"]) / len(arms["C"])
                 if arms["C"] else 0.0),
    }

    # Effect sizes against A. Compactness is deliberately absent from
    # LOWER_IS_BETTER and is not ranked - it has no better direction.
    out["prob"] = {}
    for arm in ("B", "C"):
        out["prob"][arm] = {}
        for name in metrics.FAIRNESS + metrics.NOVELTY:
            out["prob"][arm][name] = metrics.prob_better(
                [r[name] for r in arms["A"]], [r[name] for r in arms[arm]],
                lower_is_better=metrics.LOWER_IS_BETTER[name])
    return out


# --------------------------------------------------------------------------
# SVG primitives
# --------------------------------------------------------------------------


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def fmt(value, places: int = 2) -> str:
    if value is None:
        return "–"
    if isinstance(value, float) and (math.isinf(value) or math.isnan(value)):
        return "–"
    if places == 0:
        return f"{value:,.0f}"
    return f"{value:.{places}f}"


def svg(width: float, height: float, body: str, title: str) -> str:
    return (f'<svg viewBox="0 0 {width:.0f} {height:.0f}" width="100%" '
            f'role="img" aria-label="{esc(title)}" '
            f'style="max-width:{width:.0f}px;height:auto;display:block">'
            f'{body}</svg>')


def text(x: float, y: float, content, *, size: float = 12,
         fill: str = "var(--text-secondary)", anchor: str = "start",
         weight: int = 400, tabular: bool = False) -> str:
    extra = ';font-variant-numeric:tabular-nums' if tabular else ''
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:.0f}" '
            f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}" '
            f'style="font-family:system-ui,-apple-system,\'Segoe UI\',sans-serif'
            f'{extra}">{esc(content)}</text>')


def rule(x1: float, y1: float, x2: float, y2: float, *,
         stroke: str = "var(--grid)", width: float = 1,
         dash: str | None = None) -> str:
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{stroke}" stroke-width="{width}"{d}/>')


def vbar(x: float, y: float, w: float, h: float, fill: str) -> str:
    """A column with 4px rounded data-end, anchored to the baseline.

    Drawn as a path so only the top corners round; a rounded rect would round
    the baseline end too and lift the mark off its axis.
    """
    if h <= 0:
        return ""
    r = min(4.0, w / 2.0, h)
    return (f'<path d="M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} '
            f'Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} L{x + w - r:.1f},{y:.1f} '
            f'Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} '
            f'L{x + w:.1f},{y + h:.1f} Z" fill="{fill}"/>')


def legend(x: float, y: float, entries: list[tuple[str, str]]) -> str:
    """Swatch + label row. Identity is never colour alone."""
    out, cursor = [], x
    for colour, label in entries:
        out.append(f'<rect x="{cursor:.1f}" y="{y - 8:.1f}" width="10" height="10" '
                   f'rx="2" fill="{colour}"/>')
        out.append(text(cursor + 15, y, label, size=12))
        cursor += 15 + len(label) * 6.6 + 22
    return "".join(out)


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------


def fig_distribution(pools: dict[str, Counter], *, keys: list,
                     title: str, x_label: str,
                     marks: tuple[int, int] | None = None,
                     key_label=str) -> str:
    """Small multiples: one panel per arm, shared x, single series each.

    Small multiples rather than grouped bars because the comparison is between
    whole shapes, and forty-odd interleaved columns hide the shape they are
    supposed to show. Shared axis carries the comparison instead.
    """
    left, right, top = 116.0, 20.0, 26.0
    panel_h, gap = 104.0, 34.0
    width = 860.0
    plot_w = width - left - right
    height = top + len(ARMS) * (panel_h + gap)

    peak = max((c.get(k, 0) / max(sum(c.values()), 1) for c in pools.values()
                for k in keys), default=0.01)
    slot = plot_w / len(keys)
    # 2px surface gap each side, and a ceiling so a six-category panel does not
    # turn into six slabs - a wide bar reads as an area, not a count.
    bar_w = max(4.0, min(slot - 4.0, 46.0))

    body = [text(0, 14, title, size=13, fill="var(--text-primary)", weight=600)]
    for row, arm in enumerate(ARMS):
        counter = pools[arm]
        total = max(sum(counter.values()), 1)
        base = top + row * (panel_h + gap) + panel_h
        colour = f"var(--series-{ARM_SERIES[arm]})"

        body.append(text(0, base - panel_h + 12, ARM_LABEL[arm], size=12,
                         fill="var(--text-primary)", weight=600))
        body.append(text(0, base - panel_h + 28, f"{total:,} seats", size=11,
                         fill="var(--text-muted)"))
        body.append(rule(left, base, left + plot_w, base, stroke="var(--axis)"))

        if marks:
            for edge in marks:
                if edge in keys:
                    mx = left + keys.index(edge) * slot + slot / 2
                    body.append(rule(mx, base - panel_h + 4, mx, base,
                                     stroke="var(--text-muted)", dash="3 3"))

        for i, key in enumerate(keys):
            share = counter.get(key, 0) / total
            h = (share / peak) * (panel_h - 22) if peak else 0
            x = left + i * slot + (slot - bar_w) / 2
            body.append(vbar(x, base - h, bar_w, h, colour))
            if share >= 0.08:
                body.append(text(x + bar_w / 2, base - h - 5,
                                 f"{share * 100:.0f}%", size=10,
                                 fill="var(--text-secondary)", anchor="middle",
                                 tabular=True))
        if row == len(ARMS) - 1:
            for i, key in enumerate(keys):
                body.append(text(left + i * slot + slot / 2, base + 16,
                                 key_label(key), size=11,
                                 fill="var(--text-muted)", anchor="middle",
                                 tabular=True))
            body.append(text(left + plot_w / 2, base + 34, x_label, size=11,
                             fill="var(--text-secondary)", anchor="middle"))
    return svg(width, height + 26, "".join(body), title)


def fig_intervals(agg: dict, names: tuple[str, ...], title: str) -> str:
    """p10–p90 interval per arm per statistic, with a median tick.

    A percentile interval of the draws, not a confidence interval: the question
    is how much the map you are about to generate varies, and that spread does
    not shrink with more draws.
    """
    left, right, top = 190.0, 76.0, 58.0
    row_h, group_gap = 20.0, 22.0
    width = 860.0
    plot_w = width - left - right
    height = top + len(names) * (len(ARMS) * row_h + group_gap)

    # Legend on its own line: these titles are long enough to run under it.
    body = [text(0, 14, title, size=13, fill="var(--text-primary)", weight=600),
            legend(0, 38, [(f"var(--series-{ARM_SERIES[a]})", ARM_LABEL[a])
                           for a in ARMS])]

    for n, name in enumerate(names):
        block = top + n * (len(ARMS) * row_h + group_gap)
        cells = [agg["arms"][a]["stats"][name] for a in ARMS]
        cells = [c for c in cells if c]
        if not cells:
            continue
        lo = min(c["p10"] for c in cells)
        hi = max(c["p90"] for c in cells)
        if hi <= lo:
            hi = lo + 1e-9
        pad = (hi - lo) * 0.08
        lo, hi = lo - pad, hi + pad

        body.append(text(0, block + 12, metrics.LABELS[name], size=12,
                         fill="var(--text-primary)", weight=600))
        for row, arm in enumerate(ARMS):
            cell = agg["arms"][arm]["stats"][name]
            y = block + row * row_h + 20
            if not cell:
                continue
            colour = f"var(--series-{ARM_SERIES[arm]})"
            x1 = left + (cell["p10"] - lo) / (hi - lo) * plot_w
            x2 = left + (cell["p90"] - lo) / (hi - lo) * plot_w
            xm = left + (cell["median"] - lo) / (hi - lo) * plot_w
            body.append(f'<rect x="{x1:.1f}" y="{y - 4:.1f}" '
                        f'width="{max(x2 - x1, 2):.1f}" height="8" rx="4" '
                        f'fill="{colour}" opacity="0.34"/>')
            body.append(f'<circle cx="{xm:.1f}" cy="{y:.1f}" r="4.5" '
                        f'fill="{colour}" stroke="var(--surface-1)" '
                        f'stroke-width="2"/>')
            places = 0 if abs(cell["median"]) >= 100 else 2
            body.append(text(width - right + 8, y + 4, fmt(cell["median"], places),
                             size=11, fill="var(--text-secondary)", tabular=True))
        body.append(text(left, block + len(ARMS) * row_h + 14,
                         f"{fmt(lo, 2)} — {fmt(hi, 2)}", size=10,
                         fill="var(--text-muted)"))
    return svg(width, height + 10, "".join(body), title)


def fig_prob(agg: dict) -> str:
    """P(a random arm-B / arm-C map beats a random arm-A map) per statistic."""
    left, right, top = 190.0, 84.0, 58.0
    row_h = 26.0
    width = 860.0
    plot_w = width - left - right
    names = metrics.FAIRNESS + metrics.NOVELTY
    height = top + len(names) * row_h + 34
    # Domain runs to 1.0 so nothing clamps: three of these land above 0.80, and
    # pinning them to the axis edge both misreports them and collides with the
    # value labels.
    domain = (0.2, 1.0)

    body = [text(0, 14, "Effect size against arm A", size=13,
                 fill="var(--text-primary)", weight=600),
            legend(0, 38, [("var(--series-2)", "B vs A"),
                           ("var(--series-3)", "C vs A")])]

    def x_of(p: float) -> float:
        return left + (p - domain[0]) / (domain[1] - domain[0]) * plot_w

    for tick in (0.2, 0.4, 0.5, 0.6, 0.8, 1.0):
        x = x_of(tick)
        body.append(rule(x, top - 6, x, top + len(names) * row_h,
                         stroke="var(--axis)" if tick == 0.5 else "var(--grid)",
                         dash=None if tick == 0.5 else "2 4"))
        body.append(text(x, top + len(names) * row_h + 16, f"{tick:.2f}",
                         size=10, fill="var(--text-muted)", anchor="middle",
                         tabular=True))
    body.append(text(left + plot_w / 2, top + len(names) * row_h + 32,
                     "0.50 = indistinguishable on a single draw",
                     size=11, fill="var(--text-secondary)", anchor="middle"))

    for n, name in enumerate(names):
        y = top + n * row_h + 12
        body.append(text(0, y + 4, metrics.LABELS[name], size=12,
                         fill="var(--text-primary)"))
        for arm, dy in (("B", -4.5), ("C", 4.5)):
            p = agg["prob"][arm][name]
            if p is None:
                continue
            colour = f"var(--series-{ARM_SERIES[arm]})"
            body.append(f'<circle cx="{x_of(min(max(p, domain[0]), domain[1])):.1f}" '
                        f'cy="{y + dy:.1f}" r="5" fill="{colour}" '
                        f'stroke="var(--surface-1)" stroke-width="2"/>')
        pb, pc = agg["prob"]["B"][name], agg["prob"]["C"][name]
        body.append(text(width - right + 6, y + 4,
                         f"{fmt(pb)} / {fmt(pc)}", size=10,
                         fill="var(--text-secondary)", tabular=True))
    return svg(width, height + 10, "".join(body), "Effect size against arm A")


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


def table_stats(agg: dict) -> str:
    rows = ['<table><thead><tr><th>statistic</th>'
            + "".join(f'<th colspan="2">{esc(ARM_LABEL[a])}</th>' for a in ARMS)
            + '</tr><tr><th></th>'
            + "".join('<th>median</th><th>p10–p90 · CV</th>' for _ in ARMS)
            + '</tr></thead><tbody>']
    for heading, names in GROUPS:
        rows.append(f'<tr class="group"><td colspan="7">{esc(heading)}</td></tr>')
        for name in names:
            cells = [f'<th scope="row">{esc(metrics.LABELS[name])}</th>']
            for arm in ARMS:
                cell = agg["arms"][arm]["stats"][name]
                if not cell:
                    cells.append('<td>–</td><td>–</td>')
                    continue
                places = 0 if abs(cell["median"]) >= 100 else 2
                cells.append(
                    f'<td class="num">{fmt(cell["median"], places)}</td>'
                    f'<td class="num muted">{fmt(cell["p10"], places)}–'
                    f'{fmt(cell["p90"], places)} · {cell["cv"] * 100:.0f}%</td>')
            rows.append("<tr>" + "".join(cells) + "</tr>")
    rows.append('<tr class="group"><td colspan="7">Set-level</td></tr>')
    cells = ['<th scope="row">between-seed diversity</th>']
    for arm in ARMS:
        cells.append(f'<td class="num">{fmt(agg["arms"][arm]["diversity"])}</td>'
                     f'<td class="num muted">one value per set</td>')
    rows.append("<tr>" + "".join(cells) + "</tr>")
    rows.append("</tbody></table>")
    return "".join(rows)


def table_pooled(agg: dict) -> str:
    """Worst / typical / best player, in real units, pooled over every draw."""
    rows = ['<table><thead><tr><th>fairness statistic</th><th>unit</th>'
            + "".join(f'<th colspan="3">{esc(ARM_LABEL[a])}</th>' for a in ARMS)
            + '</tr><tr><th></th><th></th>'
            + "".join('<th>worst</th><th>typical</th><th>best</th>' for _ in ARMS)
            + '</tr></thead><tbody>']
    for name in metrics.FAIRNESS:
        cells = [f'<th scope="row">{esc(metrics.LABELS[name])}</th>'
                 f'<td class="muted">{esc(metrics.UNITS.get(name, ""))}</td>']
        for arm in ARMS:
            pooled = agg["arms"][arm]["pooled"][name]
            places = 0 if (pooled["typical"] or 0) >= 100 else 1
            cells.append(
                f'<td class="num">{fmt(pooled["worst"], places)}</td>'
                f'<td class="num">{fmt(pooled["typical"], places)}</td>'
                f'<td class="num">{fmt(pooled["best"], places)}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    rows.append("</tbody></table>")
    return "".join(rows)


def table_connect(agg: dict) -> str:
    keys = ["2", "3", "4", "5", "6", "7", "8", "never"]
    rows = ['<table><thead><tr><th>hyperspace level at which the galaxy is one piece'
            '</th>' + "".join(f'<th>{esc(k)}</th>' for k in keys)
            + '</tr></thead><tbody>']
    for arm in ARMS:
        counter = agg["arms"][arm]["connect"]
        total = max(sum(counter.values()), 1)
        cells = [f'<th scope="row">{esc(ARM_LABEL[arm])}</th>']
        for k in keys:
            share = counter.get(k, 0) / total
            cells.append(f'<td class="num">{share * 100:.1f}%</td>'
                         if share else '<td class="num muted">–</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    rows.append("</tbody></table>")
    return "".join(rows)


# --------------------------------------------------------------------------
# Example maps
# --------------------------------------------------------------------------


def draw_examples(arms: dict[str, list[dict]], count: int, seed: int) -> list[dict]:
    """Render `count` random arm-A draws, plus whether each cleared the band."""
    rng = random.Random(seed)
    picks = rng.sample(arms["A"], count)
    options = render.Options(resources=False, ships=False)
    out = []
    for record in picks:
        galaxy = study.build(record["seed"])
        out.append({
            "seed": record["seed"],
            "svg": render.draw(galaxy, options),
            "fronts": (record["fronts_min"], record["fronts_max"]),
            "in_band": record["in_band"],
            "connect": record["connect_level"],
            "spread": record["fronts"],
            "chokepoints": record["chokepoints_per_star"],
            "roundness": record["roundness"],
        })
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default=str(ROOT / "out" / "fronts_study.ndjson"))
    parser.add_argument("--out", default=str(ROOT / "out" / "fronts_report.html"))
    parser.add_argument("--examples", type=int, default=5)
    parser.add_argument("--example-seed", type=int, default=7)
    args = parser.parse_args()

    arms = load(Path(args.data))
    agg = aggregate(arms)
    print(f"A {len(arms['A'])}  B {len(arms['B'])}  C {len(arms['C'])}  "
          f"stream {len(arms['stream'])}  "
          f"acceptance {agg['acceptance']['rate'] * 100:.1f}%")

    figures = {
        "fronts": fig_distribution(
            {a: agg["arms"][a]["fronts_pool"] for a in ARMS},
            keys=list(range(1, 17)),
            title="Fronts per player — rivals whose territory touches yours",
            x_label="fronts (rival players)", marks=study.FRONTS_BAND),
        "capdeg": fig_distribution(
            {a: agg["arms"][a]["capdeg_pool"] for a in ARMS},
            keys=list(range(1, 7)),
            title="Capital lattice degree — adjacent rival capitals",
            x_label="adjacent capitals"),
        "fairness": fig_intervals(agg, metrics.FAIRNESS,
                                  "Fairness spreads — p10 to p90 across draws, "
                                  "dot is the median"),
        "other": fig_intervals(agg, metrics.COMPACTNESS + metrics.NOVELTY,
                               "Compactness and novelty — p10 to p90 across draws"),
        "prob": fig_prob(agg),
        "table_stats": table_stats(agg),
        "table_pooled": table_pooled(agg),
        "table_connect": table_connect(agg),
    }
    examples = draw_examples(arms, args.examples, args.example_seed)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_page(agg, figures, examples), encoding="utf-8")
    print(f"wrote {out_path}  ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")

    side = out_path.with_suffix(".aggregates.json")
    side.write_text(json.dumps(
        {k: v for k, v in agg.items() if k != "arms"}
        | {"arms": {a: {kk: vv for kk, vv in agg["arms"][a].items()
                        if kk not in ("fronts_pool", "capdeg_pool", "connect")}
                    for a in ARMS}}, indent=2, default=str), encoding="utf-8")
    print(f"wrote {side}")


if __name__ == "__main__":
    main()
