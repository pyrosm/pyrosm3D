# Installation

pyrosm3d has no release yet. Install it from GitHub with pip:

```bash
pip install "pyrosm3d @ git+https://github.com/pyrosm/pyrosm3D@main"
```

This also installs its dependencies: geopandas, numpy, pandas and shapely (2.1 or later). Python 3.11 or later is needed. The views are web pages that load the deck.gl library from the jsDelivr network when they are shown.

## Terrain models

The heights in metres need a terrain model that you supply. Reading one from a raster file, such as a GeoTIFF, needs rasterio, which the `dem` extra installs:

```bash
pip install "pyrosm3d[dem] @ git+https://github.com/pyrosm/pyrosm3D@main"
```

A function that returns the heights of coordinates needs no extra.

## pyrosm

pyrosm reads the data that pyrosm3d draws, and the views are reached through pyrosm: `osm.in3d` is a property of its `OSM` object. No pyrosm release has the property or the read of the indoor elements (`get_indoor_elements`) yet, so install pyrosm from its main branch:

```bash
pip install "pyrosm @ git+https://github.com/pyrosm/pyrosm@main"
```

The command builds pyrosm from source, which needs a C compiler.

The drawing functions do not import pyrosm. `plot_indoor` and `to_html` take the GeoDataFrames that pyrosm reads, and `plot_network` takes GeoDataFrames or a graph.
