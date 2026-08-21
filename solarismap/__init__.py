"""solarismap - build Solaris custom galaxies that Solaris will actually accept.

Nine modules, in the order a map builder uses them:

    rules       game constants and math - hyperspace, scanning, terraforming,
                and the hard limits Solaris's validator enforces
    geometry    points, spacing, reachability and scan queries
    generate    procedural layouts - the editor's six galaxy generators, for
                maps grown rather than placed by hand
    randomise   star properties rather than positions - resources per channel,
                terrain, wormholes; the editor's Randomise menu
    model       factories for stars, players and carriers, and the writer that
                emits the exact CustomGalaxy shape
    validate    Solaris-parity validation; run it before you ship a map
    inspect     measure a finished map - balance, spacing, reach, scanning
    metrics     score a finished map - fairness, compactness, novelty
    render      draw it to SVG using the game's own art

Plus `specialists`, the real specialist table synced out of the editor's store.

There is a command line over all of it: `python -m solarismap --help`.

A minimal map:

    from solarismap import geometry, model, rules, validate

    stars = [model.new_star(geometry.polar(400, angle)) for angle in (0, 120, 240)]
    model.assign_ids(stars)
    for n, star in enumerate(stars, start=1):
        model.set_resources(star, 25)
        model.make_home_star(star, str(n), ships=10)
    players = [model.new_player(str(n), star["id"])
               for n, star in enumerate(stars, start=1)]

    galaxy = model.galaxy(stars, players)
    validate.validate(galaxy).raise_for_errors()
    model.write("my_map.json", galaxy)
"""

from . import (generate, geometry, inspect, metrics, model, randomise,   # noqa: F401
               render, rules, specialists, validate)

__all__ = ["generate", "geometry", "inspect", "metrics", "model", "randomise",
           "render", "rules", "specialists", "validate"]
