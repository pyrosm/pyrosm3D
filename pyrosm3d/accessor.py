"""The ``in3d`` accessor of ``pyrosm.OSM``: 3D views of what an OSM object reads."""

from pyrosm3d.heights import network_heights
from pyrosm3d.indoor_view import plot_indoor, to_html
from pyrosm3d.network import plot_network
from pyrosm3d.view import DECK_GL


class In3D:
    """3D views of the data of a ``pyrosm.OSM`` object, reached as ``osm.in3d``. Each
    view reads what it draws with the object's own reads, within its
    ``bounding_box``::

        osm = pyrosm.OSM("place.osm.pbf")
        osm.in3d.plot_indoor().show()

    Parameters
    ----------
    osm : pyrosm.OSM
        The reader of a PBF file.
    """

    def __init__(self, osm):
        self._osm = osm

    def _indoor_frames(self):
        """The frames of the indoor views, from the reads of the OSM object: its indoor
        elements with the walking areas, the walking network with indoor elements and
        walking areas, and the buildings; as the arguments of
        :func:`pyrosm3d.plot_indoor`."""
        osm = self._osm
        nodes, edges = osm.get_network(
            "walking", nodes=True, indoor_elements=True, walking_areas=True
        )
        elements = osm.get_indoor_elements(walking_areas=True)
        buildings = osm.get_buildings()
        return dict(elements=elements, edges=edges, nodes=nodes, buildings=buildings)

    def plot_indoor(self, level=None):
        """A 3D view of the indoor elements: the floors of rooms, corridors, platforms
        and walking areas at their levels, walls with door gaps, the columns of
        stairwells and lift shafts, and the walking network.

        Parameters
        ----------
        level : float (optional)
            The level that the indoor view opens on; by default all levels.

        Returns
        -------
        pyrosm3d.View
            The view of :func:`pyrosm3d.plot_indoor`.
        """
        return plot_indoor(**self._indoor_frames(), level=level)

    def to_html(self, path, title="Indoor elements", deck_gl=DECK_GL):
        """Write the 3D view of the indoor elements of :meth:`plot_indoor` as a web
        page, in which the level picker names the number of areas on each level and a
        tapped element shows its OpenStreetMap tags.

        Parameters
        ----------
        path : str or pathlib.Path
            The HTML file to write.
        title : str
            The title of the page.
        deck_gl : str
            Where the page loads the deck.gl library from (see
            :meth:`pyrosm3d.View.to_html`).

        Returns
        -------
        pathlib.Path
            The file written, as :func:`pyrosm3d.to_html` writes it.
        """
        return to_html(path=path, title=title, deck_gl=deck_gl, **self._indoor_frames())

    def _network(self, network_type, **read_options):
        """The nodes and edges of ``get_network(network_type, nodes=True,
        indoor_elements=True)`` of the OSM object, with its other ``read_options``; a
        ValueError when the read finds no network of the type."""
        nodes, edges = self._osm.get_network(
            network_type, nodes=True, indoor_elements=True, **read_options
        )
        if edges is None:
            raise ValueError("in3d found no %s network." % network_type)
        return nodes, edges

    def get_network(self, dem, network_type="walking", **read_options):
        """The nodes and edges of the network with its indoor elements, the edges
        with heights in metres from a terrain model: streets on the terrain, floors
        placed from the streets that they meet (see
        :func:`pyrosm3d.network_heights`).

        Parameters
        ----------
        dem : str or pathlib.Path, a sequence of them, or a function
            The terrain model: a raster file of heights such as a GeoTIFF (reading one
            needs ``pip install "pyrosm3d[dem]"``), several tiles of one, or a function
            ``(longitudes, latitudes) -> heights``.
        network_type : str
            The network that is read: ``get_network(network_type, nodes=True,
            indoor_elements=True)``, so ``"walking"``, ``"all"`` or ``"all_public"``.
        **read_options
            Other arguments of ``pyrosm.OSM.get_network``, such as
            ``walking_areas=True`` or ``extra_attributes``.

        Returns
        -------
        (GeoDataFrame, GeoDataFrame)
            The nodes as they were read, and the edges with the columns ``u_height``
            and ``v_height``, the height at each end of an edge, and with lines that
            have a height at every vertex. Where the terrain model has no height, the
            height of an end is NaN and a line with such a vertex stays flat.
        """
        nodes, edges = self._network(network_type, **read_options)
        return nodes, network_heights(edges, dem)

    def plot_network(
        self,
        network_type="walking",
        center=None,
        radius=None,
        route=None,
        graph=None,
        dem=None,
    ):
        """A 3D view of the network with its indoor elements: the edges at their levels,
        with stairs, escalators, lifts and platforms told apart.

        Parameters
        ----------
        network_type : str
            The network that is read and drawn: ``get_network(network_type,
            nodes=True, indoor_elements=True)``, so ``"walking"``, ``"all"`` or
            ``"all_public"``.
        center : (lon, lat) or shapely Point (optional)
            The middle of the view; by default the middle of the edges.
        radius : float (optional)
            Draw only the edges that reach within this many metres of ``center``, and
            the station entrances within it; the ``route`` is drawn in full.
        route : list of node ids (optional)
            A path through the network, drawn as a wide red line with points at its
            two ends; the view starts over it.
        graph : igraph.Graph or networkx.MultiDiGraph (optional)
            A graph of ``get_graph(indoor_elements=True)``, such as the one that the
            ``route`` was found in. It is drawn instead of the network of
            ``network_type``, which is then not read.
        dem : str or pathlib.Path, a sequence of them, or a function (optional)
            A terrain model, as :meth:`get_network` takes it. The network is then
            drawn at heights in metres, not at its levels.

        Returns
        -------
        pyrosm3d.View
            The view of :func:`pyrosm3d.plot_network`.
        """
        view = dict(center=center, radius=radius, route=route, dem=dem)
        if graph is not None:
            return plot_network(graph, **view)
        nodes, edges = self._network(network_type)
        return plot_network(edges, nodes, **view)
