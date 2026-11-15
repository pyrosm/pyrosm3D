from dataclasses import replace

import numpy as np
import pytest
from shapely.geometry import box

from pyrosm3d.walls import _room_wall_heights, inner_walls, outer_walls, wall_panels


def _length(panels):
    """The length of the walls that ``panels`` make, in metres."""
    return float(np.hypot(*(panels[:, 1, :2] - panels[:, 0, :2]).T).sum())


def test_wall_panels_leave_gaps_at_doors():
    """A wall around a 10 m by 4 m room is four panels, 28 m long. A door 0.1 m off
    the middle of a side leaves a gap of 0.9 m there, a door at a corner 0.45 m on
    each of its two sides, two doors half a metre apart one gap of 1.4 m, and a door
    in the middle of the room none. A panel has its two bottom corners first; a
    segment of one centimetre is left out. Two doors at and just past the end of a
    100 m wall leave one panel that stops 0.45 m before the end."""
    room = np.array([(0, 0), (10, 0), (10, 4), (0, 4), (0, 0)], dtype=float)
    closed = wall_panels(room, np.empty((0, 2)), 4.0, 5.6)
    assert closed.shape == (4, 4, 3) and _length(closed) == pytest.approx(28)
    assert closed[0].tolist() == [[0, 0, 4.0], [10, 0, 4.0], [10, 0, 5.6], [0, 0, 5.6]]
    doors = np.array([(5, 0.1), (10, 4), (5, 2), (0, 2), (0, 2.5)], dtype=float)
    opened = wall_panels(room, doors, 4.0, 5.6)
    assert len(opened) == 6
    assert _length(opened) == pytest.approx(28 - 0.9 - 2 * 0.45 - 1.4)
    bottom = opened[opened[:, :2, 1].max(axis=1) == 0]
    assert sorted(bottom[:, :2, 0].ravel()) == pytest.approx([0, 4.55, 5.45, 10])
    stub = np.array([(0, 0), (0.01, 0), (5, 0)], dtype=float)
    assert len(wall_panels(stub, doors[:0], 0.0, 1.6)) == 1
    long_wall = np.array([(0, 0), (100, 0)], dtype=float)
    at_its_end = np.array([(100, 0), (101, 0)], dtype=float)
    (panel,) = wall_panels(long_wall, at_its_end, 0.0, 1.6)
    assert panel[:2, 0].tolist() == pytest.approx([0, 99.55])


@pytest.mark.parametrize(
    "kind, levels, expected",
    [
        ("room", (1.0,), {1.0: 1.6}),
        ("room", (0.0, 2.0), {0.0: 4.0, 1.0: 4.0, 2.0: 1.6}),
        ("shaft", (0.0, 1.0, 2.0), {0.0: 1.6, 1.0: 1.6, 2.0: 1.6}),
        ("room", (0.5, 1.0), {1.0: 1.6}),
        ("room", (0.0, 1000.0), {0.0: 1.6, 1000.0: 1.6}),
        ("room", (), {}),
    ],
)
def test_room_wall_heights(kind, levels, expected):
    """A room has cut-away walls on its whole levels. A tall room has full walls on
    every level below its highest, also on a level that its level list leaves out; a
    shaft, and a room whose levels are further apart than a building has floors, do
    not."""
    assert _room_wall_heights(kind, levels) == expected


def test_inner_walls_of_maunula_talo(maunula):
    """On each level the walls run along the outlines of the rooms, of the wall
    mapped as an area and of the wall mapped as a line, 1.6 m high from the floor,
    less the gaps of the doors of that level: a door opens at most the walls of the
    two rooms beside it. An area without a wall long enough to draw gives none."""
    walls = inner_walls(maunula)
    assert sorted(walls) == [0.0, 1.0, 2.0]
    areas = maunula.areas
    for level, panels in walls.items():
        walled = [
            level in levels
            and (
                kind == "wall"
                or (tags.get("indoor") == "room" and tags.get("room") != "corridor")
            )
            for kind, levels, tags in zip(areas["kind"], areas["levels"], areas["tags"])
        ]
        lines = maunula.walls[[level in found for found in maunula.walls["levels"]]]
        perimeter = areas[walled].length.sum() + lines.length.sum()
        doors = sum(level in found for found in maunula.doors["levels"])
        assert perimeter - 2 * 0.9 * doors <= _length(panels) <= perimeter
        assert set(panels[:, :2, 2].ravel()) == {level * 4.0}
        assert set(panels[:, 2:, 2].ravel()) == {level * 4.0 + 1.6}
    assert _length(walls[1.0]) == pytest.approx(453.8, abs=0.1)
    wall = areas[areas["kind"] == "wall"].geometry.iloc[0]
    no_wall_area = replace(maunula, areas=areas[areas["kind"] != "wall"])
    added = _length(walls[2.0]) - _length(inner_walls(no_wall_area)[2.0])
    assert added == pytest.approx(wall.exterior.length)

    speck = areas[areas["kind"] == "wall"].copy()
    speck.geometry = [box(0, 0, 0.02, 0.02)]
    nothing = replace(maunula, areas=speck, walls=maunula.walls.iloc[:0])
    assert inner_walls(nothing) == {}


def test_outer_walls_of_maunula_talo(maunula):
    """Outer walls stand a full storey high along the level outlines of two buildings,
    over their floors. Without level outlines, the building that holds the rooms
    gives them on the levels of its rooms, inside the view only and with no wall where
    the view cuts through the building; without building outlines, or with a building
    that holds no area, there are none, and a tram shelter around a platform area
    without an indoor tag gets none."""
    areas = maunula.areas
    view = box(*areas.total_bounds).buffer(10)
    walls, floors = outer_walls(maunula, view)
    assert sorted(walls) == sorted(floors) == [0.0, 1.0, 2.0]
    assert [round(floor.area) for floor in floors[0.0]] == [2960, 1837]
    assert [round(floor.area) for floor in floors[2.0]] == [1837]
    outline = sum(floor.length for floor in floors[2.0])
    assert outline - 2 * 0.9 * 29 <= _length(walls[2.0]) <= outline
    assert set(walls[2.0][:, 2:, 2].ravel() - walls[2.0][:, :2, 2].ravel()) == {4.0}

    rooms = replace(maunula, areas=areas[areas["kind"] != "level"])
    walls, floors = outer_walls(rooms, view)
    assert sorted(walls) == [0.0, 1.0, 2.0]
    (building,) = floors[1.0]
    assert round(building.area) == 1837
    west, south, east, north = building.bounds
    middle = (west + east) / 2
    half = box(west - 10, south - 10, middle, north + 10)
    walls, floors = outer_walls(rooms, half)
    assert floors[1.0][0].area == pytest.approx(building.intersection(half).area)
    inside = building.boundary.intersection(half).length
    assert inside - 2 * 0.9 * 39 <= _length(walls[1.0]) <= inside + 1e-6
    on_edge = (walls[1.0][:, :2, 0] > middle - 1e-6).all(axis=1)
    assert not on_edge.any()
    no_buildings = replace(rooms, buildings=maunula.buildings.iloc[:0])
    assert outer_walls(no_buildings, view) == ({}, {})
    corner = maunula.buildings.iloc[:1].copy()
    corner.geometry = [box(view.bounds[0], view.bounds[1], *areas.total_bounds[:2])]
    assert outer_walls(replace(rooms, buildings=corner), view) == ({}, {})
