# API reference

## The accessor of pyrosm

`osm.in3d`, on a `pyrosm.OSM` object, is an `In3D` for that object.

```{eval-rst}
.. autoclass:: pyrosm3d.In3D
   :members:
```

## Drawing frames

The functions draw frames that were read with pyrosm, also after you have changed them.

```{eval-rst}
.. autofunction:: pyrosm3d.plot_indoor

.. autofunction:: pyrosm3d.to_html

.. autofunction:: pyrosm3d.plot_network
```

## Figures on touch screens

The figures that the functions above return are plotly figures of this class.

```{eval-rst}
.. autoclass:: pyrosm3d.touch.TouchFigure
```

## Heights in metres

```{eval-rst}
.. automodule:: pyrosm3d.heights

.. autofunction:: pyrosm3d.network_heights

.. autofunction:: pyrosm3d.dem.sample_dem
```
