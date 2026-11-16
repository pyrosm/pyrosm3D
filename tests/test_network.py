import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from pyrosm3d import network_heights, plot_network
from pyrosm3d.dem import sample_dem
from pyrosm3d.network import (
    _STYLES,
    _edge_kind,
    _edge_text,
    _edges_by_way,
    _graph_frames,
)


def _traces(figure):
    """``{legend name: trace}`` of a figure."""
    return {trace.name: trace for trace in figure.data}


def test_plot_network_draws_an_indoor_network(helsinki_indoor):
    """Each kind of edge is a legend entry; the lift of node 2039713549 is a vertical
    line from level -2 to 0; a radius keeps what reaches near the center; the route is
    a line, drawn over the edges with markers at its ends, that rises through the lift
    (a step that is not an edge left out, no route without the u and v columns;
    repeated index labels are fine; the same route for edges in another coordinate
    system); polygon and line areas are outlines at the level
    of their JSON tags (the point at the center left out), and entrances markers
    that are hidden until they are picked in the legend, unlike the other kinds;
    stairs, escalators, moving walkways, lifts and platforms each have a colour of
    their own."""
    osm, nodes, edges = helsinki_indoor
    areas = osm.get_data_by_custom_criteria({"railway": ["platform"]}, keep_nodes=False)
    near = dict(center=(24.9415, 60.1712), radius=200)
    point = areas.iloc[:1].assign(geometry=[Point(near["center"])])
    areas = pd.concat([areas, point])
    route = [2039713539, 2039713549, -2039713549001, 2039713561, 1]
    figure = plot_network(edges, nodes, route=route, areas=areas, **near)
    traces = _traces(figure)
    assert {"Escalators", "Stairs", "Lifts", "Platforms", "Route"} <= set(traces)
    assert {"Area outlines", "Station entrances", "Lines across areas"} <= set(traces)
    assert traces["Station entrances"].visible == "legendonly"
    assert traces["Lifts"].visible is None
    lift = traces["Lifts"]
    assert [lift.z[i] for i in range(3)] == [-2.0, 0.0, None]
    route_z = pd.Series(traces["Route"].z)
    steps = [
        list(part.dropna()) for _, part in route_z.groupby(route_z.isna().cumsum())
    ]
    assert [-2.0, 0.0] in steps
    line, ends = traces["Route"], traces["Route ends"]
    points = [p for p in zip(line.x, line.y, line.z) if p[0] is not None]
    assert list(zip(ends.x, ends.y, ends.z)) == [points[0], points[-1]]
    assert ends.legendgroup == line.legendgroup and ends.showlegend is False
    moved = _traces(plot_network(edges.to_crs(3067), route=route, **near))["Route"]
    assert list(moved.z) == list(line.z)
    assert line.line.color == ends.marker.color == "#e8002d"
    assert line.line.dash == "solid" and line.line.width == 10
    assert traces["Platforms"].line.color == "#199e70"
    assert traces["Stairs"].line.color == "#444b55"
    assert traces["Escalators"].line.color == "#c98500"
    kinds = ("stairs", "escalator", "moving_walkway", "lift", "platform")
    assert len({_STYLES[kind][1] for kind in kinds}) == len(kinds)
    names = [trace.name for trace in figure.data]
    assert names.index("Route") > names.index("Platforms")
    area = traces["Area outlines"]
    assert min(z for z in area.z if z is not None) < 0
    assert (0, 0) not in set(zip(area.x, area.y))
    repeated = pd.concat([edges, edges.iloc[:1]]).drop(columns=["u", "v"])
    everything = plot_network(repeated, nodes, route=route)
    assert "Route" not in _traces(everything)
    walkways = _traces(everything)["Walkways at street level"]
    assert len(walkways.x) > len(traces["Walkways at street level"].x)
    xy = np.array([(x, y) for x, y in zip(walkways.x, walkways.y) if x is not None])
    assert abs(xy).max() > 200


