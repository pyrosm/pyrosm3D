from dataclasses import replace

import numpy as np
import pytest
import shapely

from pyrosm3d.columns import shaft_columns
from pyrosm3d.floors import floor_levels, floor_openings
from pyrosm3d.indoor_view import (
    IndoorBox,
    indoor_groups,
    indoor_stretch,
    level_heights,
)
from pyrosm3d.styles import AREA_STYLES
from pyrosm3d.walls import building_outlines, inner_walls, outer_walls


def _heights(x, y, level):
    """Heights 10 m apart for each level, from 100 m on level 0."""
    return 100.0 + 10.0 * level


def _drawn(indoor, heights=_heights):
    """The IndoorBox of ``indoor``, the middle of its box and its groups by name, at
    ``heights``."""
    view = IndoorBox(indoor)
    west, south, east, north = view.box
    origin = ((west + east) / 2, (south + north) / 2)
    groups = indoor_groups(view, origin, heights)
    return view, origin, {group["name"]: group for group in groups}


def _heights_of(items):
    """The height of every point of the rings or paths of ``items``."""
    found = []
    for item in items:
        if "r" in item:
            found += [point[2] for ring in item["r"] for point in ring]
        else:
            found += [point[2] for point in item["p"]]
    return found


def test_indoor_groups_place_every_shape_at_the_height_of_its_level(maunula):
    """Floors lie just under the height of their level, outlines just under it, doors
    and shops over it; walls rise from it, cut away at 1.6 m or up to the next level;
    columns reach from their lowest floor to wall height over their highest. The
    outlines, the outer walls and the floors under them are for the indoor view only,
    and those walls and floors, the doors and the shops are off at the start."""
    view, _, groups = _drawn(maunula)
    assert [
        (name, group["kind"], group.get("only"), group["visible"])
        for name, group in groups.items()
    ] == [
        ("Rooms", "floors", None, True),
        ("Toilets", "floors", None, True),
        ("Corridors and indoor areas", "floors", None, True),
        ("Stairwells, lifts, storage", "floors", None, True),
        ("Platform areas", "floors", None, True),
        ("Walking areas", "floors", None, True),
        ("Level outlines", "outlines", "indoor", True),
        ("Walls (rooms and indoor=wall)", "glass", None, True),
        ("Outer walls (level or building outlines)", "glass", "indoor", False),
        ("Level floors", "floors", "indoor", False),
        ("Stairwells (room=stairs)", "glass", None, True),
        ("Lift shafts (room=elevator or highway=elevator)", "glass", None, True),
        ("Doors and entrances", "points", None, False),
        ("Shops and amenities", "points", None, False),
    ]
    lifts = {"Level outlines": -0.05, "Level floors": -0.4}
    for name, group in groups.items():
        lift = lifts.get(name, -0.15 if group["kind"] == "floors" else 0.0)
        if group["kind"] in ("floors", "outlines"):
            for item in group["items"]:
                expected = round(_heights(0, 0, item["l"]) + lift, 2)
                assert set(np.round(_heights_of([item]), 2)) == {expected}
    outer = outer_walls(view.indoor, view.shape)[0]
    for name, panels in (
        ("Walls (rooms and indoor=wall)", inner_walls(view.indoor)),
        ("Outer walls (level or building outlines)", outer),
    ):
        items = groups[name]["items"]
        by_level = {level: len(found) for level, found in panels.items()}
        drawn = {level: sum(item["l"] == level for item in items) for level in by_level}
        assert drawn == by_level and len(items) == sum(by_level.values())
        assert {round(item["h"], 2) for item in items} <= {1.6, 10.0}
        assert all(
            set(_heights_of([item])) == {_heights(0, 0, item["l"])} for item in items
        )
    for name, room in (
        ("Stairwells (room=stairs)", "stairs"),
        ("Lift shafts (room=elevator or highway=elevator)", "elevator"),
    ):
        columns = shaft_columns(view.indoor, room)
        expected = {
            round(_heights(0, 0, top) + 1.6 - _heights(0, 0, bottom), 2)
            for _, bottom, top, *_ in columns
        }
        items = groups[name]["items"]
        assert {item["h"] for item in items} == expected
        assert all("l" not in item for item in items)
    for name, lift in (("Doors and entrances", 0.8), ("Shops and amenities", 0.3)):
        for item in groups[name]["items"]:
            assert item["c"][2] == pytest.approx(_heights(0, 0, item["l"]) + lift)


def test_indoor_groups_open_floors_where_stairs_rise(maunula):
    """Where stairs climb from the first to the second floor, the floors of the second
    floor are open along them: they are smaller by what the opening takes of the
    areas."""
    edges = maunula.edges.copy()
    on_second = (edges["u_level"] == 2) & (edges["v_level"] == 2)
    row = edges.index[on_second & (edges.length > 5)][0]
    edges.loc[row, "u_level"] = 1.0
    edges.loc[row, "vertical"] = "stairs"
    opening = floor_openings(edges.loc[[row]])[2.0]
    areas = maunula.areas
    has_floor = [
        kind in AREA_STYLES and 2.0 in floor_levels(kind, levels)
        for kind, levels in zip(areas["kind"], areas["levels"])
    ]
    taken = areas[has_floor].intersection(opening).area.sum()
    assert taken > 1

    def second_floor(indoor):
        _, _, groups = _drawn(indoor)
        polygons = [
            shapely.Polygon(item["r"][0], item["r"][1:])
            for group in groups.values()
            if group["kind"] == "floors" and group.get("only") is None
            for item in group["items"]
            if item["l"] == 2.0
        ]
        return sum(polygon.area for polygon in polygons)

    closed = second_floor(maunula)
    opened = second_floor(replace(maunula, edges=edges))
    assert closed - opened == pytest.approx(taken, rel=0.01)


def test_indoor_groups_outline_buildings_without_level_outlines(maunula):
    """Without level outlines, the building that holds the rooms has its outline on
    the levels of its rooms, at the heights of those levels: 4 m a level above the
    ground floor."""
    rooms = replace(maunula, areas=maunula.areas[maunula.areas["kind"] != "level"])
    view, _, groups = _drawn(rooms, heights=level_heights)
    assert "Level outlines" not in groups
    items = groups["Building outlines"]["items"]
    outlines = building_outlines(view.indoor, view.shape)
    assert sorted({item["l"] for item in items}) == sorted(outlines) == [0.0, 1.0, 2.0]
    assert len(items) == sum(len(paths) for paths in outlines.values())
    for item in items:
        assert set(_heights_of([item])) == {4.0 * item["l"] - 0.05}


@pytest.mark.parametrize(
    "box, low, high, expected",
    [
        ((0, 0, 100, 60), 0.0, 8.0, 2.2),
        ((0, 0, 1000, 200), 0.0, 4.0, 0.12 * 1000 / 7),
        ((0, 0, 20, 10), -12.0, 8.0, 1.1 * 20 / 23),
    ],
)
def test_indoor_stretch(box, low, high, expected):
    """The indoor view draws its heights 2.2 times taller than to scale, as far as its
    drawn height stays between 0.12 and 1.1 of the longest side of its box."""
    assert indoor_stretch(box, low, high) == pytest.approx(expected)
