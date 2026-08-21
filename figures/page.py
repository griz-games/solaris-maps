#!/usr/bin/env python3
"""The report page. Structure and prose only - every number comes from `agg`.

Kept apart from `fronts_report.py` so the analysis is not tangled with the
writing. Nothing here computes a statistic; it formats what the aggregation
already decided.
"""

from __future__ import annotations

import html

from solarismap import metrics

import fronts_study as study

ARMS = ("A", "B", "C")
ARM_LABEL = {"A": "A — status quo", "B": "B — fronts 2–9", "C": "C — n-limit 2–4"}


def esc(text) -> str:
    return html.escape(str(text), quote=True)


# Deliberately single-theme.
#
# The tokens are the ones `docs/index.html` already uses - the project has a
# deep-space identity and this report belongs to it. It is also the only ground
# the figures work on: `render.draw` paints a map on `Palette.ink`, pure black,
# so the five galaxy plates are black whatever the viewer's theme is, and a
# light page would frame them badly.
#
# The three series colours are the site's blue, amber and green stepped down
# into the dark lightness band; the originals sit at L 0.69-0.78 and fail it.
# Validated as a set against this ground with the dataviz validator:
# all-pairs CVD dE 9.6, normal-vision dE 20.1, all three over 3:1 contrast.
STYLE = """
<style>
  :root {
    --page:#05070b; --surface-1:#0b1017; --border:#1b2531;
    --text-primary:#dbe5ef; --text-secondary:#a9bccf; --text-muted:#8fa3b8;
    --faint:#5b6b7f; --grid:#161f2b; --axis:#2b3a4c;
    --series-1:#3a80e0; --series-2:#c87d00; --series-3:#1c9b76;
    --accent:#ff9f0c;
    --mono:ui-monospace,"Cascadia Mono",Menlo,Consolas,monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    color-scheme:dark;
  }
  html { background:var(--page); }
  body { background:var(--page); color:var(--text-primary); margin:0; }
  .doc { margin:0 auto; padding:56px 24px 112px; max-width:900px;
         font-family:var(--sans); line-height:1.62; }

  /* Monospace is the site's voice: it carries every heading, label and number.
     Long-form prose is the one thing it does badly, so body copy is sans. */
  .doc h1, .doc h2, .doc h3, .doc .eyebrow, .doc thead th, .doc tr.group td,
  .doc .key .n, .doc .mapmeta, .doc .tag { font-family:var(--mono); }

  .doc .eyebrow { font-size:11.5px; letter-spacing:0.16em; text-transform:uppercase;
                  color:var(--accent); margin:0 0 14px; }
  .doc h1 { font-size:31px; line-height:1.2; margin:0 0 14px; font-weight:600;
            letter-spacing:-0.015em; text-wrap:balance; color:#fff; }
  .doc h2 { font-size:16px; margin:52px 0 12px; font-weight:600;
            letter-spacing:0.02em; padding-top:16px;
            border-top:1px solid var(--border); text-wrap:balance; }
  .doc h3 { font-size:14px; margin:30px 0 8px; font-weight:600;
            letter-spacing:0.02em; color:var(--text-primary); }
  .doc p, .doc li { color:var(--text-secondary); font-size:15.5px; max-width:68ch; }
  .doc .lede { font-size:17.5px; line-height:1.55; color:var(--text-primary);
               margin:0 0 4px; max-width:64ch; }
  .doc strong { color:var(--text-primary); font-weight:600; }
  .doc code { font-family:var(--mono); font-size:0.88em; color:var(--text-primary);
              background:var(--surface-1); border:1px solid var(--border);
              border-radius:4px; padding:1px 5px; }

  .doc figure { margin:26px 0; background:var(--surface-1);
                border:1px solid var(--border); border-radius:4px; padding:20px; }
  .doc figcaption { font-size:12.5px; color:var(--text-muted); margin-top:14px;
                    max-width:76ch; line-height:1.5; }
  .doc .scroll { overflow-x:auto; -webkit-overflow-scrolling:touch;
                 margin:18px 0; border:1px solid var(--border); border-radius:4px; }
  .doc table { border-collapse:collapse; width:100%; font-size:13px;
               min-width:660px; background:var(--surface-1); }
  .doc th, .doc td { text-align:left; padding:8px 12px;
                     border-bottom:1px solid var(--border); }
  .doc tbody tr:last-child th, .doc tbody tr:last-child td { border-bottom:0; }
  .doc thead th { font-size:11px; text-transform:uppercase; letter-spacing:0.08em;
                  color:var(--text-muted); font-weight:500; white-space:nowrap; }
  .doc tbody th { font-weight:400; color:var(--text-primary); }
  .doc td.num { text-align:right; font-variant-numeric:tabular-nums;
                font-family:var(--mono); color:var(--text-primary);
                white-space:nowrap; }
  .doc td.muted, .doc .muted { color:var(--faint); }
  .doc tr.group td { color:var(--accent); font-size:10.5px; text-transform:uppercase;
                     letter-spacing:0.1em; padding-top:18px; }

  .doc .keys { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
               gap:1px; margin:28px 0; background:var(--border);
               border:1px solid var(--border); border-radius:4px; }
  .doc .key { background:var(--surface-1); padding:18px 18px 16px; }
  .doc .key .n { font-size:27px; font-weight:600; color:#fff;
                 letter-spacing:-0.02em; display:block; margin-bottom:6px;
                 font-variant-numeric:tabular-nums; }
  .doc .key .l { font-size:12.5px; color:var(--text-muted); line-height:1.45; }
  .doc .swatch { display:inline-block; width:9px; height:9px; border-radius:2px;
                 margin-right:7px; vertical-align:baseline; }

  .doc .maprow { margin:30px 0; }
  .doc .map { margin:0 0 8px; border:1px solid var(--border); border-radius:4px;
              overflow:hidden; background:#000; }
  .doc .map svg { width:100%; height:auto; display:block; }
  .doc .mapmeta { font-size:12px; color:var(--text-muted);
                  font-variant-numeric:tabular-nums; }
  .doc .tag { display:inline-block; font-size:10.5px; padding:1px 8px;
              border-radius:2px; border:1px solid var(--border);
              color:var(--text-secondary); margin-left:8px;
              letter-spacing:0.04em; }
  .doc ul { padding-left:18px; }
  .doc li { margin-bottom:9px; }
  .doc .note { border-left:2px solid var(--accent); padding:4px 0 4px 16px;
               margin:22px 0; color:var(--text-primary); font-size:15px; }
  .doc a:focus-visible, .doc [tabindex]:focus-visible {
      outline:2px solid var(--accent); outline-offset:2px; }
</style>
"""


