import numpy as np
import pandas as pd
import pytest
import shapely
from geopandas import GeoDataFrame
from shapely.geometry import LineString, Point

from pyrosm3d import network_heights, plot_network
from pyrosm3d.dem import sample_dem
from pyrosm3d.network import _STYLES, _terrain_ground


def _groups(view):
    """``{name: group}`` of the data of a view."""
    return {group["name"]: group for group in view.data["groups"]}


def _heights(view, name):
    """The heights of the points of each item of the group ``name``, item by item."""
    return [[point[2] for point in item["p"]] for item in _groups(view)[name]["items"]]


def _texts(view, name):
    """The texts that the page shows for the items of the group ``name``: an item's
    own text, else, for a line of the network, its name, its element with its highway
    value and its levels (the tables of the view hold the names and values)."""
    tables, found = view.data["tables"], set()
    for item in _groups(view)[name]["items"]:
        if "t" in item:
            found.add(item["t"])
            continue
        element = ("way ", "relation ", "node ")[item.get("e", 0)]
        highway = tables["highways"][item["h"]]
        levels = "level %g" % item["a"]
        if "c" in item:
            levels = "levels %g → %g" % (item["a"], item["c"])
        lines = [tables["names"][item["n"]], "%s%s · %s" % (element, item["w"], highway)]
        found.add("\n".join(lines + [levels]))
    return found


def test_plot_network_draws_an_indoor_network(helsinki_indoor):
    """Each kind of edge is a group of lines; the lift of node 2039713549 is a
    vertical line from level -2, 12 m below the ground floor (6 m a level below it),
    to level 0; a radius keeps what reaches near the center, where the view starts,
    over a flat ground under street level, unless there is a route, which the view
    starts over; the route is a line drawn over what is in front of it, with points at
    its ends, that rises through the lift (a step that is
    not an edge left out, no route without the u and v columns; repeated index labels
    are fine; the same route for edges in another coordinate system); polygon and line
    areas are outlines at the level of their JSON tags (the point at the center left
    out), and entrances points that are off at the start, unlike the other kinds;
    stairs, escalators, moving walkways, lifts and platforms each have a colour of
    their own."""
    osm, nodes, edges = helsinki_indoor
    areas = osm.get_data_by_custom_criteria({"railway": ["platform"]}, keep_nodes=False)
    near = dict(center=(24.9415, 60.1712), radius=200)
    point = areas.iloc[:1].assign(geometry=[Point(near["center"])])
    areas = pd.concat([areas, point])
    route = [2039713539, 2039713549, -2039713549001, 2039713561, 1]
    view = plot_network(edges, nodes, route=route, areas=areas, **near)
    groups = _groups(view)
    assert {"Escalators", "Stairs", "Lifts", "Platforms", "Route"} <= set(groups)
    assert {"Area outlines", "Station entrances", "Lines across areas"} <= set(groups)
    assert groups["Station entrances"]["visible"] is False
    assert groups["Lifts"]["visible"] is True
    assert _heights(view, "Lifts")[0] == [-12.0, 0.0]
    lift = groups["Lifts"]["items"][0]["p"]
    assert lift[0][:2] == lift[1][:2]
    route_xy = np.array([p[:2] for item in groups["Route"]["items"] for p in item["p"]])
    middle = (route_xy.min(axis=0) + route_xy.max(axis=0)) / 2
    assert view.data["view"]["target"][:2] == pytest.approx(middle, abs=0.06)
    assert view.data["view"]["rotationOrbit"] == 20 and view.data["mode"] == "solid"
    centred = plot_network(edges, nodes, **near).data
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
    moved = plot_network(edges.to_crs(3067), route=route, **near)
    assert _heights(moved, "Route") == _heights(view, "Route")
    assert line["colour"] == ends["colour"] == "#e8002d"
    assert groups["Platforms"]["colour"] == "#199e70"
    assert groups["Stairs"]["colour"] == "#444b55"
    assert groups["Escalators"]["colour"] == "#c98500"
    kinds = ("stairs", "escalator", "moving_walkway", "lift", "platform")
    assert len({_STYLES[kind][1] for kind in kinds}) == len(kinds)
    names = list(groups)
    assert names.index("Route") > names.index("Platforms")
    area = [p for item in groups["Area outlines"]["items"] for p in item["p"]]
    assert min(p[2] for p in area) < 0 and [0.0, 0.0] not in [p[:2] for p in area]
    repeated = pd.concat([edges, edges.iloc[:1]]).drop(columns=["u", "v"])
    everything = _groups(plot_network(repeated, nodes, route=route))
    assert "Route" not in everything
    walkways = everything["Walkways at street level"]["items"]
    assert len(walkways) > len(groups["Walkways at street level"]["items"])
    assert max(abs(c) for item in walkways for p in item["p"] for c in p[:2]) > 200


