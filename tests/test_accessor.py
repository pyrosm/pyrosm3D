import networkx as nx
import pytest

from pyrosm3d import In3D, network_heights, plot_network
from pyrosm3d.indoor_view import layers_view


def _slope(longitudes, latitudes):
    """A terrain that rises 1 m for each 0.0001 degrees north of 60.23 N."""
    return (latitudes - 60.23) * 1e4



def test_in3d_draws_the_indoor_elements_of_its_osm_object(
    maunula_osm, maunula, tmp_path
):
    """The accessor reads the layers of its OSM object and draws them as plot_indoor
    and to_html do: all levels, one level, and the web page with a button for each
    level."""
    in3d = In3D(maunula_osm)
    assert in3d.plot_indoor().data == layers_view(maunula).data
    assert in3d.plot_indoor(level=1).data == layers_view(maunula, level=1).data

    path = in3d.to_html(tmp_path / "maunula.html", title="Maunula-talo")
    page = path.read_text(encoding="utf-8")
    assert path == tmp_path / "maunula.html" and "<title>Maunula-talo</title>" in page
    assert '"levels":[[0.0,0.0,7],' in page


@pytest.mark.parametrize("dem", [None, _slope])
def test_in3d_draws_the_network_of_its_osm_object(maunula_osm, dem):
    """plot_network reads the network of the given type with its indoor elements and
    draws it, here near a center; with a graph it draws the graph and a route found in
    it; with a terrain model it draws either at heights in metres."""
    in3d = In3D(maunula_osm)
    near = dict(center=(24.9331, 60.2311), radius=60, dem=dem)
    for network_type in ("walking", "all"):
        nodes, edges = maunula_osm.get_network(
            network_type, nodes=True, indoor_elements=True
        )
        view = in3d.plot_network(network_type, **near)
        assert view.data == plot_network(edges, nodes, **near).data
        assert "Stairs" in {group["name"] for group in view.data["groups"]}

    graph = maunula_osm.get_graph(
        "walking", graph_type="networkx", indoor_elements=True
    )
    stairs = [(u, v) for u, v, data in graph.edges(data=True) if data.get("vertical")]
    route = nx.shortest_path(graph, stairs[0][0], stairs[0][1], weight="length")
    drawn = in3d.plot_network(graph=graph, route=route, dem=dem)
    assert drawn.data == plot_network(graph, route=route, dem=dem).data
    groups = {group["name"]: group for group in drawn.data["groups"]}
    assert "Route" in groups
    assert all(("m" in item) == (dem is not None) for item in groups["Stairs"]["items"])


def test_in3d_reads_the_network_with_heights(maunula_osm):
    """get_network reads the network of the given type with its indoor elements and
    the other options of the read, and gives its edges the heights of
    network_heights."""
    read = dict(network_type="all", walking_areas=True)
    nodes, edges = In3D(maunula_osm).get_network(_slope, **read)
    plain_nodes, plain_edges = maunula_osm.get_network(
        nodes=True, indoor_elements=True, **read
    )
    expected = network_heights(plain_edges, _slope)
    assert nodes.equals(plain_nodes) and len(edges) == len(plain_edges)
    assert edges[["u_height", "v_height"]].equals(expected[["u_height", "v_height"]])
    assert edges.geometry.has_z.all() and edges["walking_area"].any()


def test_in3d_without_a_network():
    """Where the read finds no network of the type, there is nothing to draw or to
    give heights."""

    class NoNetwork:
        def get_network(self, network_type, nodes, indoor_elements):
            return None, None

    in3d = In3D(NoNetwork())
    for read in (in3d.plot_network, lambda kind: in3d.get_network(_slope, kind)):
        with pytest.raises(ValueError, match="in3d found no driving network"):
            read("driving")