def key_numbers(agg: dict) -> str:
    acc = agg["acceptance"]
    cacc = agg["c_acceptance"]
    never_a = agg["arms"]["A"]["connect"].get("never", 0)
    return f"""
<div class="keys">
  <div class="key"><span class="n">{acc['rate'] * 100:.1f}%</span>
    <span class="l">of unconstrained draws put all 32 players inside 2–9 fronts
    ({acc['accepted']:,} of {acc['n']:,})</span></div>
  <div class="key"><span class="n">{cacc['rate'] * 100:.1f}%</span>
    <span class="l">of n-limit draws do, without any selection</span></div>
  <div class="key"><span class="n">{never_a * 100 / max(sum(agg['arms']['A']['connect'].values()), 1):.1f}%</span>
    <span class="l">of status-quo galaxies never become one piece by hyperspace 8</span></div>
  <div class="key"><span class="n">0</span>
    <span class="l">draws rejected by Solaris's validator, across all
    {sum(agg['arms'][a]['n'] for a in ARMS):,} measured maps</span></div>
</div>"""


def examples_section(examples: list[dict]) -> str:
    out = []
    for ex in examples:
        lo, hi = ex["fronts"]
        tag = ("inside the 2–9 band" if ex["in_band"]
               else f"outside the band (max {hi})")
        connect = "never" if ex["connect"] is None else f"hyperspace {ex['connect']}"
        out.append(f"""
<div class="maprow">
  <div class="map">{ex['svg']}</div>
  <div class="mapmeta"><code>{esc(ex['seed'])}</code>
    <span class="tag">{esc(tag)}</span>
    &nbsp; fronts {lo}–{hi} &nbsp;· spread {ex['spread']:.2f}
    &nbsp;· one piece at {connect}
    &nbsp;· chokepoints {ex['chokepoints']:.3f}
    &nbsp;· roundness {ex['roundness']:.2f}</div>
</div>""")
    return "".join(out)


