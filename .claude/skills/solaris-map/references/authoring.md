# Authoring a map

The order matters: ids are assigned once the star list is final, because wormholes and
`homeStarId` reference them.

## 1. Place stars

`model.new_star((x, y))` gives a neutral star with every required field and `naturalResources`
left `None` for you to fill. Positions come from `geometry`:

```python
from solarismap import geometry, model

geometry.polar(400, 90)                    # 400 units out at 90 degrees
geometry.rotate((400, 0), 45)              # spin a point about the origin
geometry.translate((400, 0), (60, 20))     # offset
geometry.mirror((37, 11), 45)              # reflect across a bearing
```

Hang whatever bookkeeping you like on the star itself — any key starting with `_` is scratch
and is stripped on write:

```python
star = model.new_star(pos, _role="capital", _wedge=3)
```

## 2. Assign ids

```python
model.assign_ids(stars)        # "1".."N", in list order
```

Do this once, after the last star exists. Everything that references a star by id comes after.

## 3. Resources, infrastructure, ships

```python
model.set_resources(star, 25)               # all three channels
model.set_resources(star, 54, 18, 18)       # economy, industry, science
model.set_infrastructure(star, economy=5, industry=5, science=1)
model.set_ships(star, 10)                   # keeps shipsActual and ships in step
```

Unequal channels switch Solaris's `splitResources` on for the whole game — deliberate on an
asteroid field or nebula, accidental if you did not mean it. `model.split_resources(data)`
tells you which you have.

## 4. Capitals and players

```python
model.make_home_star(capital, "1", ships=10, economy=5, industry=5, science=1)
player = model.new_player("1", capital["id"], technologies={...}, credits=500)
```

`colour` and `shape` are optional and cosmetic — Solaris reassigns both — but the renderer
uses them, so a map with them reads better as a picture.

## 5. Wormholes

```python
model.link_wormhole(a, b)      # sets both ends; raises if ids are missing or equal
```

## 6. Assemble, check, write

```python
data = model.galaxy(stars, players, carriers=[])
validate.validate(data).raise_for_errors()
model.write(OUTPUT, data)
```

## Symmetry, and why it is worth the trouble

The cheapest way to make a map fair is to make every player's start the same start,
rotated. Build one wedge in its own frame, then rotate it into place for each player:

```python
for wedge in range(n_players):
    bearing = wedge * (360.0 / n_players)
    for local in wedge_local_positions:
        stars.append(model.new_star(geometry.rotate(local, bearing), _wedge=wedge))
```

Contested ground then goes on a **midline** — the bearing exactly halfway between two
neighbouring wedges — so it is equidistant from both. The closest a midline gets to either
capital is the perpendicular foot, `capital_radius * cos(half_wedge)`; anywhere further out
is further from both.

Two floating-point traps:

- Rotating by a whole number of degrees perturbs a radius by ~1e-13. If resources are a
  function of radius and you round them, two stars meant to be identical can land either side
  of a rounding boundary. `model.new_star` stores `_radius` rounded to 6 places for exactly
  this; key resource curves off that, not off a fresh `hypot`.
- Compare distances with a tolerance (`abs(a - b) < 1e-6`), never `==`.

## Checking your own work

Validation says the file loads. These say the map plays:

```python
reach = rules.hyperspace_range(starting_hyperspace)
ticks = geometry.connected_hops(stars, capitals, reach)      # inf means unreachable
gaps = geometry.nearest_neighbour_gaps(points)               # crowding
seen = geometry.scanned_by(star, stars, scanning_level)      # what a star reveals
```

Print them in the builder and fail the build when an invariant breaks — `check()` in
`maps/spy_v_spy.py` does this for forty-odd properties, from wormhole pairing to whether every
contested star is genuinely equidistant from the two players who contest it.

A star being unreachable at the starting hyperspace level is not automatically wrong. It is
wrong when it was not a decision.