def test_plot_network_draws_heights_in_metres(helsinki_centre, helsinki_dem):
    """With a terrain model the centre of Helsinki is drawn at the heights of
    network_heights: a lift from level -2 to the ground floor is a vertical line
    between the heights of its two ends, 12 m apart, which a tap on it shows; the
    route runs down it; the entrance of node 249350774 is at the network's height on
    its level (12.7 m, the ground is at 15 m) and that of node 2261292460, which the
    network meets on another level only, on the ground. Where the terrain model has no
    heights, edges and entrances are left out. No flat ground is drawn."""
    nodes, edges = helsinki_centre
    found = network_heights(edges, helsinki_dem).set_index("id")
    lift, entrance, on_ground = 2039713549, 249350774, 2261292460
    view = plot_network(edges, nodes, route=[-lift * 1000 - 1, lift], dem=helsinki_dem)
    groups = _groups(view)
    grid = groups["Ground"]["grid"]
    drawn, terrain = (np.array(grid[key], dtype=float) for key in ("z", "t"))
    assert grid["step"] >= 10.0 and np.isfinite(terrain).all()
    assert (drawn <= terrain - 0.4 + 1e-6).all()  # under the terrain, lower near lines
    ends = found.loc[lift, ["u_height", "v_height"]].round(2).tolist()
    assert ends == [-7.89, 4.09]
    item = groups["Lifts"]["items"][0]
    assert _heights(view, "Lifts")[0] == [-7.9, 4.1] and item["m"] == [-7.9, 4.1]
    assert item["p"][0][:2] == item["p"][1][:2] and (item["a"], item["c"]) == (-2, 0)
    assert _heights(view, "Route") == [[4.1, -7.9]]

    texts = {i["t"]: i["c"][2] for i in groups["Station entrances"]["items"]}
    end = found[(found["u"] == entrance) & (found["u_level"] == 0)]["u_height"].iloc[0]
    assert texts["entrance %d\n12.7 m" % entrance] == round(end, 1)
    place = nodes[nodes["id"] == on_ground].geometry.iloc[0]
    ground = sample_dem([place.x], [place.y], helsinki_dem)[0]
    assert texts["entrance %d\n4.0 m" % on_ground] == ground == 4.0

    def west_only(longitudes, latitudes):
        heights = sample_dem(longitudes, latitudes, helsinki_dem)
        return np.where(longitudes > 24.937, np.nan, heights)

    west = _groups(plot_network(edges, nodes, dem=west_only))
    assert 0 < len(west["Station entrances"]["items"]) < len(texts)
    streets = "Walkways at street level"
    assert 0 < len(west[streets]["items"]) < len(groups[streets]["items"])
    assert all(p[2] == p[2] for item in west[streets]["items"] for p in item["p"])


def test_plot_network_draws_a_tunnel_with_an_entrance():
    """An entrance on level -1 in the middle of a tunnel between two streets at 10 m
    and 14 m, under a hill of 100 m: the tunnel has no level columns and is drawn on
    level -1, so the entrance is at the tunnel's height there, 12 m, not on the hill.
    By levels, the tunnel alone and its entrance lie 6 m below the ground floor, below
    ground; a view that no edge reaches holds only the ground at its center."""
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

    entrances = _groups(plot_network(edges, nodes, dem=hill))["Station entrances"]
    assert [item["c"][2] for item in entrances["items"]] == pytest.approx([12.0])
    assert [item["t"] for item in entrances["items"]] == ["entrance 3\n12.0 m"]

    by_levels = plot_network(edges.iloc[1:3], nodes)
    tunnel = _groups(by_levels)["Walkways on other levels"]["items"]
    assert [[p[2] for p in item["p"]] for item in tunnel] == [[-6.0, -6.0]] * 2
    assert all(item["b"] == 1 for item in tunnel)
    assert _groups(by_levels)["Station entrances"]["items"][0]["c"][2] == -6.0
    nothing = plot_network(edges, center=(25.0, 60.17), radius=10)
    assert list(_groups(nothing)) == ["Ground"]
    assert nothing.data["view"]["target"] == [0.0, 0.0, 0.0]


def test_plot_network_marks_a_whole_merged_edge_below_ground():
    """An edge of a simplified graph that is kept whole, as one that climbs from level
    to level is, has its own text naming both its ways, and is marked below ground
    like the others: here stairs from level -2 to level -1, 12 m and 6 m under street
    level."""
    import networkx as nx

    graph = nx.MultiDiGraph()
    line = LineString([(24.94, 60.17), (24.941, 60.17), (24.942, 60.17)])
    graph.add_edge(1, 2, geometry=line, id=[13, 14], name=["B", "C"],
                   u_level=-2.0, v_level=-1.0, vertical="stairs")
    item = _groups(plot_network(graph))["Stairs"]["items"][0]
    assert item["t"] == "B;C\nways 13, 14 · stairs\nlevels -2 → -1" and item["b"] == 1


def test_plot_network_keeps_edges_without_ids_apart():
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
    view = plot_network(edges)
    items = _groups(view)["Walkways at street level"]["items"]
    assert [item["t"] for item in items] == [
        "A\nstreet\nlevel 0", "B\nstreet\nlevel 0", "C\nstreet\nlevel 0"
    ]
    assert not any("w" in item for item in items) and view.to_html()
    view = plot_network(edges.drop(columns="id"))
    endless = plot_network(edges, radius=float("inf")).data
    assert endless["fit"] == view.data["fit"] and endless["groups"] == view.data["groups"]


