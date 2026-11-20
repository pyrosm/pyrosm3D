import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from pyrosm3d import plot_network
from pyrosm3d.network import (
    _edge_kind,
    _edge_text,
    _edges_by_way,
    _graph_frames,
)
from test_network_view import _groups, _heights, _texts


@pytest.mark.parametrize("graph_type", ["networkx", "igraph"])
def test_plot_network_draws_graphs(helsinki_indoor, graph_type):
    """A graph of get_graph(indoor_elements=True) draws the same kinds as its frames,
    each edge of the walking graph once, though the graph has it in both directions.

    The graph is simplified, and an edge that joins several ways is drawn way by way.
    The edge from node 1514631272 to 173248856 joins a segment of the footway 16759160
    and two of the footway 16759161, a tunnel on layer -1: a route along it runs at
    street level and then on level -1. The edge from 3929024819 to 189433503 joins
    Vilhonkatu (way 29498962) and Rautatientori (ways 4247505 and 34732049). The edge
    from 946518188 to 946518151 turns a corner between its two ways: its parts are as
    long as the ways' segments are in the graph without simplification, 17.63 m and
    32.02 m.

    The nodes 1369465828 and 1369465823 are joined by two edges, 40.1 m (way 29690379)
    and 63.8 m (way 122595265) long: a route between them is drawn along the shorter.
    The route's step between 173248856 and 1369465828 is no edge and is left out."""
    osm, _, _ = helsinki_indoor
    graph = osm.get_graph(
        "walking", graph_type=graph_type, indoor_elements=True, retain_all=True
    )
    tunnel_edge = (1514631272, 173248856)
    route = [*tunnel_edge, 1369465828, 1369465823]
    view = plot_network(graph, center=(24.9415, 60.1712), radius=200, route=route)
    groups = _groups(view)
    assert {"Escalators", "Lifts", "Platforms", "Station entrances"} <= set(groups)
    n_edges = graph.ecount() if graph_type == "igraph" else graph.number_of_edges()
    merged = _graph_frames(graph)[0]
    assert len(merged) * 2 == n_edges
    runs = _heights(view, "Route")
    assert runs[:2] == [[0, 0], [-6, -6, -6]]
    shorter = np.array(groups["Route"]["items"][2]["p"])[:, :2]
    assert np.hypot(*np.diff(shorter, axis=0).T).sum() == pytest.approx(40.1, abs=0.5)
    assert (
        "Walkways on other levels\nway 16759161 · footway\nlevel -1"
        in _texts(view, "Walkways on other levels")
    )
    assert {
        "Vilhonkatu\nway 29498962 · unclassified\nlevel 0",
        "Rautatientori\nway 4247505 · unclassified\nlevel 0",
        "Rautatientori\nway 34732049 · unclassified\nlevel 0",
    } <= _texts(view, "Walkways at street level")
    edges, chains = _edges_by_way(merged)
    first, between, last = chains[tunnel_edge]
    assert (first, last) == tunnel_edge and between < merged[["u", "v"]].min().min()
    parts = edges[(edges["u"] == between) | (edges["v"] == between)]
    assert parts["id"].tolist() == [16759160, 16759161]
    _, corner, _ = chains[(946518188, 946518151)]
    parts = edges[(edges["u"] == corner) | (edges["v"] == corner)]
    assert parts["id"].tolist() == [81239432, 81239444]
    assert parts["length"].tolist() == pytest.approx([17.63, 32.02], abs=0.01)