def observations(agg: dict) -> str:
    """Descriptive readings of the tables above. No recommendations."""
    a, b, c = (agg["arms"][x] for x in ARMS)
    lo, hi = study.FRONTS_BAND
    prob = agg["prob"]

    def m(arm: str, name: str) -> float:
        return agg["arms"][arm]["stats"][name]["median"]

    unchanged = [n for n in metrics.FAIRNESS
                 if prob["B"][n] is not None and abs(prob["B"][n] - 0.5) < 0.05]
    a_connect = sum(a["connect"].values())
    a_split = 100 * (a_connect - a["connected_at_start"]) / a_connect
    a_never = 100 * a["connect"].get("never", 0) / a_connect
    b_never = 100 * b["connect"].get("never", 0) / max(sum(b["connect"].values()), 1)
    fronts_total = sum(a["fronts_pool"].values())
    a_ones = 100 * a["fronts_pool"].get(1, 0) / fronts_total
    c_ones = 100 * c["fronts_pool"].get(1, 0) / max(sum(c["fronts_pool"].values()), 1)
    c_deg = c["capdeg_pool"]
    c_out = 100 * sum(v for k, v in c_deg.items() if k < 2 or k > 4) / max(sum(c_deg.values()), 1)

    return f"""
<h3>Observations</h3>

<ul>
<li><strong>The band is reachable but uncommon.</strong>
{agg['acceptance']['rate'] * 100:.1f}% of unconstrained draws seat all 32 players
inside {lo}–{hi} fronts. Changing the generator instead raises that to
{agg['c_acceptance']['rate'] * 100:.1f}% with no selection at all.</li>

<li><strong>Selecting on fronts moves fronts, and little else.</strong> The
fronts spread falls from {m('A', 'fronts'):.2f} to {m('B', 'fronts'):.2f}
(P = {prob['B']['fronts']:.2f}) and contested resources from
{m('A', 'contested_resources'):.2f} to {m('B', 'contested_resources'):.2f}
(P = {prob['B']['contested_resources']:.2f}). The remaining
{len(unchanged)} fairness statistics —
{esc(", ".join(metrics.LABELS[n] for n in unchanged))} — sit within 0.05 of
0.50, meaning a selected map is indistinguishable from an unselected one on
them.</li>

<li><strong>The generator change buys novelty rather than fairness.</strong> Arm
C matches arm B on contested resources
(P = {prob['C']['contested_resources']:.2f}) while moving fronts less
(P = {prob['C']['fronts']:.2f}), and it raises both structural novelty
statistics: local density variation P = {prob['C']['density_variation']:.2f},
chokepoints per star P = {prob['C']['chokepoints_per_star']:.2f}. It is also
rounder ({m('A', 'roundness'):.3f} to {m('C', 'roundness'):.3f}) and more
spread out ({m('A', 'ticks_between_capitals'):.0f} to
{m('C', 'ticks_between_capitals'):.0f} ticks between capitals).</li>

<li><strong>There is almost nothing defensible on any of these maps.</strong>
Chokepoints per star has a median of {m('A', 'chokepoints_per_star'):.3f} in arm
A — roughly one star in {1 / m('A', 'chokepoints_per_star'):.0f} is a cut vertex.
At hyperspace 2 the galaxy is dense relative to the jump range, so routes are
redundant nearly everywhere. Arm C raises it to
{m('C', 'chokepoints_per_star'):.3f}, which is still low in absolute terms.</li>

<li><strong>Most galaxies are not one piece at the opening jump.</strong>
{a_split:.1f}% of arm-A draws are in separate pieces at hyperspace 2, and
{a_never:.1f}% never join up by hyperspace 8. This is expected behaviour rather
than a defect — the voids are what give a grown galaxy its shape — but nothing
in the game measures it.</li>

<li><strong>The band selects connectivity as a side effect.</strong> Arm B
contains no galaxy that fails to join up ({b_never:.1f}% never-connecting,
against {a_never:.1f}% in arm A) and none with a marooned star. A galaxy in
pieces produces extreme front counts, so conditioning on fronts silently
conditions on connectivity. Differences between A and B on any
connectivity-sensitive statistic should be read with that in mind.</li>

<li><strong>The worst seats are extreme in every arm.</strong> Pooled over all
draws, the minimum first contact and the minimum capital exposure are both
1 tick: some player, on some map, starts within a single tick of a rival's
capital. Selection on fronts does not remove this.</li>

<li><strong>One-front seats are a status-quo phenomenon.</strong>
{a_ones:.1f}% of arm-A seats border a single rival, against {c_ones:.2f}% in arm
C. Bounding capital seating removes them almost entirely without any selection
step.</li>

<li><strong>The n-limit constraint is not exact.</strong> {c_out:.2f}% of arm-C
capitals fall outside the requested
{study.N_LIMIT_KWARGS['min_neighbours']}–{study.N_LIMIT_KWARGS['max_neighbours']}
neighbour band, which the generator's two fix-up rounds did not repair.</li>
</ul>"""


