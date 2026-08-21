#!/usr/bin/env python3
"""The player-facing Markdown write-up of the fronts study.

`fronts_report.py` builds the full HTML report with all eleven statistics.
This one answers the same data in three findings, for someone who plays Solaris
and has never read its source. Structure: two headline findings, then one
section per category with one figure each, then the map grid, then the whole
table in an appendix.

Everything is embedded as a data URI so the page is self-contained: charts as
SVG (crisp, and they carry their own dark ground so they read on any page
theme), map plates as PNG rendered through headless Chrome.

Run:  python figures/fronts_md.py --data out/fronts_study.ndjson \
          --out out/fronts.md
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from solarismap import metrics, render  # noqa: E402

import fronts_report as report  # noqa: E402
import fronts_study as study  # noqa: E402

ARMS = report.ARMS
ARM_LABEL = {"A": "A · as the game builds it",
             "B": "B · every player on 2–9 fronts",
             "C": "C · capitals capped at 2–4 neighbours"}

# Literal values for the standalone SVGs. A chart embedded through an <img>
# data URI is its own document and cannot see the page's custom properties, so
# the var() names the HTML report uses have to be substituted out.
LITERALS = {
    "var(--series-1)": "#3a80e0", "var(--series-2)": "#c87d00",
    "var(--series-3)": "#1c9b76", "var(--text-primary)": "#dbe5ef",
    "var(--text-secondary)": "#a9bccf", "var(--text-muted)": "#8fa3b8",
    "var(--grid)": "#161f2b", "var(--axis)": "#2b3a4c",
    "var(--surface-1)": "#0b1017",
}
GROUND = "#0b1017"

CHROME = [
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
]

PLATE = 300              # px per map plate in the grid
STAR_SCALE = 2.1         # plates are small; the in-game scale disappears at 300px


# --------------------------------------------------------------------------
# Embedding
# --------------------------------------------------------------------------


def standalone(markup: str) -> str:
    """Turn a report figure into a self-contained SVG on its own ground."""
    for name, literal in LITERALS.items():
        markup = markup.replace(name, literal)
    # A background rect rather than a CSS fill, so the ground travels with the
    # image into a light-themed page.
    head, rest = markup.split(">", 1)
    box = head.split('viewBox="')[1].split('"')[0].split()
    ground = (f'<rect x="{box[0]}" y="{box[1]}" width="{box[2]}" '
              f'height="{box[3]}" fill="{GROUND}"/>')
    markup = f"{head}>{ground}{rest}"
    return markup.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)


def data_uri_svg(markup: str) -> str:
    raw = standalone(markup).encode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(raw).decode("ascii")


def data_uri_png(path: Path) -> str:
    return ("data:image/png;base64,"
            + base64.b64encode(path.read_bytes()).decode("ascii"))


def chrome() -> str:
    for candidate in CHROME:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("no Chrome or Edge found - needed to rasterise the map plates")


def grid_plate(rows: list[tuple[str, list[dict]]], out_png: Path,
               cell: int = PLATE) -> None:
    """Rasterise the whole 3x5 grid as one image.

    One image rather than fifteen in a Markdown table: a table of five 300px
    plates overflows the page width and there is no way to give it its own
    scroll container from Markdown. Compositing here also puts the row labels
    and the gutters under this module's control rather than the renderer's.
    """
    label_w = 150
    cells = []
    for label, galaxies in rows:
        plates = "".join(
            f'<div class="cell">' + render.draw(galaxy, render.Options(
                resources=False, ships=False, wormhole_links=False,
                star_scale=STAR_SCALE, margin=40.0)) + "</div>"
            for galaxy in galaxies)
        cells.append(f'<div class="row"><div class="lab">{label}</div>{plates}</div>')

    width = label_w + len(rows[0][1]) * (cell + 8)
    height = len(rows) * (cell + 8) + 8
    page_html = (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "html,body{margin:0;background:#05070b;"
        "font-family:ui-monospace,'Cascadia Mono',Menlo,Consolas,monospace}"
        ".row{display:flex;align-items:center;gap:8px;margin-bottom:8px}"
        f".lab{{width:{label_w - 8}px;flex:none;color:#8fa3b8;font-size:13px;"
        "line-height:1.35;padding-left:2px}"
        f".cell{{width:{cell}px;height:{cell}px;flex:none;background:#000;"
        "border-radius:3px;overflow:hidden}"
        ".cell svg{width:100%;height:100%;display:block}"
        "</style></head><body>"
        f'<div style="padding:8px 0 0 0">{"".join(cells)}</div>'
        "</body></html>")

    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "grid.html"
        page.write_text(page_html, encoding="utf-8")
        subprocess.run(
            [chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--window-size={width},{height}", f"--screenshot={out_png}",
             "--virtual-time-budget=20000", page.as_uri()],
            check=True, capture_output=True)


# --------------------------------------------------------------------------
# The selection curve - the lead finding
# --------------------------------------------------------------------------


def fairness_index(rows: list[dict], pool: list[dict]) -> None:
    """Attach a single fairness number to every draw, in place as `_fair`.

    The mean z-score of the six fairness spreads, standardised against every
    draw in the study so the arms sit on one scale, and signed so lower is
    fairer - the same direction the spreads themselves run.

    This composite exists to *rank* maps inside the selection experiment. It is
    not reported as a statistic anywhere, because averaging six things that
    trade against each other hides which one moved.
    """
    moments = {}
    for name in metrics.FAIRNESS:
        values = [r[name] for r in pool if r[name] is not None]
        moments[name] = (statistics.mean(values), statistics.pstdev(values) or 1.0)
    for row in rows:
        z = [(row[name] - moments[name][0]) / moments[name][1]
             for name in metrics.FAIRNESS if row[name] is not None]
        row["_fair"] = sum(z) / len(z) if z else 0.0


def selection_curve(a_values: list[float], sizes=(1, 2, 3, 5, 10, 20),
                    trials: int = 4000, seed: int = 11) -> list[dict]:
    """Median fairness of the best of N draws, and how often it beats one draw."""
    rng = random.Random(seed)
    out = []
    for n in sizes:
        best = [min(rng.sample(a_values, n)) for _ in range(trials)]
        out.append({"n": n, "median": statistics.median(best),
                    "prob": metrics.prob_better(a_values, best, True)})
    return out


def fig_selection(curve: list[dict], reference: float, ref_prob: float) -> str:
    """Best-of-N against the generator change. The report's lead figure."""
    left, right, top, bottom = 64.0, 130.0, 54.0, 46.0
    width, height = 860.0, 330.0
    plot_w = width - left - right
    plot_h = height - top - bottom

    lo = min(min(p["median"] for p in curve), reference) - 0.12
    hi = max(max(p["median"] for p in curve), 0.05) + 0.06

    def y_of(v: float) -> float:
        return top + (hi - v) / (hi - lo) * plot_h

    def x_of(i: int) -> float:
        return left + i * (plot_w / max(len(curve) - 1, 1))

    body = [report.text(0, 16, "Fairness of the best map out of N draws",
                        size=13, fill="var(--text-primary)", weight=600),
            report.text(0, 34, "lower is fairer · index is the mean of the six "
                        "fairness spreads, standardised", size=11,
                        fill="var(--text-muted)")]

    # The generator change, as a level to clear.
    ry = y_of(reference)
    body.append(report.rule(left, ry, left + plot_w, ry,
                            stroke="var(--series-3)", width=2, dash="6 4"))
    body.append(report.text(left + plot_w + 8, ry + 4,
                            "capitals capped", size=11, fill="var(--series-3)"))
    body.append(report.text(left + plot_w + 8, ry + 18,
                            f"P {ref_prob:.2f}", size=10,
                            fill="var(--text-muted)", tabular=True))

    body.append(report.rule(left, y_of(0.0), left + plot_w, y_of(0.0),
                            stroke="var(--axis)"))
    body.append(report.text(left + plot_w + 8, y_of(0.0) + 4, "a single draw",
                            size=11, fill="var(--text-muted)"))

    points = " ".join(f"{x_of(i):.1f},{y_of(p['median']):.1f}"
                      for i, p in enumerate(curve))
    body.append(f'<polyline points="{points}" fill="none" '
                f'stroke="var(--series-2)" stroke-width="2" '
                f'stroke-linejoin="round"/>')
    for i, p in enumerate(curve):
        x, y = x_of(i), y_of(p["median"])
        body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" '
                    f'fill="var(--series-2)" stroke="{GROUND}" stroke-width="2"/>')
        body.append(report.text(x, y - 13, f"P {p['prob']:.2f}", size=10,
                                fill="var(--text-secondary)", anchor="middle",
                                tabular=True))
        body.append(report.text(x, height - bottom + 20, f"{p['n']}", size=12,
                                fill="var(--text-muted)", anchor="middle",
                                tabular=True))
    body.append(report.text(left + plot_w / 2, height - bottom + 38,
                            "maps drawn, keeping the fairest", size=11,
                            fill="var(--text-secondary)", anchor="middle"))
    return report.svg(width, height, "".join(body), "Best of N draws")


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def table(headers: list[str], rows: list[list[str]], align: str = "") -> str:
    align = align or ("l" + "r" * (len(headers) - 1))
    bar = {"l": ":---", "r": "---:", "c": ":---:"}
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(bar[a] for a in align) + " |"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", default=str(ROOT / "out" / "fronts_study.ndjson"))
    parser.add_argument("--out", default=str(ROOT / "out" / "fronts.md"))
    parser.add_argument("--plates", type=int, default=5)
    parser.add_argument("--plate-seed", type=int, default=3)
    args = parser.parse_args()

    arms = report.load(Path(args.data))
    agg = report.aggregate(arms)
    pool = arms["stream"] + arms["C"]
    fairness_index(pool, pool)

    a_fair = [r["_fair"] for r in arms["stream"]]
    c_fair = [r["_fair"] for r in arms["C"]]
    b_fair = [r["_fair"] for r in arms["stream"] if r["in_band"]]
    curve = selection_curve(a_fair)
    ref_prob = metrics.prob_better(a_fair, c_fair, True)

    figures = {
        "selection": data_uri_svg(fig_selection(
            curve, statistics.median(c_fair), ref_prob)),
        "fronts": data_uri_svg(report.fig_distribution(
            {a: agg["arms"][a]["fronts_pool"] for a in ARMS},
            keys=list(range(1, 17)),
            title="How many rivals each player borders",
            x_label="rival players on your border", marks=study.FRONTS_BAND)),
        "compactness": data_uri_svg(report.fig_intervals(
            agg, metrics.COMPACTNESS,
            "Compactness — p10 to p90 across draws, dot is the median")),
        "novelty": data_uri_svg(report.fig_intervals(
            agg, metrics.NOVELTY,
            "Novelty — p10 to p90 across draws, dot is the median")),
    }

    # Five draws from each arm, composited into one grid image.
    rng = random.Random(args.plate_seed)
    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, picked = [], {}
    for arm in ARMS:
        chosen = rng.sample(arms[arm], args.plates)
        picked[arm] = [r["seed"] for r in chosen]
        galaxies = []
        for record in chosen:
            generator = "irregular_n_limit" if arm == "C" else study.GENERATOR
            kwargs = study.N_LIMIT_KWARGS if arm == "C" else {}
            galaxies.append(study.build(record["seed"], generator, **kwargs))
            print(f"  built {arm} {record['seed']}", flush=True)
        rows.append((ARM_LABEL[arm].replace(" · ", "<br>"), galaxies))

    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "grid.png"
        grid_plate(rows, png)
        grid_uri = data_uri_png(png)
    print(f"  grid {len(grid_uri) / 1024:.0f} KB", flush=True)

    Path(args.out).write_text(build(agg, arms, figures, grid_uri, curve,
                                    a_fair, b_fair, c_fair, ref_prob, picked),
                              encoding="utf-8")
    size = Path(args.out).stat().st_size / 1024 / 1024
    print(f"wrote {args.out}  ({size:.1f} MB)")


def build(agg, arms, figures, grid_uri, curve, a_fair, b_fair, c_fair,
          ref_prob, picked) -> str:
    from md import document
    return document(agg, arms, figures, grid_uri, curve,
                    a_fair, b_fair, c_fair, ref_prob, picked)


if __name__ == "__main__":
    main()