def test_plot_network_draws_heights_in_metres(helsinki_centre, helsinki_dem):
    """With a terrain model the centre of Helsinki is drawn at the heights of
    network_heights, on an axis in metres: a lift is a vertical line between the
    heights of its two ends, which the hover texts give; the route runs down it; the
    entrance of node 249350774 is at the network's height on its level (12.7 m, the
    ground is at 15 m) and that of node 2261292460, which the network meets on another
    level only, on the ground. Where the terrain model has no heights, edges and
    entrances are left out."""
    nodes, edges = helsinki_centre
    found = network_heights(edges, helsinki_dem).set_index("id")
    lift, entrance, on_ground = 2039713549, 249350774, 2261292460
    figure = plot_network(edges, nodes, route=[-lift * 1000 - 1, lift], dem=helsinki_dem)
    scene = figure.layout.scene
    assert scene.zaxis.title.text == "height (m)" and scene.aspectratio.z == 0.25
    traces = _traces(figure)
    ends = found.loc[lift, ["u_height", "v_height"]].round(2).tolist()
    assert ends == [-3.94, 4.05]
    lifts = traces["Lifts"]
    assert list(lifts.z[:3]) == ends + [None] and lifts.x[0] == lifts.x[1]
    assert lifts.text[0].endswith("levels -2 → 0<br>-3.9 m")
    assert list(traces["Route"].z) == ends[::-1] + [None]
    assert traces["Route"].text[1] == "route<br>-3.9 m"

    heights = dict(zip(traces["Station entrances"].text, traces["Station entrances"].z))
    end = found[(found["u"] == entrance) & (found["u_level"] == 0)]["u_height"].iloc[0]
    assert heights["entrance %d<br>12.7 m" % entrance] == end
    place = nodes[nodes["id"] == on_ground].geometry.iloc[0]
    ground = sample_dem([place.x], [place.y], helsinki_dem)[0]
    assert heights["entrance %d<br>4.0 m" % on_ground] == ground == 4.0

    def west_only(longitudes, latitudes):
        heights = sample_dem(longitudes, latitudes, helsinki_dem)
        return np.where(longitudes > 24.937, np.nan, heights)

    west = _traces(plot_network(edges, nodes, dem=west_only))
    assert 0 < len(west["Station entrances"].x) < len(heights)
    streets = "Walkways at street level"
    assert 0 < len(west[streets].x) < len(traces[streets].x)
    assert not any(z != z for z in west[streets].z if z is not None)


def test_plot_network_puts_an_entrance_on_its_edge_in_metres():
    """An entrance on level -1 in the middle of a tunnel between two streets at 10 m
    and 14 m, under a hill of 100 m: the tunnel has no level columns and is drawn on
    level -1, so the entrance is at the tunnel's height there, 12 m, not on the hill."""
    from geopandas import GeoDataFrame

    def line(west, east):
        return LineString([(24.94 + west * 1e-3, 60.17), (24.94 + east * 1e-3, 60.17)])

    edges = GeoDataFrame(
        {
            "u": [1, 2, 3, 4],
            "v": [2, 3, 4, 5],
            "tags": [None, '{"tunnel":"yes"}', '{"tunnel":"yes"}', None],
        },
        geometry=[line(-1, 0), line(0, 1), line(1, 2), line(2, 3)],
        crs=4326,
    )
    nodes = GeoDataFrame(
        {"id": [3], "railway": ["subway_entrance"], "level": ["-1"]},
        geometry=[Point(24.941, 60.17)],
        crs=4326,
    )

    def hill(longitudes, latitudes):
        east = (longitudes - 24.94) * 1e3
        return np.where(east < 0.5, 10.0, np.where(east < 1.5, 100.0, 14.0))

    entrances = _traces(plot_network(edges, nodes, dem=hill))["Station entrances"]
    assert list(entrances.z) == pytest.approx([12.0], abs=0.01)
    assert list(entrances.text) == ["entrance 3<br>12.0 m"]


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
    figure = plot_network(graph, center=(24.9415, 60.1712), radius=200, route=route)
    traces = _traces(figure)
    assert {"Escalators", "Lifts", "Platforms", "Station entrances"} <= set(traces)
    n_edges = graph.ecount() if graph_type == "igraph" else graph.number_of_edges()
    merged = _graph_frames(graph)[0]
    assert len(merged) * 2 == n_edges
    assert list(traces["Route"].z)[:7] == [0, 0, None, -1, -1, -1, None]
    drawn = np.array(
        [traces["Route"].x[7:-1], traces["Route"].y[7:-1]], dtype=float
    )
    assert np.hypot(*np.diff(drawn)).sum() == pytest.approx(40.1, abs=0.5)
    assert (
        "Walkways on other levels<br>way 16759161 · footway<br>level -1"
        in traces["Walkways on other levels"].text
    )
    assert {
        "Vilhonkatu<br>way 29498962 · unclassified<br>level 0",
        "Rautatientori<br>way 4247505 · unclassified<br>level 0",
        "Rautatientori<br>way 34732049 · unclassified<br>level 0",
    } <= set(traces["Walkways at street level"].text)
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
    kinds = ["Walkways at street level", "Platforms"]
    traces = _traces(plot_network(graph))
    assert list(traces) == kinds
    assert len(traces["Walkways at street level"].x) == 3
    nx.set_node_attributes(graph, {1: 24.94, 2: 24.941}, "x")
    nx.set_node_attributes(graph, {1: 60.17, 2: 60.17}, "y")
    assert list(_traces(plot_network(graph))) == kinds
    nx.set_node_attributes(graph, {1: "subway_entrance"}, "railway")
    traces = _traces(plot_network(graph, center=(24.94, 60.17), radius=0))
    assert list(traces) == kinds + ["Station entrances"]
    graph.add_edge(2, 3, geometry=LineString([(24.941, 60.17), (24.95, 60.17)]), id=12)
    nx.set_node_attributes(graph, {3: 24.95}, "x")
    nx.set_node_attributes(graph, {3: 60.17}, "y")
    traces = _traces(
        plot_network(graph, center=(24.94, 60.17), radius=0, route=[1, 2, 3])
    )
    assert max(x for x in traces["Walkways at street level"].x if x is not None) < 100
    assert max(x for x in traces["Route"].x if x is not None) > 500
    traces = _traces(plot_network(graph, dem=lambda lons, lats: 100 * (lons - 24.94)))
    assert list(traces["Walkways at street level"].z) == [0, 0.1, None, 0.1, 1.0, None]
    assert list(traces["Platforms"].z) == [0, 0.1, None]
    assert list(traces["Station entrances"].z) == [0]


