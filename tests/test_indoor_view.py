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
    layers_view,
    level_heights,
)
from pyrosm3d.styles import AREA_STYLES, VIEW_MARGIN
from pyrosm3d.tags import crosses_area, element_keys
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


def _groups(view):
    """The groups of a view by name."""
    return {group["name"]: group for group in view.data["groups"]}


def _on_levels(group):
    """``{level: items}`` of a group: an item on its level, a line on the levels that
    the indoor view shows it on."""
    found = {}
    for item in group.get("items", []):
        levels = [item["l"]] if "l" in item else item.get("ls", [item.get("a", 0.0)])
        for level in levels:
            found[level] = found.get(level, 0) + 1
    return found


def _area(item):
    """The area of the polygon of a floor item, in square metres."""
    return shapely.Polygon(item["r"][0], item["r"][1:]).area


def _length(item):
    """The length of the path of a line item on the ground, in metres."""
    xy = np.asarray(item["p"])[:, :2]
    return float(np.hypot(*np.diff(xy, axis=0).T).sum())


def test_plot_indoor_draws_maunula_talo(maunula):
    """The view opens in the indoor view over the box of the areas, with a level to
    pick for each floor and the heights drawn taller. The floors of each kind cover
    the areas inside the box, one for each area and floor level: the lift shaft on
    each of its three levels, the platform areas and the two squares on street level;
    the larger square reaches past the box and is drawn as far as it goes. The network
    is on its levels, without the outlines of platforms that have floors; the solid
    model and the see-through map stand on a flat ground."""
    view = layers_view(maunula)
    data, groups = view.data, _groups(view)
    areas = maunula.areas
    west, south, east, north = areas[areas["kind"] != "walking_area"].total_bounds
    box = shapely.box(west, south, east, north).buffer(VIEW_MARGIN, join_style=2)
    half = (east - west) / 2 + VIEW_MARGIN
    indoor = data["indoor"]
    assert data["mode"] == "indoor" and "level" not in indoor
    assert indoor["box"][0] == pytest.approx(-half, abs=0.1) and indoor["ground"] == 0
    assert indoor["levels"] == [[0.0, 0.0], [1.0, 4.0], [2.0, 8.0]]
    assert indoor["stretch"] == 2.2 and indoor["background"] == "#ffffff"
    assert data["groups"][0]["name"] == "Ground"
    square = areas[areas["id"] == 1250318665].geometry.iloc[0]
    assert square.intersection(box).area == pytest.approx(378.2, abs=0.1)
    clipped = areas.assign(geometry=areas.intersection(box))
    for kind, (name, _, _) in AREA_STYLES.items():
        rows = clipped[clipped["kind"] == kind]
        on_levels = [floor_levels(kind, levels) for levels in rows["levels"]]
        items = groups[name]["items"] if name in groups else []
        drawn = {item["t"].split("\n")[-1] for item in items}
        assert drawn == {
            "%s · level %g" % (key, level)
            for key, levels in zip(element_keys(rows), on_levels)
            for level in levels
        }
        columns = (rows.geometry.area, rows.geometry.length, on_levels)
        expected = sum(area * len(levels) for area, _, levels in zip(*columns))
        outline = sum(length * len(levels) for _, length, levels in zip(*columns))
        assert abs(sum(map(_area, items)) - expected) <= 0.01 * outline
    assert set(_on_levels(groups["Stairwells, lifts, storage"])) == {0.0, 1.0, 2.0}
    assert set(_on_levels(groups["Platform areas"])) == {0.0}
    assert set(_on_levels(groups["Lines across areas"])) == {0.0, 1.0, 2.0}
    assert "Platforms" not in groups
    stairs = groups["Stairs"]["items"][0]
    tables = data["tables"]
    assert (stairs["w"], tables["names"][stairs["n"]]) == (674689746, "Stairs")
    assert (tables["highways"][stairs["h"]], stairs["a"]) == ("steps", 0.0)
    kinds = [group["kind"] for group in data["groups"]]
    assert kinds.index("lines") > kinds.index("glass") and kinds[-1] == "points"


