import numpy as np
import pandas as pd
import pytest
import shapely
from geopandas import GeoDataFrame

from pyrosm3d.dem import sample_dem
from pyrosm3d.heights import network_heights


def _point(north, east=0.0):
    """A place ``north`` steps of 0.0001 degrees (11.1 m) north and ``east`` such
    steps east of 24.94 E, 60.17 N."""
    return (24.94 + east * 1e-4, 60.17 + north * 1e-4)


def _ground(longitudes, latitudes):
    """A slope that rises 4 m for each step north from 10 m at 60.17 N, with a hill
    100 m higher between 2.2 and 2.8 steps, and no heights from 10 steps on."""
    north = (np.asarray(latitudes) - 60.17) * 1e4
    heights = 10 + 4 * north + 100 * ((north > 2.2) & (north < 2.8))
    return np.where(north > 9.5, np.nan, heights)


def _edges(rows, point=_point):
    """A frame of edges from ``rows``: dicts with ``u``, ``v``, ``line`` (places of
    :func:`_point`) and other columns of an indoor read."""
    lines = [shapely.LineString([point(*place) for place in row["line"]]) for row in rows]
    columns = pd.DataFrame([{k: v for k, v in row.items() if k != "line"} for row in rows])
    return GeoDataFrame(columns, geometry=lines, crs=4326)


def _street(u, v, *north):
    """A street from node ``u`` to node ``v`` through the places ``north`` steps north."""
    return dict(u=u, v=v, line=[(step,) for step in north])


def _floor(u, v, u_level, v_level, *line, **columns):
    """An edge from level ``u_level`` at node ``u`` to ``v_level`` at ``v``."""
    return dict(u=u, v=v, u_level=u_level, v_level=v_level, line=list(line), **columns)


# Streets that end at node 2 (0 steps north, ground 10 m) and at node 5 (4 steps
# north, ground 26 m)
STREETS = [_street(1, 2, -1, 0), _street(5, 6, 4, 5)]
STREET_ENDS = [(6, 10), (26, 30)]
NONE = float("nan")
CASES = {
    # a line without other columns is a street: the ground at each of its vertices
    "street": (
        [_street(1, 2, 0, 1, 3)],
        [(10, 22)],
        {0: [10, 14, 22]},
    ),
    # a corridor on level 1 from node 2 over node 3 to node 5, its second edge three
    # times as long as its first: node 3 a quarter of the way up from 10 m to 26 m,
    # and the vertex of the second edge over the hill halfway from 14 m to 26 m
    "floor between streets": (
        STREETS + [_floor(2, 3, 1, 1, (0,), (1,)), _floor(3, 5, 1, 1, (1,), (2.5,), (4,))],
        STREET_ENDS + [(10, 14), (14, 26)],
        {3: [14, 20, 26]},
    ),
    # stairs from the street up one level, a corridor there, and a lift two levels
    # up from its end, a line without length
    "stairs, floor and lift": (
        STREETS
        + [
            _floor(2, 3, 0, 1, (0,), (1,), vertical="stairs"),
            _floor(3, 4, 1, 1, (1,), (2,)),
            _floor(4, 7, 1, 3, (2,), (2,), vertical="lift"),
        ],
        STREET_ENDS + [(10, 14), (14, 14), (14, 22)],
        {4: [14, 22]},
    ),
    # a corridor on level -1 and stairs up from it, where the ground is at 10 m and
    # nothing meets a street: a level below ground is 6 m
    "floor away from streets": (
        [
            _floor(1, 2, -1, -1, (0,), (0, 2)),
            _floor(2, 3, -1, 0, (0, 2), (0, 4), vertical="stairs"),
        ],
        [(4, 4), (4, 10)],
        {},
    ),
    # a bridge from node 2 to node 5 with a vertex over the hill, 2.5 of 4 steps along
    "bridge": (
        STREETS + [dict(_street(2, 5, 0, 2.5, 4), bridge="yes")],
        STREET_ENDS + [(10, 26)],
        {2: [10, 20, 26]},
    ),
    # a tunnel of two edges from node 2 to node 5, the second three times as long
    "tunnel": (
        STREETS
        + [
            dict(_street(2, 9, 0, 1), tags='{"tunnel":"yes"}'),
            dict(_street(9, 5, 1, 4), tags='{"tunnel":"yes"}'),
        ],
        STREET_ENDS + [(10, 14), (14, 26)],
        {},
    ),
    # node 3 on level -1 (a corridor from the street, 10 m) and on level 1 (stairs
    # up to node 4, 6 m to the ground floor and 4 m above it, and a corridor back,
    # 20 m): an indoor way without a
    # level, drawn at level 0, starts from the lower of the two, and a way tagged
    # with levels 1 and 2, drawn at level 1, from level 1
    "ends without a level": (
        STREETS
        + [
            _floor(2, 3, -1, -1, (0,), (1,)),
            _floor(3, 4, -1, 1, (1,), (2,), vertical="stairs"),
            _floor(4, 3, 1, 1, (2,), (1,)),
            dict(u=3, v=7, line=[(1,), (1, 2)], tags='{"indoor":"yes"}'),
            dict(u=3, v=8, line=[(1,), (1, -2)], tags='{"level":"1;2"}'),
        ],
        STREET_ENDS + [(10, 10), (10, 20), (20, 20), (10, 10), (20, 20)],
        {},
    ),
    # a street that leaves the terrain model after 9 steps north; a corridor from its
    # node outside the model and stairs from there; a corridor from its node inside
    # the model to a place outside; and a corridor on level -1 that meets no street,
    # from where the ground is at 46 m to a place outside
    "outside the terrain model": (
        [
            _street(1, 2, 8, 9, 11),
            _floor(2, 3, 0, 0, (11,), (12,)),
            _floor(3, 7, 0, 1, (12,), (13,), vertical="stairs"),
            _floor(1, 4, 0, 0, (8,), (9,), (10.5,)),
            _floor(5, 6, -1, -1, (9,), (10.5,)),
        ],
        [(42, NONE), (NONE, NONE), (NONE, NONE), (42, NONE), (40, NONE)],
        {0: None, 3: None, 4: None},
    ),
}


