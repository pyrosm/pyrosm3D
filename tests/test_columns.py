from dataclasses import replace

import pytest
from geopandas import GeoDataFrame
from shapely.geometry import LineString, box

from pyrosm3d.columns import _room_number, shaft_columns


def _with_shafts(indoor, rooms, climbs=()):
    """``indoor`` with the hand-made shaft ``rooms`` (``(levels, tags, polygon)``) as
    its areas and the ``climbs`` (``(vertical, u_level, v_level, line)``) as its
    edges."""
    levels, tags, polygons = zip(*rooms)
    areas = GeoDataFrame(
        {"kind": "shaft", "levels": list(levels), "tags": list(tags)},
        geometry=list(polygons),
        crs=indoor.areas.crs,
    )
    verticals, u_levels, v_levels, lines = zip(*climbs) if climbs else ([], [], [], [])
    edges = GeoDataFrame(
        {"vertical": verticals, "u_level": u_levels, "v_level": v_levels},
        geometry=list(lines),
        crs=indoor.areas.crs,
    )
    return replace(indoor, areas=areas, edges=edges)


def _summary(columns):
    """``(area of the outline, bottom, top, levels, names)`` of each column."""
    return [(round(c[0].area, 1), *c[1:]) for c in columns]


def test_shaft_columns_of_maunula_talo(maunula):
    """The lift of Maunula-talo is one room through three floors, and each of its two
    stairwells one room through two: three columns."""
    assert _summary(shaft_columns(maunula, "elevator")) == [
        (7.1, 0, 2, [0.0, 1.0, 2.0], [])
    ]
    stairs = shaft_columns(maunula, "stairs")
    assert [column[1:] for column in stairs] == [(1, 2, [1.0, 2.0], [])] * 2


def test_shaft_columns_stack_rooms_over_each_other(maunula):
    """Stairwell rooms over each other on consecutive floors, or with one floor
    missing between them, are one column with the outline of the largest. A room two
    floors above and a room elsewhere are columns of their own. Stairs between two
    levels stretch every column whose outline they lie in to the levels they reach;
    stairs on one level, stairs elsewhere and a lift edge stretch none."""
    stairs = {"room": "stairs"}
    rooms = [
        ((0.0,), stairs, box(0, 0, 4, 4)),
        ((1.0,), {**stairs, "name": "North stairs"}, box(0, 0, 5, 5)),
        ((3.0,), stairs, box(1, 1, 3, 3)),
        ((6.0,), stairs, box(0, 0, 4, 4)),
        ((0.0,), stairs, box(20, 0, 24, 4)),
    ]
    climbs = [
        ("stairs", 3.0, 4.5, LineString([(1, 1), (3, 3)])),
        ("stairs", 9.0, 9.0, LineString([(1, 1), (3, 3)])),
        ("lift", 0.0, 8.0, LineString([(2, 2), (2, 2)])),
        ("stairs", 0.0, 7.0, LineString([(40, 40), (42, 42)])),
    ]
    indoor = _with_shafts(maunula, rooms, climbs)
    assert _summary(shaft_columns(indoor, "stairs")) == [
        (25.0, 0, 5, [0.0, 1.0, 3.0], ["North stairs"]),
        (16.0, 3, 6, [6.0], []),
        (16.0, 0, 0, [0.0], []),
    ]
    assert shaft_columns(indoor, "elevator") == []


def test_shaft_columns_keep_numbered_lifts_apart(maunula):
    """Lift rooms with one number on every floor (the first and last part of their
    ref) form a column, a lift with another number in the same place does not join
    it, and a lift area without a number joins the first column that reaches it."""
    shaft = box(0, 0, 3, 3)
    rooms = [
        ((0.0,), {"room": "elevator", "ref": "AA 00 35"}, shaft),
        ((1.0,), {"room": "elevator", "ref": "AA 01 35"}, shaft),
        ((2.0,), {"room": "elevator", "ref": "AA 02 37"}, shaft),
        ((3.0,), {"highway": "elevator"}, shaft),
        ((0.5,), {"room": "elevator"}, shaft),
    ]
    columns = shaft_columns(_with_shafts(maunula, rooms), "elevator")
    assert [column[1:] for column in columns] == [
        (0, 3, [0.0, 1.0, 3.0], ["AA 00 35", "AA 01 35"]),
        (2, 2, [2.0], ["AA 02 37"]),
    ]


@pytest.mark.parametrize(
    "ref, number",
    [("AA 01 35", "AA 35"), ("B  7", "B 7"), ("12", None), (None, None)],
)
def test_room_number(ref, number):
    """A ref in several parts gives its first and last part; a ref in one part, or
    no ref, gives no number."""
    assert _room_number({} if ref is None else {"ref": ref}) == number