def test_plot_network_draws_a_graph_made_by_hand():
    """A networkx graph with line geometries: the two directions of an edge are drawn
    once, a parallel edge of another way too; no entrances without node coordinates or
    entrance nodes; with radius 0 what touches the center is drawn, an entrance there
    too, and a route in full, also along an edge beyond the radius (nodes 2 to 3).
    With a terrain model, here a function, the graph is drawn at its heights."""
    import networkx as nx

    graph = nx.MultiDiGraph()
    line = LineString([(24.94, 60.17), (24.941, 60.17)])
    graph.add_edge(1, 2, geometry=line, id=10)
    graph.add_edge(2, 1, geometry=line.reverse(), id=10)
    graph.add_edge(1, 2, geometry=line, id=11, railway="platform")
    kinds = ["Ground", "Walkways at street level", "Platforms"]
    groups = _groups(plot_network(graph))
    assert list(groups) == kinds
    assert len(groups["Walkways at street level"]["items"]) == 1
    nx.set_node_attributes(graph, {1: 24.94, 2: 24.941}, "x")
    nx.set_node_attributes(graph, {1: 60.17, 2: 60.17}, "y")
    assert list(_groups(plot_network(graph))) == kinds
    nx.set_node_attributes(graph, {1: "subway_entrance"}, "railway")
    groups = _groups(plot_network(graph, center=(24.94, 60.17), radius=0))
    assert list(groups) == kinds + ["Station entrances"]
    graph.add_edge(2, 3, geometry=LineString([(24.941, 60.17), (24.95, 60.17)]), id=12)
    nx.set_node_attributes(graph, {3: 24.95}, "x")
    nx.set_node_attributes(graph, {3: 60.17}, "y")
    view = plot_network(graph, center=(24.94, 60.17), radius=0, route=[1, 2, 3])
    walkways = _groups(view)["Walkways at street level"]["items"]
    assert max(p[0] for item in walkways for p in item["p"]) < 100
    assert max(p[0] for item in _groups(view)["Route"]["items"] for p in item["p"]) > 500
    view = plot_network(graph, dem=lambda lons, lats: 100 * (lons - 24.94))
    assert _heights(view, "Walkways at street level") == [[0, 0.1], [0.1, 1.0]]
    assert _heights(view, "Platforms") == [[0, 0.1]]
    assert [i["c"][2] for i in _groups(view)["Station entrances"]["items"]] == [0]


def test_plot_network_draws_merged_edges_made_by_hand():
    """A networkx graph made by hand, with lists as a simplified graph has them.

    The edge from node 1 to 2 has a value for each of its four segments: a street
    (way 10), two segments of a tunnel on layer -2 (way 11) and a street (way 12). It
    is drawn in three parts with new nodes below every node id, and a route runs along
    them, here against the edge, made of runs where one step goes on where the last
    ended. With a terrain model of 10 m in the west, 14 m in the east and a hill of
    100 m above the middle of the tunnel, the tunnel runs straight from 10 m to 14 m.

    Two edges are kept whole. The stairs from node 2 to 3 climb from level 0 to 1:
    their text names both ways and both names. The edge from node 3 to -5 has two
    segments, the two booleans of ``reversed`` and a list of three names: neither list
    splits it.

    With a second edge of 100 m between nodes 1 and 2, shorter than the split edge's
    line, a route between the two nodes is drawn along that edge, not along the
    parts. The second edge bends north, out of a terrain model that ends there: in
    metres it has no heights, and the route's step is left out, not drawn along the
    longer edge."""
    import networkx as nx

    def line(*east):
        return LineString([(24.94 + step * 1e-3, 60.17) for step in east])

    graph = nx.MultiDiGraph()
    graph.add_edge(
        1,
        2,
        geometry=line(0, 1, 1.5, 2, 3),
        id=[10, 11, 11, 12],
        name=["A", np.nan, None, "A"],
        tunnel=[None, "yes", "yes", np.nan],
        tags=[np.nan, '{"layer":"-2"}', '{"layer":"-2"}', np.nan],
    )
    graph.add_edge(
        2,
        3,
        geometry=line(3, 4, 5),
        id=[13, 14],
        name=["B", "C"],
        tags=['{"handrail":"yes"}', '{"handrail":"no"}'],
        u_level=0.0,
        v_level=1.0,
        vertical="stairs",
    )
    graph.add_edge(
        3,
        -5,
        geometry=line(5, 6, 7),
        id=15,
        reversed=[False, True],
        name=["X", "Y", "Z"],
    )
    edges, chains = _edges_by_way(_graph_frames(graph)[0])
    assert chains == {(1, 2): [1, -6, -7, 2]}
    assert sorted(zip(edges["u"], edges["v"])) == [
        (-7, 2),
        (-6, -7),
        (1, -6),
        (2, 3),
        (3, -5),
    ]
    view = plot_network(graph, route=[-5, 3, 2, 1])
    assert _texts(view, "Walkways at street level") == {
        "A\nway 10 · street\nlevel 0",
        "A\nway 12 · street\nlevel 0",
        "X;Y;Z\nway 15 · street\nlevel 0",
    }
    assert _texts(view, "Walkways on other levels") == {
        "Walkways on other levels\nway 11 · levels\nlevel -2"
    }
    assert _texts(view, "Stairs") == {"B;C\nways 13, 14 · stairs\nlevels 0 → 1"}
    # the street, the stairs and way 12 on, ways 11 and 10
    assert _heights(view, "Route") == [[0, 0, 0], [4, 2, 0, 0], [-12, -12, -12], [0, 0]]

    def hill(longitudes, latitudes):
        east = (longitudes - 24.94) * 1e3
        return np.where(east < 1.2, 10.0, np.where(east < 1.8, 100.0, 14.0))

    tunnel = _heights(plot_network(graph, dem=hill), "Walkways on other levels")
    assert tunnel == [pytest.approx([10, 12, 14], abs=0.05)]

    bend = LineString([(24.943, 60.17), (24.9415, 60.171), (24.94, 60.17)])
    graph.add_edge(2, 1, geometry=bend, id=16, length=100.0)
    assert _edges_by_way(_graph_frames(graph)[0])[1] == {}
    assert _heights(plot_network(graph, route=[1, 2]), "Route") == [[0, 0, 0]]

    def south(longitudes, latitudes):
        return np.where(latitudes < 60.1705, hill(longitudes, latitudes), np.nan)

    assert "Route" not in _groups(plot_network(graph, route=[1, 2], dem=south))


