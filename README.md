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

# An OpenStreetMap PBF file (.osm.pbf) and a box around one building: west, south, east, north
osm = OSM("Helsinki.osm.pbf", bounding_box=[24.9295, 60.2297, 24.9364, 60.2325])

view = osm.in3d.plot_indoor()              # a deck.gl view of all levels
view.show()

osm.in3d.plot_indoor(level=1).show()       # opened on one level
osm.in3d.to_html("building.html")          # the view as a web page
osm.in3d.plot_network().show()             # the walking network alone, each edge at its levels
```

pyrosm does the reading, and pyrosm3d the drawing. The views of `osm.in3d` read what they draw with the `OSM` object's own reads: the indoor elements with the walking areas (`get_indoor_elements(walking_areas=True)`), the walking network with `indoor_elements=True`, and the buildings. Only `plot_network(graph=...)` reads nothing: it draws the graph it is given. `plot_indoor` draws floors with openings for stairs and escalators, walls with a gap at each door, stairwells and lift shafts as columns, and the network. What it can draw depends on what is mapped: the levels come from the `level` tags of [Simple Indoor Tagging](https://wiki.openstreetmap.org/wiki/Simple_Indoor_Tagging), and a platform or a walking area without one takes the level of its lines in the network, else its layer below ground, else street level.

Frames that you have read or changed yourself are drawn with the functions of the package, which take pyrosm's frames: `pyrosm3d.plot_indoor(elements, edges, nodes, buildings)`, `pyrosm3d.to_html(elements, path, edges, nodes, buildings)` and `pyrosm3d.plot_network(edges, nodes)`.

## Heights in metres

OpenStreetMap levels are counted from each building's own ground floor, so on a slope the levels of two buildings do not meet. With a terrain model, pyrosm3d places the walking network at heights in metres: streets lie on the terrain, and floors are placed from the streets that they meet.

```python
dem = "elevation.tif"                          # a raster of ground heights that you supply

nodes, edges = osm.in3d.get_network(dem=dem)   # the edges with u_height and v_height
osm.in3d.plot_network(dem=dem).show()          # the network drawn in metres
osm.in3d.plot_indoor(dem=dem).show()           # the indoor view in metres
```

`dem` takes a raster file such as a GeoTIFF, a list of tiles, or a function `(longitudes, latitudes) -> heights`. pyrosm3d bundles and downloads no terrain data. Reading a raster file needs rasterio, which the `dem` extra installs:

```bash
pip install "pyrosm3d[dem] @ git+https://github.com/pyrosm/pyrosm3D@main"
```

OpenStreetMap holds no depths: a floor that meets no street, such as a metro platform, is placed by its level from the floors that it is joined to, 6 m for each level below the ground floor and 4 m for each level above it, not at its real depth. `pyrosm3d.network_heights(edges, dem)` gives the heights to edges that you have read yourself.

## Documentation

The pages under [docs/](docs/) show the functions on a real building and list their parameters.

## License

BSD 3-Clause. Map data © OpenStreetMap contributors, ODbL.
