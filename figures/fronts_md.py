#!/usr/bin/env python3
"""The player-facing Markdown write-up of the fronts study.

`fronts_report.py` builds the full HTML report with all eleven statistics.
This one answers the same data in three findings, for someone who plays Solaris
and has never read its source: three findings, one section per category with a
figure each, the map grid, then the full table in an appendix.

Figures come from `study_figs`, which draws in the repository's study house
style - dot-and-range charts and flat vector galaxies on a light ground. They
are written beside the write-up as ordinary SVG files and linked relatively, so
the Markdown stays readable in a diff and GitHub renders it directly. That is
also why `study_figs` writes literal colours and paints its own background: each
figure is its own document.

Statistics are reported as the median and interquartile range across draws, in
their own units. There are no win probabilities: the question a player has is
where the map they are about to get will land, and a percentage cannot say.

Run:  python figures/fronts_md.py --data out/fronts_study.ndjson --out FRONTS.md
"""

from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from solarismap import metrics  # noqa: E402

import fronts_report as report  # noqa: E402
import fronts_study as study  # noqa: E402
import study_figs as sfig  # noqa: E402
from md import label as row_label  # noqa: E402

ARMS = report.ARMS
ARM_LABEL = {"A": "A · as the game builds it",
             "B": "B · picked for fewest fronts",
             "C": "C · capitals capped at 2–4 neighbours"}


FIGURE_DIR = ROOT / "figures"
FIGURE_PREFIX = "fronts-"


def write_figure(name: str, markup: str, out_md: Path) -> str:
    """Write one figure beside the others and return a path relative to the
    write-up, so the link resolves both on GitHub and on disk."""
    path = FIGURE_DIR / f"{FIGURE_PREFIX}{name}.svg"
    path.write_text(markup, encoding="utf-8")
    rel = os.path.relpath(path, out_md.parent).replace("\\", "/")
    print(f"  wrote {path.name}  ({path.stat().st_size / 1024:.0f} KB)", flush=True)
    return rel


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
    """Where the fairness index lands if you draw N maps and keep the fairest.

    Reported as the distribution of that outcome - median and interquartile
    range over `trials` repetitions - rather than as a win probability, so the
    reader sees the value they would actually get and in the index's own units.
    """
    rng = random.Random(seed)
    out = []
    for n in sizes:
        best = [min(rng.sample(a_values, n)) for _ in range(trials)]
        out.append({"n": n, "summary": metrics.summarise(best)})
    return out


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
    parser.add_argument("--out", default=str(ROOT / "FRONTS.md"))
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

    labels = {a: ARM_LABEL[a].split(" · ")[1] for a in ARMS}
    cells = {a: agg["arms"][a]["stats"] for a in ARMS}
    marks = "Dot = median across 1,000 maps, bar = interquartile range."

    # Selection curve: rows are how many maps were drawn, one series.
    curve_cells = {"sel": {f"best of {p['n']}": p["summary"] for p in curve}}
    curve_names = [f"best of {p['n']}" for p in curve]

    # The level of fronts, as opposed to their spread: pooled per-player values.
    front_levels = {a: {"fronts, per player": metrics.summarise(
        [v for r in arms[a] for v in r["raw_fronts"]])} for a in ARMS}

    out_md = Path(args.out)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    def W(name: str, markup: str) -> str:
        return write_figure(name, markup, out_md)

    figures = {
        "selection": W("selection", sfig.dot_range(
            ["sel"], {"sel": "drawn from the ordinary generator"}, curve_cells,
            curve_names,
            "Fairness of the best map, by how many maps you draw",
            marks + "  Lower is fairer. The dashed level is the generator change.",
            shared=True, reference=statistics.median(c_fair))),
        "fairness": W("fairness", sfig.dot_range(
            ARMS, labels, cells, metrics.FAIRNESS,
            "Fairness — spread across players within a map "
            "(0 = identical, lower is fairer)",
            marks + "  Shared scale.", shared=True, row_label=row_label)),
        "fronts": W("fronts", sfig.dot_range(
            ARMS, labels, front_levels, ["fronts, per player"],
            "Fronts — how many rivals each player borders",
            marks + "  Pooled over every player of every map, in rivals.",
            shared=True)),
        "compactness": W("compactness", sfig.dot_range(
            ARMS, labels, cells, metrics.COMPACTNESS,
            "Compactness — a description, not a score",
            marks + "  Each row on its own scale; the two share no unit.",
            shared=False, row_label=row_label)),
        "novelty": W("novelty", sfig.dot_range(
            ARMS, labels, cells, metrics.NOVELTY,
            "Novelty — higher is more varied",
            marks + "  Each row on its own scale.", shared=False, row_label=row_label)),
    }

    # Five draws from each arm, as one flat-vector grid.
    rng = random.Random(args.plate_seed)
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
        head, tail = ARM_LABEL[arm].split(" · ")
        rows.append((f"{head}\n{tail}", galaxies))

    grid_uri = W("maps", sfig.map_grid(
        rows, "Five draws from each condition",
        "Drawn at random from the 1,000 maps in each row. Same scale "
        "throughout; ordinary stars in grey."))

    out_md.write_text(build(agg, arms, figures, grid_uri, curve,
                                    a_fair, b_fair, c_fair, picked),
                              encoding="utf-8")
    print(f"wrote {out_md}  ({out_md.stat().st_size / 1024:.0f} KB)")


def build(agg, arms, figures, grid_uri, curve, a_fair, b_fair, c_fair,
          picked) -> str:
    from md import document
    return document(agg, arms, figures, grid_uri, curve,
                    a_fair, b_fair, c_fair, picked)


if __name__ == "__main__":
    main()