def test_plot_network_refuses_what_it_cannot_draw():
    """A network without line geometries is refused with a pointer to the frames, a
    network without edges and a radius below 0 too; so are areas together with a
    terrain model, and a terrain model without a height for any edge."""
    import networkx as nx
    from geopandas import GeoDataFrame

    class Network:  # stands in for a pandana network
        pass

    with pytest.raises(ValueError, match="pass the frames of get_network"):
        plot_network(Network())
    for empty in (nx.MultiDiGraph(), GeoDataFrame(geometry=[], crs=4326)):
        with pytest.raises(ValueError, match="no edges to draw"):
            plot_network(empty)
    for radius in (-1, np.nan):
        with pytest.raises(ValueError, match="radius must be at least 0"):
            plot_network(Network(), radius=radius)
    line = LineString([(24.94, 60.17), (24.941, 60.17)])
    edges = GeoDataFrame({"u": [1], "v": [2]}, geometry=[line], crs=4326)
    with pytest.raises(ValueError, match="give areas or dem, not both"):
        plot_network(edges, areas=edges, dem=lambda lons, lats: lons)
    with pytest.raises(ValueError, match="found no heights for the edges"):
        plot_network(edges, dem=lambda lons, lats: lons * np.nan)


@pytest.mark.parametrize(
    "tags, vertical, levels, crossing, expected",
    [
        ({"level": "0;1"}, None, (np.nan, np.nan), False, ("multi", 0.0, 0.0)),
        ({"level": "-1"}, None, (np.nan, np.nan), False, ("levels", -1.0, -1.0)),
        ({"tunnel": "yes"}, None, (np.nan, np.nan), False, ("levels", -1.0, -1.0)),
        ({"tunnel": "yes", "layer": "1"}, None, (np.nan,) * 2, False, ("street", 0, 0)),
        ({}, None, (np.nan, -1.0), True, ("crossing", -1.0, -1.0)),
        ({"railway": "platform"}, None, (0.0, 0.0), False, ("platform", 0.0, 0.0)),
        ({}, pd.NA, (0.0, 0.0), False, ("street", 0.0, 0.0)),
        ({}, "stairs", (0.0, 1.0), False, ("stairs", 0.0, 1.0)),
        ({}, "moving_walkway", (-4.0, -3.5), False, ("moving_walkway", -4.0, -3.5)),
        ({"stairs": "yes"}, "escalator", (1.0, 2.0), True, ("escalator", 1.0, 2.0)),
    ],
)
def test_plot_network_edge_kinds(tags, vertical, levels, crossing, expected):
    """An edge's kind and the levels it is drawn at: a walkway tagged with several
    levels flat at the lowest, one with one level at it, an edge without a level at its
    layer below street level (a tunnel at least one below), else at street level, a
    missing end level from the other end; a line across an area by its vertical value
    when it has one; a missing vertical value may be ``pd.NA``."""
    assert _edge_kind(tags, vertical, *levels, crossing) == expected


@pytest.mark.parametrize(
    "tags, kind, levels, expected",
    [
        (
            {"name": "Asema", "highway": "footway"},
            "levels",
            (-1.0, -1.0),
            "Asema<br>way 7 · footway<br>level -1",
        ),
        (
            {"highway": "steps"},
            "stairs",
            (0.0, 1.5),
            "Stairs<br>way 7 · steps<br>levels 0 → 1.5",
        ),
        (
            {},
            "crossing",
            (2.0, 2.0),
            "Lines across areas<br>way 7 · crossing<br>level 2",
        ),
    ],
)
def test_plot_network_edge_text(tags, kind, levels, expected):
    """The hover text of an edge names it (its name, else the legend entry of its
    kind), its element with its highway value (else its kind) and the levels it is
    drawn at: one level, or the levels of its two ends."""

    class Row:
        id = 7

    assert _edge_text(Row, tags, kind, *levels) == expected
