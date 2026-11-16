"""The ``in3d`` accessor of ``pyrosm.OSM``: 3D views of what an OSM object reads."""

from pyrosm3d.figure import plot_indoor
from pyrosm3d.network import plot_network
from pyrosm3d.page import to_html


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
        """A plotly Figure of the indoor elements in 3D: the floors of rooms,
        corridors, platforms and walking areas at their levels, walls with door gaps,
        the columns of stairwells and lift shafts, and the walking network.

        Parameters
        ----------
        level : float (optional)
            Draw only what is on this level, without the columns of stairwells and
            lift shafts; by default all levels.

        Returns
        -------
        plotly.graph_objects.Figure
            The figure of :func:`pyrosm3d.plot_indoor`.
        """
        return plot_indoor(**self._indoor_frames(), level=level)

    def to_html(self, path, title="Indoor elements", include_plotlyjs=True):
        """Write a web page with the 3D view of the indoor elements: the figure of
        :meth:`plot_indoor` with a button for each level and the OpenStreetMap tags of
        a clicked element.

        Parameters
        ----------
        path : str or pathlib.Path
            The HTML file to write.
        title : str
            The title of the page.
        include_plotlyjs : bool or "cdn"
            With True (the default) the page holds plotly's JavaScript, so it works
            without a network connection and is about 5 MB larger. With ``"cdn"`` the
            page loads the library from plotly's content delivery network.

        Returns
        -------
        pathlib.Path
            The file written, as :func:`pyrosm3d.to_html` writes it.
        """
        return to_html(
            path=path,
            title=title,
            include_plotlyjs=include_plotlyjs,
            **self._indoor_frames(),
        )

    def plot_network(
        self, network_type="walking", center=None, radius=None, route=None, graph=None
    ):
        """A plotly Figure of the network with its indoor elements in 3D: the edges at
        their levels, with stairs, escalators, lifts and platforms told apart.

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
            A path through the network, drawn as a wide red line with markers at its
            two ends.
        graph : igraph.Graph or networkx.MultiDiGraph (optional)
            A graph of ``get_graph(indoor_elements=True)``, such as the one that the
            ``route`` was found in. It is drawn instead of the network of
            ``network_type``, which is then not read.

        Returns
        -------
        plotly.graph_objects.Figure
            The figure of :func:`pyrosm3d.plot_network`.
        """
        if graph is not None:
            return plot_network(graph, center=center, radius=radius, route=route)
        nodes, edges = self._osm.get_network(
            network_type, nodes=True, indoor_elements=True
        )
        if edges is None:
            raise ValueError(
                "in3d.plot_network found no %s network to draw." % network_type
            )
        return plot_network(edges, nodes, center=center, radius=radius, route=route)