def test_plot_network_draws_merged_edges_made_by_hand():
    """A networkx graph made by hand, with lists as a simplified graph has them.

    The edge from node 1 to 2 has a value for each of its four segments: a street
    (way 10), two segments of a tunnel on layer -2 (way 11) and a street (way 12). It
    is drawn in three parts with new nodes below every node id, and a route runs along
    them, here against the edge. With a terrain model of 10 m in the west, 14 m in the
    east and a hill of 100 m above the middle of the tunnel, the tunnel runs straight
    from 10 m to 14 m.

    Two edges are kept whole. The stairs from node 2 to 3 climb from level 0 to 1:
    the hover text names both ways and both names. The edge from node 3 to -5 has two
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
    traces = _traces(plot_network(graph, route=[-5, 3, 2, 1]))
    assert set(traces["Walkways at street level"].text) - {None} == {
        "A<br>way 10 · street<br>level 0",
        "A<br>way 12 · street<br>level 0",
        "X;Y;Z<br>way 15 · street<br>level 0",
    }
    assert set(traces["Walkways on other levels"].text) - {None} == {
        "Walkways on other levels<br>way 11 · levels<br>level -2"
    }
    assert set(traces["Stairs"].text) - {None} == {
        "B;C<br>ways 13, 14 · stairs<br>levels 0 → 1"
    }
    along = [0, 0, 0, None, 1, 0.5, 0, None]  # the street and the stairs
    along += [0, 0, None, -2, -2, -2, None, 0, 0, None]  # ways 12, 11 and 10
    assert list(traces["Route"].z) == along

    def hill(longitudes, latitudes):
        east = (longitudes - 24.94) * 1e3
        return np.where(east < 1.2, 10.0, np.where(east < 1.8, 100.0, 14.0))

    in_metres = _traces(plot_network(graph, dem=hill))
    tunnel = in_metres["Walkways on other levels"].z
    assert list(tunnel) == pytest.approx([10, 12, 14, None], abs=0.01)

    bend = LineString([(24.943, 60.17), (24.9415, 60.171), (24.94, 60.17)])
    graph.add_edge(2, 1, geometry=bend, id=16, length=100.0)
    assert _edges_by_way(_graph_frames(graph)[0])[1] == {}
    by_levels = _traces(plot_network(graph, route=[1, 2]))
    assert list(by_levels["Route"].z) == [0, 0, 0, None]

    def south(longitudes, latitudes):
        return np.where(latitudes < 60.1705, hill(longitudes, latitudes), np.nan)

    assert "Route" not in _traces(plot_network(graph, route=[1, 2], dem=south))


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