def test_plot_indoor_opens_on_a_level(maunula, tmp_path, run_view):
    """With a level the indoor view opens on it, at its height; a door on a level
    between two floors is shown on its whole level, an edge half a level below the
    floor also on the floor's level, and a level with nothing on it is refused."""
    on_first = maunula.doors["levels"].map(lambda levels: levels == (1.0,))
    doors = maunula.doors[on_first].iloc[:1].assign(levels=[(0.5, 1.0)])
    edges = maunula.edges.copy()
    row = edges.index[(edges["u_level"] == 1) & (edges["v_level"] == 1)][0]
    edges.loc[row, ["u_level", "v_level"]] = 0.5
    view = layers_view(replace(maunula, doors=doors, edges=edges), level=1)
    groups = _groups(view)
    assert view.data["indoor"]["level"] == 1.0
    assert [level for level, _ in view.data["indoor"]["levels"]] == [0.0, 1.0, 2.0]
    assert _on_levels(groups["Doors and entrances"]) == {1.0: 1}
    half = [
        item
        for group in groups.values()
        if group["kind"] == "lines"
        for item in group["items"]
        if 0.5 in item.get("ls", [])
    ]
    assert [item["ls"] for item in half] == [[0.5, 1.0]]
    assert {point[2] for point in half[0]["p"]} == {2.0}
    (start,) = run_view(view, (), tmp_path)
    assert start["controls"]["level"]["value"] == "1"
    stretch = view.data["indoor"]["stretch"]
    assert start["viewState"]["target"][2] == pytest.approx(4.0 * stretch)
    with pytest.raises(ValueError, match="nothing to draw on level 5"):
        layers_view(maunula, level=5)


def test_plot_indoor_shows_a_line_on_the_levels_of_its_edges(maunula):
    """The edges of one way that run on from each other make one line, shown on the
    levels of each of them; an edge without an id is a line of its own, on its
    levels."""
    edges = maunula.edges.copy()
    first, second = edges.index[edges["id"] == 26131689][:2]
    edges.loc[first, ["u_level", "v_level"]] = 1.0
    edges.loc[second, ["u_level", "v_level"]] = [1.0, 0.5]
    lines = _groups(layers_view(replace(maunula, edges=edges)))
    (joined,) = [
        item
        for item in lines["Walkways on other levels"]["items"]
        if item.get("w") == 26131689
    ]
    assert (joined["a"], joined["c"], joined["ls"]) == (1.0, 0.5, [0.5, 1.0])
    edges.loc[second, "id"] = None
    lines = _groups(layers_view(replace(maunula, edges=edges)))
    (own,) = [item for item in lines["Walkways on other levels"]["items"] if "t" in item]
    assert own["ls"] == [0.5, 1.0]


def test_plot_indoor_draws_a_floor_between_two_levels(maunula):
    """A room whose only level is between two floors has its floor, outline and walls
    at its own height, and a level of its own to pick; a door there is a point and an
    edge there is shown on that level only."""
    areas = maunula.areas.copy()
    on_first = areas["levels"].map(lambda levels: levels == (1.0,))
    room = areas.index[(areas["kind"] == "room") & on_first][0]
    areas["levels"] = [
        (0.5,) if row == room else levels
        for row, levels in zip(areas.index, areas["levels"])
    ]
    door_on_first = maunula.doors["levels"].map(lambda levels: levels == (1.0,))
    doors = maunula.doors[door_on_first].iloc[:1].assign(levels=[(0.5,)])
    edges = maunula.edges.copy()
    edge = edges.index[(edges["u_level"] == 1) & (edges["v_level"] == 1)][0]
    edges.loc[edge, ["u_level", "v_level"]] = 0.5
    view = layers_view(replace(maunula, areas=areas, doors=doors, edges=edges), 0.5)
    groups = _groups(view)
    assert [level for level, _ in view.data["indoor"]["levels"]] == [0, 0.5, 1, 2]
    on_half = {
        name for name, group in groups.items() if 0.5 in _on_levels(group)
    }
    drawn = {"Rooms", "Walls (rooms and indoor=wall)", "Doors and entrances"}
    assert drawn < on_half and len(on_half) == len(drawn) + 1  # and the edge
    (floor,) = [item for item in groups["Rooms"]["items"] if item["l"] == 0.5]
    assert {point[2] for point in floor["r"][0]} == {1.85}
    (edge,) = on_half - drawn
    shown = [item.get("ls", [item["a"]]) for item in groups[edge]["items"]]
    assert [0.5] in shown and all(0.5 not in levels[:-1] for levels in shown)