@pytest.mark.parametrize("rows, ends, lines", CASES.values(), ids=CASES.keys())
def test_network_heights_place_small_networks(rows, ends, lines):
    """The heights at the two ends of each edge, and at the vertices of the edges in
    ``lines``, are the ones worked out by hand from the rules of the module; a line
    with a vertex outside the terrain model (None in ``lines``) stays flat, with the
    coordinates it had."""
    edges = _edges(rows)
    found = network_heights(edges, _ground)
    heights = found[["u_height", "v_height"]].to_numpy()
    np.testing.assert_allclose(heights, ends, atol=1e-3)
    for row, expected in lines.items():
        line = found.geometry.iloc[row]
        if expected is None:
            assert not shapely.has_z(line) and line.equals_exact(edges.geometry[row], 0)
            continue
        vertices = shapely.get_coordinates(line, include_z=True)
        np.testing.assert_allclose(vertices[:, 2], expected, atol=1e-3)


def test_network_heights_take_frames_in_another_crs_and_without_edges():
    """Edges in EPSG:3067 get the heights of the same edges in EPSG:4326 and keep
    their coordinates, and a frame without edges gets the two columns."""
    edges = _edges(CASES["floor between streets"][0])
    projected = edges.to_crs(3067)
    found = network_heights(projected, _ground)
    columns = ["u_height", "v_height"]
    np.testing.assert_allclose(
        found[columns], network_heights(edges, _ground)[columns], atol=1e-6
    )
    assert found.crs == projected.crs
    assert shapely.equals_exact(
        shapely.force_2d(found.geometry.to_numpy()), projected.geometry.to_numpy()
    ).all()
    empty = network_heights(edges.iloc[:0], _ground)
    assert empty.empty and set(columns) <= set(empty.columns)


