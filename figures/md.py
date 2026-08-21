#!/usr/bin/env python3
"""Prose for the Markdown write-up. Every number is passed in, none computed.

Written for someone who plays Solaris and has never opened its source, so the
body names things the way the game does - jumps, territory, borders - and keeps
file names and function names out of it. The appendix carries the method.

Values are medians and interquartile ranges across the 1,000 maps in each arm.
No win probabilities: what a player wants to know is where the map they are
about to get will land, and in what units.
"""

from __future__ import annotations

import re
import statistics

from solarismap import metrics

import fronts_study as study

ARMS = ("A", "B", "C")
NAME = {"A": "as the game builds it",
        "B": "picked for fewest fronts",
        "C": "capitals capped at 2–4 neighbours"}

PLAYER_LABEL = {
    "contested_resources": "contested resources",
    "fronts": "fronts (rivals on your border)",
    "situation_divergence": "how different the seats are",
}


def label(name: str) -> str:
    return PLAYER_LABEL.get(name, metrics.LABELS[name])


def places_for(value: float) -> int:
    if abs(value) >= 10:
        return 0
    return 2 if abs(value) >= 0.1 else 3


def unwrap(text: str) -> str:
    """Put every paragraph and list item back on one line.

    The prose below is written as a wrapped f-string, which is readable in the
    source but leaves the generated Markdown broken at whatever column the
    interpolated numbers happened to push it to. Markdown joins those lines when
    it renders, so this changes nothing on screen - it just stops the file
    itself reading like it was cut with scissors, and keeps diffs to the
    sentence that actually changed.

    Tables, headings, rules and fenced code are passed through untouched.
    """
    out: list[str] = []
    block: list[str] = []
    fenced = False

    def flush() -> None:
        if block:
            out.append(" ".join(line.strip() for line in block))
            block.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            flush()
            fenced = not fenced
            out.append(line)
            continue
        if fenced:
            out.append(line)
            continue
        if not stripped:
            flush()
            out.append("")
            continue
        # Headings, table rows, block quotes and horizontal rules stand alone.
        if (stripped.startswith(("#", "|", ">"))
                or (len(stripped) >= 3 and set(stripped) <= set("-*_ "))):
            flush()
            out.append(line)
            continue
        # A bullet or numbered item starts a fresh block; anything after it is a
        # continuation of that same item and folds into it.
        if stripped.startswith(("- ", "* ", "+ ")) or re.match(r"\d+\. ", stripped):
            flush()
        block.append(line)

    flush()
    return "\n".join(out)


