import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString

from pyrosm3d import network_heights
from pyrosm3d.dem import sample_dem
from pyrosm3d.network import _STYLES, network_view


def _groups(view):
    """``{name: group}`` of the data of a view."""
    return {group["name"]: group for group in view.data["groups"]}


def _heights(view, name):
    """The heights of the points of each item of the group ``name``, item by item."""
    return [[point[2] for point in item["p"]] for item in _groups(view)[name]["items"]]


def test_network_view_draws_an_indoor_network(helsinki_indoor):
    """Each kind of edge is a group of lines; the lift of node 2039713549 is a
    vertical line from level -2, 12 m below the ground floor (6 m a level below it),
    to level 0; a radius keeps what reaches near the center, where the view starts,
    over a flat ground under street level, unless there is a route, which the view
    starts over; the route is a line drawn over what is in front of it, with points at
    its ends, that rises through the lift (a step that is not an edge left out, no
    route without the u and v columns; repeated index labels are fine; the same route
    for edges in another coordinate system); the lines across areas are off at the
    start, unlike the other kinds; stairs, escalators, moving walkways, lifts and
    platforms each have a colour of their own."""
    osm, nodes, edges = helsinki_indoor
    near = dict(center=(24.9415, 60.1712), radius=200)
    route = [2039713539, 2039713549, -2039713549001, 2039713561, 1]
    view = network_view(edges, nodes, route=route, **near)
    groups = _groups(view)
    assert {"Escalators", "Stairs", "Lifts", "Platforms", "Route"} <= set(groups)
    assert groups["Lines across areas"]["visible"] is False
    assert groups["Lifts"]["visible"] is True
    assert _heights(view, "Lifts")[0] == [-12.0, 0.0]
    lift = groups["Lifts"]["items"][0]["p"]
    assert lift[0][:2] == lift[1][:2]
    route_xy = np.array([p[:2] for item in groups["Route"]["items"] for p in item["p"]])
    middle = (route_xy.min(axis=0) + route_xy.max(axis=0)) / 2
    assert view.data["view"]["target"][:2] == pytest.approx(middle, abs=0.06)
    assert view.data["view"]["rotationOrbit"] == 20 and view.data["mode"] == "solid"
    centred = network_view(edges, nodes, **near).data
    assert centred["view"]["target"] == [0.0, 0.0, 0.0] and centred["fit"] == [420.0] * 2
    assert centred["view"]["rotationOrbit"] == 0
    ground = groups["Ground"]["grid"]
    assert ground["z"] == [-0.4] * 4 and ground["t"] == [0.0] * 4
    climbs = [heights for heights in _heights(view, "Route")]
    assert any([-12.0, 0.0] == run[i : i + 2] for run in climbs for i in range(len(run)))
    line, ends = groups["Route"], groups["Route start and end"]
    paths = [item["p"] for item in line["items"]]
    assert [item["c"] for item in ends["items"]] == [paths[0][0], paths[-1][-1]]
    assert line["always"] and line["rounded"]
    moved = network_view(edges.to_crs(3067), route=route, **near)
    assert _heights(moved, "Route") == _heights(view, "Route")
    assert line["colour"] == ends["colour"] == "#e8002d"
    assert groups["Platforms"]["colour"] == "#199e70"
    assert groups["Stairs"]["colour"] == "#444b55"
    assert groups["Escalators"]["colour"] == "#c98500"
    kinds = ("stairs", "escalator", "moving_walkway", "lift", "platform")
    assert len({_STYLES[kind][1] for kind in kinds}) == len(kinds)
    names = list(groups)
    assert names.index("Route") > names.index("Platforms")
    repeated = pd.concat([edges, edges.iloc[:1]]).drop(columns=["u", "v"])
    everything = _groups(network_view(repeated, nodes, route=route))
    assert "Route" not in everything
    walkways = everything["Walkways at street level"]["items"]
    assert len(walkways) > len(groups["Walkways at street level"]["items"])
    assert max(abs(c) for item in walkways for p in item["p"] for c in p[:2]) > 200


