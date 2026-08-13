# What the validator is telling you

`python -m solarismap validate <map.json>`. Errors are rejections. Warnings are things Solaris
accepts but that will bite somewhere else.

## Errors

| Message | Cause | Fix |
| --- | --- | --- |
| `missing required field(s) ...` | star dict built by hand | build it with `model.new_star()` |
| `id must be a non-empty string` | numeric ids | ids are strings; `model.assign_ids` handles it |
| `duplicate star id` | ids assigned twice, or a star appended after `assign_ids` | assign ids once, after the list is final |
| `stars: N entries, must be 1..1500` | over the cap | fewer stars, or fewer per player — `rules.max_stars_per_player(n)` |
| `naturalResources.x: N is outside 0..2000` | resource curve overshoots | clamp the curve |
| `infrastructure.x: N is outside 0..200` | starting infrastructure too generous | cap it |
| `infrastructure.x is null, Solaris requires a number` | copied from an editor export | `model.set_infrastructure(star)` zeroes all three |
| `home star must have a playerId` | `homeStar` set without ownership | use `model.make_home_star(star, player_id)` |
| `unowned star must have 0 ships` | ships set before ownership, or ownership removed after | `model.set_ships(star, 0)` when clearing `playerId` |
| `dead star cannot have infrastructure / a specialist / a warp gate` | resources zeroed on a star that already had them | zero them together, or give the star resources |
| `specialistId N is not flagged active.custom` | a specialist Solaris does not allow in custom galaxies | `specialists.is_custom_star_specialist(id)` before using one |
| `specialistId N is not a star specialist` | a carrier specialist on a star | ids 19–21 are carrier-only; star ids are 1–18 |
| `wormhole points at itself` | index arithmetic wrapped onto the same star | `model.link_wormhole` refuses this |
| `wormHoleToStarId 'x' does not exist` | linked before ids were assigned, or to a deleted star | link after `assign_ids` |
| `capital 'x' is already claimed by player 'y'` | two players sharing a home star | one capital each |
| `capital 'x' is owned by 'y', not by the player claiming it` | `homeStarId` and `playerId` disagree | set both from the same variable |
| `playerId 'x' is not a player` | star owned by a player that was never added to `players` | add the player, or clear the star |
| `has N home stars, must have exactly 1` | a second `homeStar: true` for one player | only capitals get `homeStar` |
| `players: required in advanced mode` | no `players` array | pass players to `model.galaxy`, or validate `--basic` |
| `carrier ships: 0 is outside 1..20000` | a carrier with no ships | give it at least 1, or drop the carrier |
| `in-flight carrier needs at least one waypoint` | `orbiting: null` with no route | park it at a star instead |
| `waypoint N does not continue from waypoint N-1` | route does not chain | each waypoint's `source` is the previous `destination` |
| `name ... must be 3..30` | a one or two character star name | 3 characters minimum, or leave `name` off |

## Warnings

| Message | What it means |
| --- | --- |
| `wormhole to 'x' is one-way` | Solaris accepts it; the editor rejects it on import, so you could not open the map to look at it. Use `model.link_wormhole`. |
| `has waypoints` | Solaris truncates carrier waypoints outside tutorial games. Harmless, but the route will not survive. |
| `ships N does not match floor(shipsActual)` | the two ship fields disagree. `model.set_ships` keeps them in step. |
| `players/carriers/teams are ignored...` | validated `--basic`, where Solaris reads only `stars`. |

## When the map is valid but wrong

`python -m solarismap inspect <map.json>` and read for:

- **`spread` above a few percent** in stars, ships or natural resources — one player is
  richer than another.
- **`unreachable by anyone`** non-empty — stars nobody can ever take, usually a gap wider than
  the starting hyperspace range.
- **`below the floor`** non-zero — stars closer than 50u, which overlap on screen.
- **`contested stars` of 0** — nobody's expansion overlaps, so there is nothing to fight over.
- **`one-way` wormholes** listed — the same problem as the warning above.

`--hyperspace N` measures reach at a different tech level, which is how to check what the map
opens up as players research.
