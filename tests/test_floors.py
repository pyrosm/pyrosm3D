import numpy as np
import pytest
from shapely.geometry import Polygon

from pyrosm3d.floors import floor_levels, triangles


@pytest.mark.parametrize(
    "kind, levels, expected",
    [
        ("room", (1.0,), [1.0]),
        ("room", (1.0, 2.0), [1.0]),
        ("corridor", (0.5, 1.0, 2.0), [1.0]),
        ("shaft", (0.0, 1.0, 2.0), [0.0, 1.0, 2.0]),
        ("room", (0.5,), []),
        ("room", (), []),
    ],
)
def test_floor_levels(kind, levels, expected):
    """An area has a floor on its whole levels: on the lowest when it is a tall space
    over several of them, on each of them when it is a shaft, on none between two
    floors."""
    assert floor_levels(kind, levels) == expected


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