def test_network_view_draws_heights_in_metres(helsinki_centre, helsinki_dem):
    """With a terrain model the centre of Helsinki is drawn at the heights of
    network_heights: a lift from level -2 to the ground floor is a vertical line
    between the heights of its two ends, 12 m apart, which a tap on it shows; the
    route runs down it. Where the terrain model has no heights, edges are left out. No
    flat ground is drawn."""
    nodes, edges = helsinki_centre
    found = network_heights(edges, helsinki_dem).set_index("id")
    lift = 2039713549
    view = network_view(edges, nodes, route=[-lift * 1000 - 1, lift], dem=helsinki_dem)
    groups = _groups(view)
    assert "Ground" not in groups
    ends = found.loc[lift, ["u_height", "v_height"]].round(2).tolist()
    assert ends == [-7.89, 4.09]
    item = groups["Lifts"]["items"][0]
    assert _heights(view, "Lifts")[0] == [-7.9, 4.1] and item["m"] == [-7.9, 4.1]
    assert item["p"][0][:2] == item["p"][1][:2] and (item["a"], item["c"]) == (-2, 0)
    assert _heights(view, "Route") == [[4.1, -7.9]]


    def west_only(longitudes, latitudes):
        heights = sample_dem(longitudes, latitudes, helsinki_dem)
        return np.where(longitudes > 24.937, np.nan, heights)

    west = _groups(network_view(edges, nodes, dem=west_only))
    streets = "Walkways at street level"
    assert 0 < len(west[streets]["items"]) < len(groups[streets]["items"])
    assert all(p[2] == p[2] for item in west[streets]["items"] for p in item["p"])


def test_network_view_draws_a_tunnel():
    """A tunnel without level columns is drawn on level -1, 6 m below the ground
    floor, and below ground; a view that no edge reaches holds only the ground at its
    center."""
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
    by_levels = network_view(edges.iloc[1:3])
    tunnel = _groups(by_levels)["Walkways on other levels"]["items"]
    assert [[p[2] for p in item["p"]] for item in tunnel] == [[-6.0, -6.0]] * 2
    assert all(item["b"] == 1 for item in tunnel)
    nothing = network_view(edges, center=(25.0, 60.17), radius=10)
    assert list(_groups(nothing)) == ["Ground"]
    assert nothing.data["view"]["target"] == [0.0, 0.0, 0.0]


def test_network_view_marks_a_whole_merged_edge_below_ground():
    """An edge of a simplified graph that is kept whole, as one that climbs from level
    to level is, has its own text naming both its ways, and is marked below ground
    like the others: here stairs from level -2 to level -1, 12 m and 6 m under street
    level."""
    import networkx as nx

    graph = nx.MultiDiGraph()
    line = LineString([(24.94, 60.17), (24.941, 60.17), (24.942, 60.17)])
    graph.add_edge(1, 2, geometry=line, id=[13, 14], name=["B", "C"],
                   u_level=-2.0, v_level=-1.0, vertical="stairs")
    item = _groups(network_view(graph))["Stairs"]["items"][0]
    assert item["t"] == "B;C\nways 13, 14 · stairs\nlevels -2 → -1" and item["b"] == 1


def test_network_view_keeps_edges_without_ids_apart():
    """Edges without an id, here missing in different ways, that go on from each other
    stay lines of their own, each with a text of its own and no id, so the page can
    hold them; an infinite radius draws everything, as no radius does."""
    from geopandas import GeoDataFrame

    lines = [
        LineString([(24.94, 60.17), (24.941, 60.17)]),
        LineString([(24.941, 60.17), (24.942, 60.17)]),
        LineString([(24.942, 60.17), (24.943, 60.17)]),
    ]
    edges = GeoDataFrame(
        {"name": ["A", "B", "C"], "id": [np.nan, pd.NA, None]},
        geometry=lines,
        crs=4326,
    )
    view = network_view(edges)
    items = _groups(view)["Walkways at street level"]["items"]
    assert [item["t"] for item in items] == [
        "A\nstreet\nlevel 0", "B\nstreet\nlevel 0", "C\nstreet\nlevel 0"
    ]
    assert not any("w" in item for item in items) and view.to_html()
    view = network_view(edges.drop(columns="id"))
    endless = network_view(edges, radius=float("inf")).data
    assert endless["fit"] == view.data["fit"] and endless["groups"] == view.data["groups"]
