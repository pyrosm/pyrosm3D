# Installation

pyrosm3d has no release yet. Install it from GitHub with pip:

```bash
pip install "pyrosm3d @ git+https://github.com/pyrosm/pyrosm3D@main"
```

This also installs its dependencies: geopandas, numpy, pandas, plotly (5.15 or later) and shapely (2.1 or later). Python 3.11 or later is needed.

## pyrosm

pyrosm reads the data that pyrosm3d draws. `read_indoor` needs a pyrosm that reads indoor elements (`get_network(..., indoor_elements=True)`). No pyrosm release has them yet, so install pyrosm from its main branch:

```bash
pip install "pyrosm @ git+https://github.com/pyrosm/pyrosm@main"
```

The command builds pyrosm from source, which needs a C compiler. With a pyrosm that lacks the indoor reads, `read_indoor` raises a `TypeError` that names this command.

The drawing functions do not import pyrosm. `plot_network` takes GeoDataFrames or a graph, and `plot_indoor` and `to_html` take an `IndoorElements` object, whose layers are GeoDataFrames.