def test_plot_indoor_draws_platform_lines_without_a_floor(maunula):
    """The outline of a platform mapped as a closed way is an edge of the network.
    Where the platform has a floor, with an outline of its own, the edge is not drawn
    as a "Platforms" line; without the floor it is, where it reaches the view."""
    areas, edges = maunula.areas, maunula.edges
    no_floors = replace(maunula, areas=areas[areas["kind"] != "platform"])
    lines = _groups(layers_view(no_floors))["Platforms"]
    assert set(_on_levels(lines)) == {0.0}
    platforms = set(element_keys(areas[areas["kind"] == "platform"]))
    of_platform = np.array([key in platforms for key in element_keys(edges)])
    outlines = edges[of_platform & ~crosses_area(edges)]
    assert len(outlines) == 27
    in_view = outlines[outlines.intersects(IndoorBox(no_floors).shape)]
    drawn = sum(map(_length, lines["items"]))
    assert drawn == pytest.approx(in_view.length.sum(), abs=0.5)


def test_plot_indoor_view_follows_the_other_areas(maunula):
    """A walking area does not widen the view: one that lies outside the view of the
    other areas has no floor. Where the walking areas are the only areas, the view is
    theirs and their floors are whole."""
    areas = maunula.areas
    is_square = areas["kind"] == "walking_area"
    far = areas.assign(geometry=areas.geometry.where(~is_square, areas.translate(5000)))
    view = layers_view(replace(maunula, areas=far))
    assert "Walking areas" not in _groups(view)
    assert view.data["indoor"]["box"] == layers_view(maunula).data["indoor"]["box"]

    view = layers_view(replace(maunula, areas=areas[is_square]))
    floors = _groups(view)["Walking areas"]["items"]
    squares = areas[is_square].geometry
    outline = squares.length.sum()
    assert sum(map(_area, floors)) == pytest.approx(squares.area.sum(), abs=0.01 * outline)
    west, _, east, _ = view.data["indoor"]["box"]
    assert east - west == pytest.approx(np.ptp(squares.total_bounds[::2]) + 2 * VIEW_MARGIN, abs=0.1)


def test_plot_indoor_without_areas(maunula):
    """Without areas the view is the network, and a wall mapped as a line is still
    drawn, unless it lies outside the view; without a network too there is nothing to
    draw."""
    no_areas = replace(maunula, areas=maunula.areas.iloc[:0])
    groups = _groups(layers_view(no_areas))
    assert [name for name, group in groups.items() if group["kind"] == "glass"] == [
        "Walls (rooms and indoor=wall)"
    ]
    far = maunula.walls.assign(levels=[(7.0,)])
    far.geometry = far.translate(5000, 0)
    groups = _groups(layers_view(replace(no_areas, walls=far)))
    assert "glass" not in {group["kind"] for group in groups.values()}
    assert "Walkways at street level" in groups
    with pytest.raises(ValueError, match="nothing to draw on level 7"):
        layers_view(replace(maunula, walls=far), level=7)
    with pytest.raises(ValueError, match="no areas and no network"):
        layers_view(replace(no_areas, edges=maunula.edges.iloc[:0]))