def test_network_heights_measure_lines_across_the_180th_meridian():
    """A bridge that crosses the 180th meridian, with a vertex on it halfway along:
    the vertex lies halfway between the streets at the bridge's ends, 10 m and 26 m."""

    def point(north, east):
        return ((180 + east * 1e-4 + 180) % 360 - 180, 60.17 + north * 1e-4)

    rows = [
        dict(u=1, v=2, line=[(-1, -2), (0, -1)]),
        dict(u=5, v=6, line=[(4, 1), (5, 2)]),
        dict(u=2, v=5, line=[(0, -1), (2, 0), (4, 1)], bridge="yes"),
    ]
    found = network_heights(_edges(rows, point), _ground)
    bridge = shapely.get_coordinates(found.geometry.iloc[2], include_z=True)
    assert bridge[:, 0] == pytest.approx([179.9999, -180, -179.9999])
    assert bridge[:, 2] == pytest.approx([10, 18, 26], abs=1e-3)


def test_network_heights_refuse_edges_without_end_nodes():
    """Edges read without their nodes are refused with the read that gives them."""
    edges = _edges(CASES["street"][0]).drop(columns=["u", "v"])
    with pytest.raises(ValueError, match=r"get_network\(\.\.\., nodes=True\)"):
        network_heights(edges, _ground)


def test_network_heights_place_the_centre_of_helsinki(helsinki_centre, helsinki_dem):
    """On the walking network around Helsinki's railway station, Forum and Kamppi:
    the lines across an outdoor square have the terrain's height at each vertex; the
    door of Forum to its courtyard Kukontori, which a street ends at, has the ground's
    height on Forum's level 2; every node has one height on each level; each of the
    95 edges between two levels climbs towards its higher end, the 50 below the
    ground floor 3 to 7.1 m for each level (6 m in the median) and the 45 above it 2
    to 5 m (4 m in the median); and the metro platform of the railway station, on
    level -3, lies three levels of 6 m below the ground above it."""
    nodes, edges = helsinki_centre
    found = network_heights(edges, helsinki_dem)
    square = found[(found["id"] == 1320750) & found["u_level"].isna()]
    vertices = shapely.get_coordinates(square.geometry.to_numpy(), include_z=True)
    assert len(vertices) > 2 * len(square) > 0
    assert vertices[:, 2] == pytest.approx(
        sample_dem(vertices[:, 0], vertices[:, 1], helsinki_dem)
    )

    door = nodes[nodes["id"] == 256257168].geometry.iloc[0]
    ground = sample_dem([door.x], [door.y], helsinki_dem)[0]
    on_level_2 = found[(found["u"] == 256257168) & (found["u_level"] == 2)]
    assert len(on_level_2) == 5
    assert on_level_2["u_height"].to_numpy() == pytest.approx(ground)

    ends = pd.DataFrame(
        {
            "node": np.r_[found["u"], found["v"]],
            "level": np.r_[found["u_level"], found["v_level"]],
            "height": np.r_[found["u_height"], found["v_height"]],
        }
    )
    assert ends["height"].notna().all()
    heights = ends.groupby(["node", "level"])["height"]
    assert (heights.max() == heights.min()).all()

    climbs = found[found["u_level"] != found["v_level"]].dropna(
        subset=["u_level", "v_level"]
    )
    per_level = (climbs["v_height"] - climbs["u_height"]) / (
        climbs["v_level"] - climbs["u_level"]
    )
    below = climbs[["u_level", "v_level"]].max(axis=1) <= 0
    assert len(climbs) == 95 and below.sum() == 50
    assert per_level[below].between(3, 7.1).all()
    assert per_level[below].median() == pytest.approx(6, abs=0.05)
    assert per_level[~below].between(2, 5).all()
    assert per_level[~below].median() == pytest.approx(4, abs=0.05)

    platform = nodes[nodes["id"] == 5403677505].geometry.iloc[0]
    on_level_3 = found[(found["u"] == 5403677505) & (found["u_level"] == -3)]
    ground = sample_dem([platform.x], [platform.y], helsinki_dem)[0]
    assert ground - on_level_3["u_height"].to_numpy() == pytest.approx(18, abs=0.5)
