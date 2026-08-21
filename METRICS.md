# Criteria for evaluating a galaxy

A map can be perfectly legal and still be a bad map: one player boxed into a corner, another
handed a quiet third of the board, a galaxy so evenly packed there is nowhere in it worth
holding. 

These are eleven proposed criteria for judging a map before anyone plays it, in three categories:

- **Fairness** — is every player treated alike? Six criteria, each of them something a player
  could reasonably be annoyed about afterwards.
- **Compactness** — how big is the galaxy, and how far apart does it put people? Evaluates whether the galaxy geometry is fun to reflect on after the map.
- **Novelty** — is the map worth playing, and worth playing twice? A
  perfectly fair map can be perfectly dull.

To implement, apply the metrics to any Solaris JSON.

```sh
python -m solarismap metrics out/irregular.json
```

---

## Two levels of statistics

Every fairness criterion produces a number **per player**: player 3 borders five rivals, player 7 borders one. What matters more is how these statistics are spread across maps, and how much spread can vary between map seeds.



### Within a map —  spread

How *unequal* the players' values are, as `(max − min) ÷ mean`. This is unitless to make comparisons across the criteria fair.

For example: If Ten players border 1, 2, 2, 3, 3, 3, 4, 4, 5, 5 rivals, then Mean 3.2, max − min = 4, so the spread is
4 ÷ 3.2 = **1.25**.

**0 means every player got the same. Lower is fairer.** To anchor interpretation: 0.35 is roughly a 1.5x gap
between the best and worst seat, 1.25 about 4x, 1.8 about 6x.

**Always read the uncertainty in addition to the spread.** The band is `(worst, typical, best)` in real units and it catches the experience of players separate from the typical value: a spread cannot tell if the  "the worst-off player has a little" from "the worst-off player has nothing". 

### Across maps — distribution

Generators are stochastic. A criterion measured on one map is a monte carlo **draw**, not a property of the generator that made it. A claim about a generator therefore needs to be about distributions, rather than within map spreads.

- **The interval is a percentile interval of the draws** (10th–90th). It answers "how much does the map I am about to generate vary?"
- **The coefficient of variation** says the same thing in one number. Read it before the median. A CV of 25% means the map you get differs from the typical map by about a quarter, routinely.

---

## Fairness

| criterion | what it measures | unit |
| --- | --- | --- |
| contested resources | resources on neutral stars you and a rival can both reach quickly | resources |
| fronts | how many rivals' territory touches yours | rival players |
| ticks to the 10th star | travel time to your 10th nearest unowned star | ticks |
| first contact | travel time until you can touch any rival-owned star | ticks |
| capital exposure | travel time for the nearest rival to reach your capital | ticks |
| starting vision | stars visible from your starting pod on turn one | stars |

### Contested resources

A player with nothing contested nearby has an easy start, while a player whose every neighbour is contested has no safe ground.

Zero for this statistic means there is no neutral star that both this player and a rival can get to, so there is no contested ground at all. 

### Fronts

How many directions you can be attacked from. 

Two players are on a front when their territories touch, calculated by when a player first reaches another expanding outward. 

### Ticks to the 10th star

Measures expansion speed. A player slower to their tenth star is behind on economy for
the rest of the game, and the gap widens with ticks.

Measured from a player's **whole starting pod**, not their capital.

### First contact

How many ticks until first contact (see also Fronts). Being reachable on tick 8 while a rival is safe until tick 40 is a handicap.

### Capital exposure

It is measured *towards* a player rather than from a player. So a higher number is better for player.

### Starting vision

Vision is counted per star rather than at a flat radius, because terrain changes what a star can
see: a black hole scans considerably further than a plain star

---

## Compactness

Added out of a personal preference. I get more joy out of seeing a final map that looks unexpected and stringy. More compact and rounded galaxies will tend to be more fair, though less interesting visually. These are purely aesthetic considerations rather than strategic or fair.

### Ticks between capitals

Median travel time between every pair of capitals. Essentially, how much room a galaxy occupies.

### Roundness

0 to 1, where 1.0 is a perfect circle and lower means long, stringy or ragged. A square would score 0.785.

---

## Novelty criteria

Fairness is at ends with novelty, which is important for strategic play, diplomacy, and keeping the game compelling. 

| criterion | what it measures | reading |
| --- | --- | --- |
| local density variation | how much star density varies across the galaxy | 0 = a perfectly even field. 0.33 = a typical neighbourhood is a third denser or sparser than average |
| chokepoints per star | share of stars whose loss would cut off a region | 0.25 = one star in four is a chokepoint worth holding |
| situation divergence | how differently the players starting positions are from each other | 0 = every player in an identical position. Higher = genuinely different seats |
| between-map diversity | how different a generator's maps are from *each other* | 0 = it makes the same galaxy every time |

---

## Using them together

The three criteria are at ends:

- Fairness costs novelty. Regularising a galaxy to even out the starting positions makes it rounder and denser, which removes strategic chokepoints.
- Novelty costs fairness. Spreading a galaxy out creates interesting geometry and situations, while at the same time puts contested ground out of reach of whoever was badly placed.
- Compactness explains both, and explains visual interest.

Practically, fairness is likely a **floor**, then a decision could be made
between maps on strategic and aesthetic novelty. Because seed-to-seed variation is large, generating
twenty maps and keeping the best given a set of criteria is likely a bigger improvement than any change
to generators themselves and would also make it easy to implement better map generation within the game (e.g., way less code would need to be written besides implementing the statistics and using them to select candidates!).
