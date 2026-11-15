# pyrosm3d

pyrosm3d draws the OpenStreetMap elements that [pyrosm](https://pyrosm.readthedocs.io) reads with their levels in 3D: the walking network inside stations and buildings, and their floors, rooms, walls, doors, stairwells and lifts. The figures are [plotly](https://plotly.com/python/) figures, which turn and zoom in a notebook or a browser.

The levels come from OpenStreetMap's `level` tags, as [Simple Indoor Tagging](https://wiki.openstreetmap.org/wiki/Simple_Indoor_Tagging) describes them. A building shows as much as its mappers have drawn: some have every room and door, and many have nothing mapped indoors.

The package is under development and has no release yet.

```{toctree}
:maxdepth: 1

installation
indoor_views
reference
changelog
```
