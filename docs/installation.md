# Installation

pyrosm3d has no release yet. Install it from GitHub with pip:

```bash
pip install "pyrosm3d @ git+https://github.com/pyrosm/pyrosm3D@main"
```

This also installs its dependencies: geopandas, numpy, pandas, plotly (5.15 or later) and shapely (2.1 or later). Python 3.11 or later is needed.

## pyrosm

pyrosm reads the data that pyrosm3d draws, and the views are reached through pyrosm: `osm.in3d` is a property of its `OSM` object. No pyrosm release has the property or the read of the indoor elements (`get_indoor_elements`) yet, so install pyrosm from its main branch:

```bash
pip install "pyrosm @ git+https://github.com/pyrosm/pyrosm@main"
```

The command builds pyrosm from source, which needs a C compiler.

The drawing functions do not import pyrosm. `plot_network` takes GeoDataFrames or a graph, and `plot_indoor` and `to_html` take an `IndoorElements` object, which `indoor_layers` makes of frames read with pyrosm.
