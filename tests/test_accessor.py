import networkx as nx
import pytest

from pyrosm3d import In3D, plot_indoor, plot_network


def _summary(figure):
    """The name, the levels and the number of points of each trace of a figure."""
    return [(trace.name, trace.meta, len(trace.x)) for trace in figure.data]


def test_in3d_draws_the_indoor_elements_of_its_osm_object(
    maunula_osm, maunula, tmp_path
):
    """The accessor reads the layers of its OSM object and draws them as plot_indoor
    and to_html do: all levels, one level, and the web page with a button for each
    level."""
    in3d = In3D(maunula_osm)
    assert _summary(in3d.plot_indoor()) == _summary(plot_indoor(maunula))
    one_level = in3d.plot_indoor(level=1)
    assert _summary(one_level) == _summary(plot_indoor(maunula, level=1))
    assert all(1 in trace.meta["levels"] for trace in one_level.data)

    path = in3d.to_html(
        tmp_path / "maunula.html", title="Maunula-talo", include_plotlyjs="cdn"
    )
    page = path.read_text(encoding="utf-8")
    assert path == tmp_path / "maunula.html" and "<title>Maunula-talo</title>" in page
    assert '"levels": [0.0, 1.0, 2.0]' in page


def test_in3d_draws_the_network_of_its_osm_object(maunula_osm):
    """plot_network reads the network of the given type with its indoor elements and
    draws it, here near a center; with a graph it draws the graph and a route found in
    it."""
    in3d = In3D(maunula_osm)
    near = dict(center=(24.9331, 60.2311), radius=60)
    for network_type in ("walking", "all"):
        nodes, edges = maunula_osm.get_network(
            network_type, nodes=True, indoor_elements=True
        )
        figure = in3d.plot_network(network_type, **near)
        assert _summary(figure) == _summary(plot_network(edges, nodes, **near))
        assert "Stairs" in {trace.name for trace in figure.data}

    graph = maunula_osm.get_graph(
        "walking", graph_type="networkx", indoor_elements=True
    )
    stairs = [(u, v) for u, v, data in graph.edges(data=True) if data.get("vertical")]
    route = nx.shortest_path(graph, stairs[0][0], stairs[0][1], weight="length")
    drawn = in3d.plot_network(graph=graph, route=route)
    assert _summary(drawn) == _summary(plot_network(graph, route=route))
    assert "Route" in {trace.name for trace in drawn.data}


def test_in3d_plot_network_without_a_network():
    """Where the read finds no network of the type, there is nothing to draw."""

    class NoNetwork:
        def get_network(self, network_type, nodes, indoor_elements):
            return None, None

    with pytest.raises(ValueError, match="found no driving network to draw"):
        In3D(NoNetwork()).plot_network("driving")