def build_page(agg: dict, figures: dict, examples: list[dict]) -> str:
    a, b, c = (agg["arms"][x] for x in ARMS)
    acc = agg["acceptance"]
    lo, hi = study.FRONTS_BAND

    def med(arm: str, name: str, places: int = 2) -> str:
        cell = agg["arms"][arm]["stats"][name]
        return "–" if not cell else f"{cell['median']:.{places}f}"

    def pooled(arm: str, name: str, key: str, places: int = 0) -> str:
        value = agg["arms"][arm]["pooled"][name][key]
        return "–" if value is None else f"{value:.{places}f}"

    return f"""<title>Fronts and Fairness</title>
{STYLE}
<main class="doc">

<p class="eyebrow">Solaris · irregular galaxy · {acc['n']:,} draws</p>
<h1>Fronts and fairness in the 32-player irregular galaxy</h1>
<p class="lede">A Monte Carlo study of {acc['n']:,} galaxies generated the way
Solaris generates them, measured on eleven statistics, and compared against the
same generator restricted to maps where every player has between {lo} and {hi}
fronts.</p>

{key_numbers(agg)}

<h2>Design</h2>

<p>Three arms, {a['n']:,} draws each. Arm B is arm A conditioned on the fronts
band rather than a different generator, so every difference between A and B is
attributable to the selection and to nothing else. Arm C changes the generator
instead of selecting on the output.</p>

<div class="scroll"><table>
<thead><tr><th>arm</th><th>generator</th><th>selection</th><th>n</th></tr></thead>
<tbody>
<tr><th scope="row"><span class="swatch" style="background:var(--series-1)"></span>A — status quo</th>
    <td><code>irregular</code></td><td>none</td><td class="num">{a['n']:,}</td></tr>
<tr><th scope="row"><span class="swatch" style="background:var(--series-2)"></span>B — fronts {lo}–{hi}</th>
    <td><code>irregular</code></td>
    <td>kept only when every player has {lo}–{hi} fronts</td>
    <td class="num">{b['n']:,}</td></tr>
<tr><th scope="row"><span class="swatch" style="background:var(--series-3)"></span>C — n-limit {study.N_LIMIT_KWARGS['min_neighbours']}–{study.N_LIMIT_KWARGS['max_neighbours']}</th>
    <td><code>irregular_n_limit</code></td>
    <td>none</td><td class="num">{c['n']:,}</td></tr>
</tbody></table></div>

<h3>Settings</h3>

<p>Taken from the game's own 32-player templates,
<code>32player_capital_elimination.json</code> and
<code>32player_experimental.json</code>. The two are identical in every field
this study reads.</p>

<div class="scroll"><table>
<thead><tr><th>setting</th><th>value</th><th>consequence</th></tr></thead>
<tbody>
<tr><th scope="row">playerLimit</th><td class="num">32</td><td class="muted">—</td></tr>
<tr><th scope="row">galaxyType</th><td>irregular</td><td class="muted">—</td></tr>
<tr><th scope="row">starsPerPlayer</th><td class="num">20</td><td class="muted">640 stars</td></tr>
<tr><th scope="row">startingStars</th><td class="num">6</td><td class="muted">capital + 5</td></tr>
<tr><th scope="row">hyperspace</th><td class="num">2</td><td class="muted">175 unit opening jump</td></tr>
<tr><th scope="row">scanning</th><td class="num">3</td><td class="muted">200 unit vision</td></tr>
<tr><th scope="row">splitResources</th><td>enabled</td><td class="muted">three channels rolled independently</td></tr>
<tr><th scope="row">resourceDistribution</th><td>random</td>
    <td class="muted">forced for irregular regardless of the setting</td></tr>
<tr><th scope="row">random terrain</th>
    <td>nebula 15, asteroid 10, binary 10, black hole 5, pulsar 1, warp gate 10, wormhole 3</td>
    <td class="muted">percent of stars</td></tr>
</tbody></table></div>

<h3>What was deliberately not applied</h3>

<p>The map builder in this repository adds a fairness layer that the game does
not have. Every one of those passes changes the quantities measured here, so
none of them ran. The build applies what the game applies, in the game's
order.</p>

<ul>
<li><strong>No separation relaxation.</strong> The game ships whatever its
pull-into-range pass leaves behind, overlapping stars included.</li>
<li><strong>No positional resource curve.</strong>
<code>ResourceService.distribute</code> forces the random path for irregular and
doughnut galaxies regardless of the <code>resourceDistribution</code> setting, so
a live irregular galaxy prices every star uniformly in [10, 50] with no
distance term at all.</li>
<li><strong>No wealth, terrain or opening rebalancing.</strong> Terrain is
scattered uniformly one star at a time and never evened out.</li>
<li><strong>No build-time bands.</strong> The builder's <code>check()</code>
asserts forty-odd properties and fails the build when one breaks. The game
asserts none of them, so nothing here was rejected for imbalance.</li>
</ul>

<p>One consequence is worth stating on its own: because only the capital is
pinned to fixed resources and the other five starting stars keep whatever the
random roll gave them, <strong>openings in a live game are not identical across
players.</strong> Total starting natural resources varied by roughly 40% between
the best and worst seat in a spot check.</p>

<h2>What the game does about any of this</h2>

<p>Nothing. The map is generated once, at game creation, and saved.
<code>IrregularMapService.generateLocations</code> carves voids by sorting every
candidate location on a simplex noise field and truncating the array; the step
has no notion of connectivity. Its only reachability logic operates on a single
player's own starting stars. <code>MapService</code> contains one
<code>throw</code> in 521 lines, for an unsupported galaxy type. Every check in
<code>GameCreateService</code> runs on <em>settings</em> before generation — at
least two players, starting stars not exceeding total stars, a 1500-star
ceiling — after which the generated galaxy is assigned to the game and written to
the database unexamined.</p>

<p class="note">There is no connectivity test, no fairness test, no retry, no
regeneration and no preview gate. A severed 32-player irregular galaxy is a
legal game. Separately, a severed <em>custom</em> galaxy also passes the
custom-galaxy validator, whose semantic rules cover identifiers, wormhole
targets, specialists, home stars, ship counts and dead stars, but not
topology.</p>

<h2>Sampling and acceptance</h2>

<p>A single stream of {acc['n']:,} draws supplied arms A and B: A is the first
{a['n']:,} draws of it, B is the first {b['n']:,} that cleared the band.
{acc['accepted']:,} of {acc['n']:,} draws cleared it, an acceptance rate of
<strong>{acc['rate'] * 100:.1f}%</strong>. Arm C was drawn separately and
{agg['c_acceptance']['rate'] * 100:.1f}% of its draws would have cleared the same
band without any selection applied.</p>

<h2>Fronts</h2>

<p>A player's fronts are the number of rivals whose territory touches theirs.
Territory is a travel-time partition: every star belongs to whichever player's
starting pod can reach it soonest, and two players are on a front when a star of
one lies within a single jump of a star of the other. It is measured on all
{study.PLAYERS * study.STARS_PER_PLAYER} stars, not on capital positions.</p>

<figure>{figures['fronts']}
<figcaption>Pooled across every player of every draw. Dashed lines mark the
{lo}–{hi} band. Arm B is inside it by construction; arm A and arm C are not
constrained.</figcaption></figure>

<p>Capital lattice degree is a different quantity and a much narrower one: it
counts how many rival capitals sit adjacent on the generator's triangular
lattice, so it is bounded above by six. Arm C constrains this directly; arms A
and B do not.</p>

<figure>{figures['capdeg']}
<figcaption>Adjacent rival capitals per player. Arm C's generator carves capitals
out of a hex grid so that each keeps
{study.N_LIMIT_KWARGS['min_neighbours']}–{study.N_LIMIT_KWARGS['max_neighbours']}
neighbours.</figcaption></figure>

<h2>Results</h2>

<p>Each fairness statistic is reported as a spread — the range across players
divided by the mean, so 0 means every player got the same and lower is fairer.
The interval is a percentile interval of the draws, not a confidence interval on
the mean: it answers how much the map you are about to generate varies, and it
does not shrink with more draws. Read the coefficient of variation before the
median.</p>

<figure>{figures['fairness']}
<figcaption>Fairness spreads. Each bar spans the 10th to 90th percentile of the
{a['n']:,} draws in that arm; the dot is the median and the number at the right
repeats it. The range under each group is the axis extent for that
statistic.</figcaption></figure>

<figure>{figures['other']}
<figcaption>Compactness has no better direction and is not ranked. Novelty is
read in the opposite direction to fairness: higher is more varied.</figcaption>
</figure>

<div class="scroll">{figures['table_stats']}</div>

<h3>Effect sizes</h3>

<p>The probability that a randomly drawn map from an arm beats a randomly drawn
map from arm A on that statistic. 0.50 means the two are indistinguishable on a
single draw, which is the only draw a real game gets. Compactness is absent
because it has no better direction.</p>

<figure>{figures['prob']}
<figcaption>Common-language effect size against arm A. The pair of numbers at
the right is B then C.</figcaption></figure>

<h3>What the worst-off player actually gets</h3>

<p>A spread cannot distinguish a worst-off player who has a little from one who
has nothing. These are the pooled per-player values in their own units, across
every draw in the arm.</p>

<div class="scroll">{figures['table_pooled']}</div>

<h3>Connectivity</h3>

<p>A grown galaxy is not one piece at the opening jump and is not meant to be;
the voids are the point. What matters is whether the whole map opens up
eventually. Travel statistics are measured at the level where the galaxy becomes
one piece, because measuring them at the opening jump produces infinite distances
whose removal scores a badly connected map as a fairer one.</p>

<div class="scroll">{figures['table_connect']}</div>

{observations(agg)}

<h2>Five draws</h2>

<p>Five arm-A seeds chosen at random from the {a['n']:,}, rendered without
resource and garrison labels for legibility. Each is a galaxy the game would
have served without comment.</p>

{examples_section(examples)}

<h2>Limitations</h2>

<ul>
<li><strong>This is a port, not the game.</strong> The generator reproduces
<code>irregular.ts</code> step for step and matches its constants — the hardcoded
<code>SPREAD = 2.5</code> and the noise spread formula — but the two npm
dependencies it relies on, <code>simplex-noise</code> and
<code>random-seed</code>, are reimplemented rather than bit-ported. The same seed
does not give the same galaxy. Rates reported here describe this implementation
of the algorithm, not measurements taken from live games.</li>
<li><strong>Fronts is measured at the connectivity level, not the opening
jump.</strong> Jump range there is longer, so more stars are mutually adjacent
and front counts are correspondingly higher than they would be at hyperspace 2
alone.</li>
<li><strong>Wormholes create fronts at arbitrary distance.</strong> A wormhole is
one tick at any range and is included in the adjacency graph, so a player can
share a front with a rival on the far side of the galaxy.</li>
<li><strong>Selection is not a mechanism.</strong> Arm B describes the
subpopulation of galaxies that happen to satisfy the band. It does not say
what makes a galaxy satisfy it, and any statistic correlated with the band moves
in arm B whether or not the band caused it.</li>
<li><strong>No game was played.</strong> Every statistic here is a property of a
starting position, measured before anyone moves.</li>
</ul>

</main>
"""