@pytest.mark.parametrize("radius, dem", [(None, None), (60, None), (None, "slope")])
def test_plot_network_draws_buildings(maunula_osm, radius, dem):
    """The buildings stand on the ground with the network: on the flat ground or on
    the terrain, which reaches under them; with a radius only those that reach within
    it. A building part with a height is drawn from under the ground, and the start
    view stays that of the network."""
    nodes, edges = maunula_osm.get_network("walking", nodes=True, indoor_elements=True)
    buildings = maunula_osm.get_buildings()
    outline = buildings.geometry.iloc[0]
    part = outline.centroid.buffer(0.00003)
    tags = {"building:part": ["yes"], "height": ["30"]}
    parts = GeoDataFrame(tags, geometry=[part], crs=4326)
    slope = (lambda lon, lat: (lat - 60.23) * 1e4) if dem else None
    near = dict(center=(24.9331, 60.2311), radius=radius, dem=slope)
    view = plot_network(edges, nodes, buildings=buildings, building_parts=parts, **near)
    plain = plot_network(edges, nodes, **near)
    assert (view.data["view"], view.data["fit"]) == (plain.data["view"], plain.data["fit"])
    groups = _groups(view)
    blocks = [
        item
        for group in groups.values()
        if group["kind"] == "buildings"
        for item in group["items"]
    ]
    assert blocks
    if radius is not None:
        whole = plot_network(edges, nodes, buildings=buildings, center=near["center"])
        everywhere = sum(
            len(group["items"])
            for group in whole.data["groups"]
            if group["kind"] == "buildings"
        )
        assert len(blocks) < everywhere
        far = [shapely.Polygon(item["r"][0]).distance(shapely.Point(0, 0)) for item in blocks]
        assert max(far) <= radius
    grid = view.data["groups"][0]["grid"]
    corners = np.array([point[:2] for item in blocks for point in item["r"][0]])
    far = [(grid["columns"] - 1) * grid["step"], (grid["rows"] - 1) * grid["step"]]
    assert (corners >= [grid["x"], grid["y"]]).all()
    assert (corners <= np.add([grid["x"], grid["y"]], far)).all()
    if dem is None and radius is None:
        (drawn_part,) = [item for item in blocks if "part" in item]
        assert drawn_part["h"] == 30.4
    if dem is not None:
        assert view.data["groups"][1]["kind"] == "buildings"
        _, south, _, north = buildings.total_bounds
        heights = [item["g"] for item in blocks]
        assert slope(0, south) - 0.1 <= min(heights) < max(heights)
        assert max(heights) <= slope(0, north) + 0.1


def test_terrain_ground_stays_under_what_is_at_the_surface():
    """The ground on a terrain lies 0.4 m under it, and lower around a square where it
    would rise over a line at the surface, by as much as it would: here a line half a
    metre under a flat terrain of 10 m, also between two of its points 30 m apart. A
    line deeper than 1.5 m under the terrain is below ground and changes nothing. A
    corner without a terrain height has none, and a wide view has wider squares."""

    def flat(x, y):
        return np.where(np.asarray(x) < 290, 10.0, np.nan)

    surface = [[-5.0, 5.0, 9.5], [25.0, 5.0, 9.5]]
    deep = [[-5.0, 45.0, 8.0], [25.0, 45.0, 8.0]]
    grid = _terrain_ground([surface, deep], [], flat, (0.0, 0.0))["grid"]
    assert (grid["x"], grid["y"], grid["step"]) == (-25.0, -15.0, 10.0)
    drawn = np.array(grid["z"], dtype=float).reshape(grid["rows"], grid["columns"])
    terrain = np.array(grid["t"], dtype=float).reshape(drawn.shape)
    assert np.isfinite(terrain).all() and (terrain == 10.0).all()
    lowered = 9.6 - drawn
    # the squares that hold the surface line, from x -5 to 35 and y 5 to 15, and
    # every corner of them, come down by half a metre; nothing else does
    assert set(np.round(lowered[2:4, 2:7].ravel(), 2)) == {0.5}
    lowered[2:4, 2:7] = 0
    assert np.allclose(lowered, 0)

    # 2 km and 20 m on each side: 21 m squares hold it in at most 100
    wide = _terrain_ground([[[0.0, 0.0, 10.0], [2000.0, 0.0, 10.0]]], [], flat, (0, 0))
    grid = wide["grid"]
    assert grid["step"] == 21.0 and 2040 <= (grid["columns"] - 1) * 21.0
    assert grid["columns"] - 1 <= 100
    assert grid["z"][-1] is None and grid["t"][-1] is None
    # 1 km with the margins, from no multiple of the width: still 100 across
    offset = [[[3.3, 0.0, 10.0], [963.3, 0.0, 10.0]]]
    assert _terrain_ground(offset, [], flat, (0, 0))["grid"]["columns"] == 101