def table(headers, rows, align=None) -> str:
    align = align or ["l"] + ["r"] * (len(headers) - 1)
    bar = {"l": ":---", "r": "---:", "c": ":---:"}
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join(bar[a] for a in align) + " |"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def document(agg, arms, figures, grid_uri, curve, a_fair, b_fair, c_fair,
             picked) -> str:
    a, b, c = (agg["arms"][x] for x in ARMS)
    acc = agg["acceptance"]
    lo, hi = study.FRONTS_BAND
    stream = arms["stream"]

    def cell(arm, name):
        return agg["arms"][arm]["stats"][name]

    def mr(arm, name) -> str:
        """median [q1–q3], the form every number in this report takes."""
        s = cell(arm, name)
        if not s:
            return "–"
        d = places_for(s["median"])
        return f"{s['median']:.{d}f} [{s['q1']:.{d}f}–{s['q3']:.{d}f}]"

    def med(arm, name, places=None):
        s = cell(arm, name)
        d = places_for(s["median"]) if places is None else places
        return f"{s['median']:.{d}f}"

    def quart(values, q):
        values = sorted(values)
        i = (len(values) - 1) * q
        import math
        f, cl = math.floor(i), math.ceil(i)
        return values[f] if f == cl else values[f] + (values[cl] - values[f]) * (i - f)

    def fair(values) -> str:
        # " to " rather than an en dash: these values are signed, and
        # "-0.66--0.17" is unreadable.
        return (f"{statistics.median(values):+.3f} "
                f"[{quart(values, .25):+.3f} to {quart(values, .75):+.3f}]")

    def seats(arm):
        pool = [v for r in arms[arm] for v in r["raw_fronts"]]
        return pool

    seat_share = {arm: 100 * sum(1 for v in seats(arm) if lo <= v <= hi)
                  / len(seats(arm)) for arm in ARMS}
    seat_med = {arm: statistics.median(seats(arm)) for arm in ARMS}
    best_out = min(r["out_of_band"] for r in stream)
    close_share = sum(1 for r in stream if r["out_of_band"] <= 5)

    step = {p["n"]: p["summary"] for p in curve}
    def curve_row(n):
        s = step[n]
        return f"{s['median']:+.3f} [{s['q1']:+.3f} to {s['q3']:+.3f}]"

    a_connect = sum(a["connect"].values())
    never = 100 * a["connect"].get("never", 0) / a_connect
    split = 100 * (a_connect - a["connected_at_start"]) / a_connect

    appendix_rows = []
    for heading, names in (("Fairness — spread across players", metrics.FAIRNESS),
                           ("Compactness — no better direction", metrics.COMPACTNESS),
                           ("Novelty — higher is more varied", metrics.NOVELTY)):
        appendix_rows.append([f"**{heading}**", "", "", ""])
        for name in names:
            appendix_rows.append([label(name), mr("A", name), mr("B", name),
                                  mr("C", name)])

    pooled_rows = []
    for name in metrics.FAIRNESS:
        row = [label(name), metrics.UNITS.get(name, "")]
        for arm in ARMS:
            pool = agg["arms"][arm]["pooled"][name]
            d = 0 if (pool["typical"] or 0) >= 100 else 1
            row.append(f"{pool['worst']:.{d}f} / {pool['typical']:.{d}f} "
                       f"/ {pool['best']:.{d}f}")
        pooled_rows.append(row)

    return unwrap(f"""# Fronts and Fairness

**How fair is a 32-player Solaris galaxy, and what actually makes it fairer?**

I generated {acc['n']:,} thirty-two-player irregular galaxies using the game's own
32-player settings, measured each one, and compared three ways of getting a
better map. Every number below is a **median across 1,000 maps, with the middle
half of them in brackets** — the range you would actually land in, not an average
that hides the spread.

---

## Finding 1 · Two maps beat a better generator

Every galaxy is a roll of the dice. Some seat you with a single neighbour and a
quiet corner; some drop you in the middle of a dozen rivals. You can attack that
by improving the generator, or by generating a few galaxies and keeping the
fairest one.

![Fairness of the best map, by how many maps you draw]({figures['selection']})

The index combines all six fairness measures into one number; lower is fairer,
and 0 is a typical unfiltered map.

{table(["how you pick the map", "fairness index [middle half]"],
       [["take the first one you get", curve_row(1)],
        ["**redesign the generator** (arm C)", f"**{fair(c_fair)}**"],
        ["draw 2, keep the fairer", curve_row(2)],
        ["draw 3, keep the fairest", curve_row(3)],
        ["draw 5, keep the fairest", curve_row(5)],
        ["draw 20, keep the fairest", curve_row(20)]],
       ["l", "r"])}

Drawing **two** maps and keeping the fairer already beats the generator redesign.
Drawing twenty gets you five times as far. Generating a galaxy takes about a
second, so this is the cheapest lever available by a wide margin.

Worth knowing: **the game does not do this for you.** A galaxy is generated once
when the game is created and used as-is. Nothing checks whether it is fair,
whether every player can reach everyone else, or even whether the galaxy is in
one piece — {never:.1f}% of the galaxies I generated never join up into a single
connected map no matter how much hyperspace anyone researches.

---

## Finding 2 · Not every player can be put on {lo}–{hi} fronts

A **front** is a rival whose territory touches yours — how many directions you
can be attacked from. Asking that every player get between {lo} and {hi} of them
is a reasonable-sounding request, and it is very nearly satisfiable.

Very nearly, but not quite. **Of {acc['n']:,} galaxies, none put all 32 players
inside {lo}–{hi} fronts.** The closest came within {best_out} players of it, and
{close_share} maps in {acc['n']:,} got within five. Arm B below is the 1,000 that
came closest.

![Fronts — how many rivals each player borders]({figures['fronts']})

{table(["", "typical player", f"seats inside {lo}–{hi}"],
       [[f"**A** · {NAME['A']}", f"{seat_med['A']:.0f} fronts",
         f"{seat_share['A']:.0f}%"],
        [f"**B** · {NAME['B']}", f"{seat_med['B']:.0f} fronts",
         f"{seat_share['B']:.0f}%"],
        [f"**C** · {NAME['C']}", f"{seat_med['C']:.0f} fronts",
         f"{seat_share['C']:.0f}%"]],
       ["l", "r", "r"])}

Note what arm C does here without any selection at all: capping capital
neighbours puts {seat_share['C']:.0f}% of seats inside the target band, against
{seat_share['A']:.0f}% in an ordinary galaxy and {seat_share['B']:.0f}% even
after picking the best 1,000 maps out of {acc['n']:,}.

---

## Finding 3 · Picking for fewer fronts does not make a map fairer

This is the part that surprised me. Selecting maps for low front counts changes
the **level** — the typical player goes from {seat_med['A']:.0f} borders to
{seat_med['B']:.0f} — but it barely touches the **inequality**. Arm B's fronts
spread is {med('B', 'fronts')} against arm A's {med('A', 'fronts')}: a shift of
{abs(cell('B', 'fronts')['median'] - cell('A', 'fronts')['median']):.2f} against a
middle half that is {cell('A', 'fronts')['q3'] - cell('A', 'fronts')['q1']:.2f}
wide. Contested ground moves no further ({med('B', 'contested_resources')} against
{med('A', 'contested_resources')}). The seats stay about as unequal as they were;
they are all simply a little smaller.

Changing the generator does both. Arm C is fairer on fronts
({med('C', 'fronts')} against {med('A', 'fronts')}) and on contested ground
({med('C', 'contested_resources')} against {med('A', 'contested_resources')}),
*and* it is more varied — which is the trade-off you would normally expect to
have to pay for fairness, and here you do not.

![Fairness spreads]({figures['fairness']})

A spread is the gap between the best-off and worst-off player divided by the
average, so 0 would mean every player got exactly the same and lower is fairer.

---

## Compactness

How much room the galaxy takes up, and how far apart it puts people. A
description rather than a score: neither direction is better.

![Compactness]({figures['compactness']})

Capping capital neighbours spreads the galaxy out — the typical pair of capitals
goes from {med('A', 'ticks_between_capitals')} to \
{med('C', 'ticks_between_capitals')} ticks apart — and makes the outline rounder
({med('A', 'roundness')} to {med('C', 'roundness')}, where 1.0 is a circle).

---

## Novelty

Whether the galaxy is interesting to play: does its density vary, is there
ground worth defending, are the seats meaningfully different.

![Novelty]({figures['novelty']})

**Chokepoints per star** is the number to watch and it is low everywhere. In an
ordinary galaxy it is {med('A', 'chokepoints_per_star')} — about one star in \
{1 / cell('A', 'chokepoints_per_star')['median']:.0f}. At hyperspace 2 you can
jump 175 units, and the stars sit close enough together that nearly every route
has an alternative, so very little ground is worth holding for its position.
Capping capital neighbours raises it by about \
{cell('C', 'chokepoints_per_star')['median'] / cell('A', 'chokepoints_per_star')['median']:.1f}×, \
to {med('C', 'chokepoints_per_star')}. Still low, but it is the only lever here
that moves it at all.

---

## What the galaxies look like

![Five draws from each condition]({grid_uri})

Rows A and B are the same generator, so the family resemblance is expected — row
B is simply the subset with the lowest front counts. Row C is visibly different:
rounder, more evenly filled, with the capitals holding each other at arm's
length.

---

## Appendix

### How to read the numbers

Every value in this write-up is a **median across the 1,000 maps in an arm, with
the middle half of those maps in brackets**. So `1.43 [1.27–1.59]` means half the
maps you generate land between 1.27 and 1.59, and the middle one is 1.43. The
bracket is not an error bar and it does not shrink if I generate more maps — it
is how much galaxies genuinely differ from each other, which is the thing you are
subject to when you generate exactly one.

The six fairness measures are reported as a **spread**: the gap between the
best-off and the worst-off player, divided by the average of all 32.

| spread | roughly means |
| :--- | :--- |
| 0 | every player got exactly the same |
| 0.35 | the best seat has about 1.5× what the worst seat has |
| 1.25 | about 4× |
| 1.8 | about 6× |

A spread says nothing about whether the map is rich or poor, only whether it
treats players alike. It also cannot tell you whether the worst-off player has a
little or has nothing, which is why the table after next gives the raw worst /
typical / best values in their own units.

### What each measure means

**Fairness — six measures, each reported as a spread across the 32 players.**

| measure | what it counts | how to read it |
| :--- | :--- | :--- |
| contested resources | the resources sitting on neutral stars that both you and at least one rival can reach within 40 ticks | The prize you have to fight for, as opposed to the prize you are handed. A player with none has no reason to leave home; a player surrounded by it has no safe ground. **Zero is not a low score, it is a broken seat** — it means no neutral star is reachable by both you and any rival. |
| fronts | how many rivals' territory touches yours | How many directions you can be attacked from. Territory is worked out by travel time: every star belongs to whoever can get a carrier to it soonest from their starting stars, and two players share a front when a star of one sits within a single jump of a star of the other. A typical seat borders 5 rivals; 1 is a quiet corner and 12 is a nightmare. |
| ticks to 10th star | travel time from your whole starting group to the 10th nearest unowned star | Expansion speed, and it compounds — a player slower to their tenth star is behind on economy for the rest of the game and the gap widens. Measured from all six of your starting stars, not just the capital. |
| ticks to first contact | travel time until you can reach any star a rival begins with | When the shooting can start. Being reachable on tick 8 while a rival is safe until tick 40 is a handicap set before anyone moves. |
| capital exposure | travel time for the nearest rival to reach *your* capital | The same question aimed at the one star whose loss ends your game in the elimination modes. Measured towards you, so this is the one fairness measure where **a bigger number is better for you**. |
| starting vision | how many stars you can see from your starting group on turn one | Solaris has fog, so this is how much of the map you begin knowing. Counted per star rather than at one flat radius, because terrain changes scanning range — a black hole sees three levels further than an ordinary star. |

**Compactness — two measures, one value per map. Neither has a better
direction; they describe the galaxy rather than score it.**

| measure | what it counts | how to read it |
| :--- | :--- | :--- |
| ticks between capitals | the median travel time between every pair of capitals | How much room the galaxy actually occupies, in the units the game cares about. Lower is a tighter galaxy where everyone is in reach of everyone. |
| roundness | the shape of the galaxy's outline, as `4π × area ÷ perimeter²` | 1.0 is a perfect circle and a square scores 0.785. Lower means long, stringy or ragged. Independent of size, so it separates "a bigger galaxy" from "a differently shaped one". |

**Novelty — three measures, one value per map. Higher is more varied.**

| measure | what it counts | how to read it |
| :--- | :--- | :--- |
| local density variation | how much star density varies from place to place across the galaxy | 0 would be a perfectly even field with no places in it. 0.33 means a typical neighbourhood is about a third denser or sparser than average. Higher means the galaxy has regions rather than being uniform mush. |
| chokepoints per star | the share of stars whose loss would cut a region off from the rest | 0.25 would mean one star in four is worth holding for its position alone. Measured at the jump range players actually start with, because the question is how redundant the routes are at the range people can currently fly. Low numbers mean there is nothing to defend. |
| how different the seats are | how differently the 32 players are placed relative to one another, across five of the fairness quantities at once | 0 means every player is in an identical position — which is exactly what a rotationally symmetric map scores by construction. Higher means genuinely different seats. **It does not say whether the differences are fair**; that is what the six spreads are for. The goal is a map that is high here and low on the spreads: players facing different problems of equal difficulty. |

**The fairness index** used in Finding 1 is not one of the eleven. It is the
average of the six fairness spreads after putting each on a common scale, signed
so lower is fairer, and it exists only to rank maps against each other in the
selection experiment. It is deliberately not reported as a measure anywhere else,
because averaging six things that trade against each other hides which one moved.

### All eleven measures

Median across the 1,000 maps in each arm, with the middle half in brackets.

{table(["measure", f"A · {NAME['A']}", f"B · {NAME['B']}",
        f"C · {NAME['C']}"], appendix_rows)}

### What the worst-off player actually gets

A spread cannot tell you whether the worst-off player has a little or nothing at
all. Worst / typical / best player, pooled across every map in the arm.

{table(["measure", "unit", f"A · {NAME['A']}", f"B · {NAME['B']}",
        f"C · {NAME['C']}"], pooled_rows, ["l", "l", "r", "r", "r"])}

### The three arms

{table(["", "how the galaxy is made", "how it is chosen"],
       [[f"**A** · {NAME['A']}", "the game's irregular generator, unmodified",
         f"the first 1,000 of {acc['n']:,} draws"],
        [f"**B** · {NAME['B']}", "the same generator",
         f"the 1,000 of {acc['n']:,} closest to 2–4 fronts"],
        [f"**C** · {NAME['C']}",
         "capitals carved so each has 2–4 neighbouring capitals",
         "1,000 draws, unselected"]],
       ["l", "l", "l"])}

All three use the game's published 32-player setup: 32 players, 640 stars, six
starting stars each, hyperspace 2 and scanning 3 at the start.

### Method

Galaxies were built to match the game's own behaviour rather than this
repository's map builder, which adds a fairness layer the game does not have.
That means uniform random star resources with no distance weighting, terrain
scattered one star at a time and never evened out, no separation cleanup, and no
build-time balance checks. Only the capital gets fixed resources, so **starting
positions in a real game are not identical** — total starting resources varied by
roughly 40% between the best and worst seat.

The fairness index in Finding 1 is the average of the six fairness spreads after
standardising each one, signed so lower is fairer. It exists to rank maps for the
selection experiment and is not reported as a measure anywhere else, because
averaging six things that trade against each other hides which one moved.

### Caveats

- **Fronts is measured at the jump range players start with.** An earlier version
  of this study measured borders on whatever jump range finally connects the
  galaxy, which on a badly connected map is hyperspace 8 — a 475-unit jump
  against the 175 players actually have. That counted territories two and three
  regions apart as touching and inflated front counts to as many as 20. The other
  ten measures were checked for the same fault and none of them has it.
- **{split:.0f}% of galaxies are not one connected piece at the starting jump
  range.** This is normal for this generator — the voids are the point — and
  travel times are measured at the range where the galaxy does join up.
- **Arm B is a selection, not a guarantee.** No map satisfies the {lo}–{hi} band
  outright, so arm B is the closest 1,000 available. Even the best map in the run
  leaves {best_out} of its 32 players outside.
- **This is a reimplementation of the game's generator, not the game itself.**
  It follows the same steps with the same constants, but its random number
  generator is not identical, so the same seed gives a different galaxy. The
  rates here describe the algorithm, not measurements taken from live games.
- **No game was played.** Everything here is measured on the starting position,
  before anyone moves.
""")
