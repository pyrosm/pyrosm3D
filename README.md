# pyrosm3d

3D views of the OpenStreetMap elements that [pyrosm](https://github.com/pyrosm/pyrosm) reads with their levels: the walking network inside stations and buildings, and their floors, rooms, walls, doors, stairwells and lifts.

The package is under development and has no release yet.

## Installation

pyrosm3d needs a pyrosm that reads indoor elements. No pyrosm release has them yet, so install both from GitHub:

```bash
pip install "pyrosm @ git+https://github.com/pyrosm/pyrosm@main"
pip install "pyrosm3d @ git+https://github.com/pyrosm/pyrosm3D@main"
```

pyrosm is built from source with this command, which needs a C compiler.

## Example

```python
from pyrosm import OSM
import pyrosm3d

# A PBF file and a box around one building: west, south, east, north
osm = OSM("Helsinki.osm.pbf", bounding_box=[24.9295, 60.2297, 24.9364, 60.2325])

indoor = pyrosm3d.read_indoor(osm)               # layers as GeoDataFrames, in metres
figure = pyrosm3d.plot_indoor(indoor)            # a plotly figure of all levels
figure.show()

pyrosm3d.plot_indoor(indoor, level=1).show()     # one level
pyrosm3d.to_html(indoor, "building.html")        # a page with level buttons

# The walking network alone, each edge at its levels
nodes, edges = osm.get_network("walking", nodes=True, indoor_elements=True)
pyrosm3d.plot_network(edges, nodes).show()
```

`read_indoor` returns the indoor areas, each with its levels and a `kind` (a drawing category such as room, corridor, shaft or wall), the walls, the doors, the shops and amenities that have a level, the building outlines and the walking network. `plot_indoor` draws them: floors with openings for stairs and escalators, walls with a gap at each door, stairwells and lift shafts as columns, and the network. What it can draw depends on what is mapped: the levels come from the `level` tags of [Simple Indoor Tagging](https://wiki.openstreetmap.org/wiki/Simple_Indoor_Tagging).

## Documentation

The pages under [docs/](docs/) show the functions on a real building and list their parameters.

## License

BSD 3-Clause. Map data © OpenStreetMap contributors, ODbL.
