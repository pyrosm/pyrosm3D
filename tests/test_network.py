import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from pyrosm3d import plot_network
from pyrosm3d.network import _STYLES, _edge_kind, _graph_frames


def _traces(figure):
    """``{legend name: trace}`` of a figure."""
    return {trace.name: trace for trace in figure.data}


def test_plot_network_draws_an_indoor_network(helsinki_indoor):
    """Each kind of edge is a legend entry; the lift of node 2039713549 is a vertical
    line from level -2 to 0; a radius keeps what reaches near the center; the route is
    a line, drawn over the edges with markers at its ends, that rises through the lift
    (a step that is not an edge left out, no route without the u and v columns;
    repeated index labels are fine); polygon and line areas are outlines at the level
    of their JSON tags (the point at the center left out) and entrances markers;
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


@pytest.mark.parametrize("graph_type", ["networkx", "igraph"])
def test_plot_network_draws_graphs(helsinki_indoor, graph_type):
    """A graph of get_graph(indoor_elements=True) draws the same kinds as its frames,
    each edge of the walking graph once, though the graph has it in both directions."""
    osm, _, _ = helsinki_indoor
    graph = osm.get_graph(
        "walking", graph_type=graph_type, indoor_elements=True, retain_all=True
    )
    traces = _traces(plot_network(graph, center=(24.9415, 60.1712), radius=200))
    assert {"Escalators", "Lifts", "Platforms", "Station entrances"} <= set(traces)
    n_edges = graph.ecount() if graph_type == "igraph" else graph.number_of_edges()
    assert len(_graph_frames(graph)[0]) * 2 == n_edges


def test_plot_network_draws_a_graph_made_by_hand():
    """A networkx graph with line geometries: the two directions of an edge are drawn
    once, a parallel edge of another way too; no entrances without node coordinates or
    entrance nodes; with radius 0 what touches the center is drawn, an entrance there
    too, and a route in full, also along an edge beyond the radius (nodes 2 to 3)."""
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


def test_plot_network_refuses_what_it_cannot_draw():
    """A network without line geometries is refused with a pointer to the frames, a
    network without edges and a radius below 0 too."""
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
