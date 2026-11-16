import numpy as np
import pytest
from geopandas import GeoDataFrame
from shapely.geometry import LineString, Polygon

from pyrosm3d.floors import floor_levels, floor_openings, triangles


@pytest.mark.parametrize(
    "kind, levels, expected",
    [
        ("room", (1.0,), [1.0]),
        ("room", (1.0, 2.0), [1.0]),
        ("corridor", (0.5, 1.0, 2.0), [1.0]),
        ("shaft", (0.0, 1.0, 2.0), [0.0, 1.0, 2.0]),
        ("room", (0.5,), [0.5]),
        ("shaft", (0.25, 0.5), [0.25, 0.5]),
        ("room", (), []),
    ],
)
def test_floor_levels(kind, levels, expected):
    """An area has a floor on its whole levels: on the lowest when it is a tall space
    over several of them, on each of them when it is a shaft. Without a whole level
    its levels between two floors count in the same way."""
    assert floor_levels(kind, levels) == expected


def test_floor_openings():
    """An escalator from level 0 to 1 opens the floor of level 1 along it, 1.6 m wide,
    up to a 1 m landing at its top. Stairs drawn from level 2 down to 0 open level 1
    over their lower half and level 2 up to the landing, 2 m wide. A lift, stairs on
    one level, stairs without levels, stairs no longer than their landing, an edge
    under half a metre and a climb of more levels than a building has open nothing,
    and neither do edges without the columns of an indoor network."""
    climbs = [
        ("escalator", 0.0, 1.0, [(0, 0), (10, 0)]),
        ("stairs", 2.0, 0.0, [(12, 10), (0, 10)]),
        ("lift", 0.0, 2.0, [(0, 20), (10, 20)]),
        ("stairs", 1.0, 1.0, [(0, 30), (10, 30)]),
        ("stairs", np.nan, np.nan, [(0, 40), (10, 40)]),
        ("stairs", 0.0, 1.0, [(0, 50), (1.05, 50)]),
        ("moving_walkway", 0.0, 1.0, [(0, 60), (0.4, 60)]),
        ("stairs", 0.0, 1e9, [(0, 70), (10, 70)]),
    ]
    verticals, u_levels, v_levels, lines = zip(*climbs)
    edges = GeoDataFrame(
        {"vertical": verticals, "u_level": u_levels, "v_level": v_levels},
        geometry=[LineString(line) for line in lines],
        crs=32635,
    )
    openings = floor_openings(edges)
    assert set(openings) == {1.0, 2.0}
    escalator, stairs = sorted(openings[1.0].geoms, key=lambda part: part.bounds[1])
    assert escalator.bounds == pytest.approx((0, -0.8, 9, 0.8))
    assert stairs.bounds == pytest.approx((0, 9, 6, 11))
    assert openings[1.0].area == pytest.approx(9 * 1.6 + 6 * 2.0)
    assert openings[2.0].bounds == pytest.approx((0, 9, 11, 11))
    assert openings[2.0].area == pytest.approx(11 * 2.0)
    assert floor_openings(edges[["geometry"]]) == {}


def test_triangles_cover_a_polygon_with_a_hole():
    """The triangles of a 4 m square with a 1 m hole cover its 15 square metres and
    leave the hole open."""
    hole = [(1, 1), (2, 1), (2, 2), (1, 2)]
    square = Polygon([(0, 0), (4, 0), (4, 4), (0, 4)], [hole])
    corners = triangles(square)
    assert corners.shape[1:] == (3, 2)
    a, b, c = corners[:, 0], corners[:, 1], corners[:, 2]
    doubled = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (c[:, 0] - a[:, 0]) * (
        b[:, 1] - a[:, 1]
    )
    assert np.abs(doubled).sum() / 2 == pytest.approx(15.0)
    middles = corners.mean(axis=1)
    in_hole = (middles > 1).all(axis=1) & (middles < 2).all(axis=1)
    assert not in_hole.any()
