# pyrosm3d

3D views of the OpenStreetMap elements that [pyrosm](https://github.com/pyrosm/pyrosm) reads with their levels: the walking network inside stations and buildings, and their floors, rooms, walls, doors, stairwells and lifts.

The package is under development and has no release yet.

## Installation

pyrosm3d adds 3D views to pyrosm's `OSM` object, as `osm.in3d`. No pyrosm release has the accessor or the indoor reads yet, so install both from GitHub:

```bash
pip install "pyrosm @ git+https://github.com/pyrosm/pyrosm@main"
pip install "pyrosm3d @ git+https://github.com/pyrosm/pyrosm3D@main"
```

pyrosm is built from source with this command, which needs a C compiler.

## Example

```python
from pyrosm import OSM

# A PBF file and a box around one building: west, south, east, north
osm = OSM("Helsinki.osm.pbf", bounding_box=[24.9295, 60.2297, 24.9364, 60.2325])

figure = osm.in3d.plot_indoor()            # a plotly figure of all levels
figure.show()

osm.in3d.plot_indoor(level=1).show()       # one level
osm.in3d.to_html("building.html")          # a web page with level buttons
osm.in3d.plot_network().show()             # the walking network alone, each edge at its levels
```

pyrosm does the reading, and pyrosm3d the drawing. Each view of `osm.in3d` reads what it draws with the `OSM` object's own reads: the indoor elements with the walking areas (`get_indoor_elements(walking_areas=True)`), the walking network with `indoor_elements=True`, and the buildings. `plot_indoor` draws floors with openings for stairs and escalators, walls with a gap at each door, stairwells and lift shafts as columns, and the network. What it can draw depends on what is mapped: the levels come from the `level` tags of [Simple Indoor Tagging](https://wiki.openstreetmap.org/wiki/Simple_Indoor_Tagging).

Frames that you have read or changed yourself are drawn with the functions of the package: `pyrosm3d.plot_network(edges, nodes)`, and `pyrosm3d.plot_indoor` and `pyrosm3d.to_html` with the layers that `pyrosm3d.indoor_layers` makes of pyrosm's frames.

## Documentation

The pages under [docs/](docs/) show the functions on a real building and list their parameters.

## License

BSD 3-Clause. Map data © OpenStreetMap contributors, ODbL.
