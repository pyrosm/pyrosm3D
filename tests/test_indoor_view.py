import json
import re
from dataclasses import replace

import numpy as np
import pytest
import shapely

from pyrosm3d.columns import shaft_columns
from pyrosm3d.floors import floor_levels, floor_openings
from pyrosm3d import network_heights
from pyrosm3d.indoor import indoor_layers
from pyrosm3d.indoor_view import (
    IndoorBox,
    LevelHeights,
    element_notes,
    indoor_groups,
    indoor_stretch,
    layers_view,
    level_heights,
    plot_indoor,
    to_html,
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
    assert [entry[:2] for entry in indoor["levels"]] == [[0, 0], [1, 4], [2, 8]]
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
    assert [level for level, *_ in view.data["indoor"]["levels"]] == [0.0, 1.0, 2.0]
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
    assert [level for level, *_ in view.data["indoor"]["levels"]] == [0, 0.5, 1, 2]
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


def test_to_html_writes_the_view_with_levels_and_tags(
    maunula, maunula_frames, tmp_path, run_view
):
    """The page of to_html is the view of plot_indoor under its title, with the
    deck.gl library from where it is asked. The level picker names the number of areas
    on each level, a tap on a room shows what it is, its tags and a link to it, and a
    tap on an item of no element shows its own text only."""
    path = to_html(
        path=tmp_path / "maunula.html",
        title="Maunula-talo <3D>",
        deck_gl="deck.min.js",
        **maunula_frames,
    )
    page = path.read_text(encoding="utf-8")
    assert "<title>Maunula-talo &lt;3D&gt;</title>" in page
    assert '<script src="deck.min.js"' in page
    data = re.search(r'<script id="data" type="application/json">(.*?)</script>', page)
    view = plot_indoor(**maunula_frames)
    assert json.loads(data[1]) == json.loads(json.dumps(view.data))
    floors = maunula.areas[maunula.areas["kind"].isin(list(AREA_STYLES))]
    counts = {
        level: sum(level in levels for levels in floors["levels"])
        for level in (0.0, 1.0, 2.0)
    }
    assert counts[0.0] == 7  # four platforms, the two squares and the lift
    steps = [
        ["click", "floors-Rooms", 0],
        ["toggle", "Level floors"],
        ["click", "floors-Level floors", 0],
    ]
    start, room, _, level_floor = run_view(view, steps, tmp_path)
    assert start["controls"]["levelChoices"] == [["", "All levels"]] + [
        [str(int(level)), "Level %d · %d areas" % (level, count)]
        for level, count in counts.items()
    ]
    item = _groups(view)["Rooms"]["items"][0]
    key, note, tags = view.data["tables"]["elements"][item["q"]]
    assert room["info"].startswith(item["t"] + "\n\n" + note + "\n")
    assert "indoor = room" in room["info"] and note.startswith("room · level")
    assert tags["indoor"] == "room"
    assert room["links"] == ["https://www.openstreetmap.org/" + key.replace(" ", "/")]
    assert level_floor["info"] == "Floor of level 0" and level_floor["links"] == []


def test_level_counts_leave_out_areas_outside_the_view(maunula):
    """The number of areas on a level holds the areas that the view draws: a walking
    area that lies outside the view of the other areas, or only touches its edge, is
    not counted and has no floor."""
    areas = maunula.areas
    is_square = areas["id"] == 674689752
    _, south, east, _ = IndoorBox(maunula).box
    beside_the_view = shapely.box(east, south, east + 10, south + 10)
    moved = {
        "near": areas.geometry,
        "far": areas.geometry.where(~is_square, areas.translate(5000)),
        "touching": areas.geometry.where(~is_square, beside_the_view),
    }
    counts, floors = {}, {}
    for name, geometry in moved.items():
        view = layers_view(replace(maunula, areas=areas.assign(geometry=geometry)))
        levels = view.data["indoor"]["levels"]
        counts[name] = {level: count for level, _, count in levels}
        floors[name] = len(_groups(view)["Walking areas"]["items"])
    assert counts["near"][0.0] == 7
    assert counts["far"] == counts["touching"] == {**counts["near"], 0.0: 6}
    assert floors["far"] == floors["touching"] == floors["near"] - 1


def test_element_notes_of_maunula_talo(maunula):
    """The note of an element says what it is and its levels: an area by its kind (a
    platform area also for the edges of its outline), an edge of the network by its
    kind and the levels of its ends, a door and a shop or amenity by their levels."""
    notes = element_notes(maunula)
    assert notes["way 1568797319"] == "stairwell, lift or storage · levels 0, 1, 2"
    assert notes["way 536922648"] == "platform area · level 0"
    assert notes["way 1576010635"] == "wall · level 2"
    assert notes["way 674689746"] == "stairs · level 0"
    assert notes["way 26131689"] == "walkway · level 0"
    doors = maunula.doors
    on_first = doors[doors["levels"].map(lambda levels: levels == (1.0,))]
    assert notes["node %d" % on_first["id"].iloc[0]] == "door or entrance · level 1"
    unlevelled = doors[doors["levels"].map(len) == 0]
    assert notes["node %d" % unlevelled["id"].iloc[0]] == "door or entrance · no level"
    shop = maunula.pois[maunula.pois["kind"] == "shop"].iloc[0]
    key = "%s %d" % (shop["osm_type"], shop["id"])
    assert notes[key] == "shop or amenity · level %g" % shop["levels"][0]


def test_plot_indoor_draws_the_buildings_in_its_box(maunula, maunula_frames):
    """The solid model and the see-through map draw the buildings that reach into the
    box of the indoor view (what parts leave of one may lie beside it), on a ground
    that holds them; the start views stay those of the indoor elements."""
    view = plot_indoor(**maunula_frames)
    plain = layers_view(maunula)
    kinds = [group["kind"] for group in view.data["groups"]]
    assert kinds[1:3] == ["buildings", "buildings"]
    assert view.data["groups"][3:] == plain.data["groups"][1:]
    assert (view.data["view"], view.data["fit"]) == (plain.data["view"], plain.data["fit"])
    assert view.data["indoor"] == plain.data["indoor"]
    blocks = view.data["groups"][1]["items"] + view.data["groups"][2]["items"]
    box = shapely.box(*view.data["indoor"]["box"])
    assert all(shapely.Polygon(item["r"][0]).distance(box) < 50 for item in blocks)
    grid = view.data["groups"][0]["grid"]
    corners = np.array([point[:2] for item in blocks for point in item["r"][0]])
    assert (corners >= [grid["x"], grid["y"]]).all()
    assert (corners <= [grid["x"] + grid["step"], grid["y"] + grid["step"]]).all()


def test_plot_indoor_on_a_terrain(helsinki_station_frames, helsinki_dem):
    """With a terrain model a level is at the heights of the network's nodes on it in
    its building, and a level without them at the nearest level with them moved by 4 m
    a level above the ground floor and 6 m below; outside buildings at the terrain
    moved so, as at the middle of the view; a floor outside buildings near the terrain
    follows it. The edges have their heights, and the ground and the buildings lie on
    the terrain."""
    frames = helsinki_station_frames
    view = plot_indoor(**frames, dem=helsinki_dem)
    indoor, groups = view.data["indoor"], _groups(view)
    by_level = {level: height for level, height, _ in indoor["levels"]}
    assert by_level[0.0] == indoor["ground"] > 0
    assert by_level[-1.0] == pytest.approx(indoor["ground"] - 6.0)
    assert by_level[1.0] == pytest.approx(indoor["ground"] + 4.0)
    assert groups["Ground"]["grid"]["t"][0] is not None
    assert all("m" in item for item in groups["Stairs"]["items"])
    assert min(item["g"] for item in groups["Buildings"]["items"]) > 0
    draped = [
        item
        for item in groups["Platform areas"]["items"]
        if len({point[2] for point in item["r"][0]}) > 1
    ]
    assert draped  # outdoor platforms on the terrain

    edges = network_heights(frames["edges"], helsinki_dem)
    layers = indoor_layers(frames["elements"], frames["nodes"], edges, frames["buildings"])
    heights = LevelHeights(layers, lambda x, y: np.full(len(x), 1.0))
    # a floor outside buildings with a height from the network where the terrain has
    # none keeps that height; with the terrain there, near it, it follows it
    west, south = layers.buildings.total_bounds[:2]
    far = shapely.box(west - 500, south - 500, west - 480, south - 480)
    nowhere = LevelHeights(layers, lambda x, y: np.full(len(x), np.nan))
    nowhere._nodes_height_on = lambda polygon, level: 5.0
    assert nowhere.floor(far, 0.0) == pytest.approx(4.85)
    flat = LevelHeights(layers, lambda x, y: np.full(len(x), 4.5))
    flat._nodes_height_on = lambda polygon, level: 5.0
    assert callable(flat.floor(far, 0.0))
    building, known = max(heights.in_building.items(), key=lambda item: len(item[1]))
    spot = layers.buildings.geometry.iloc[building].representative_point()
    levels = sorted(known)
    assert heights(spot.x, spot.y, levels[0]) == known[levels[0]]
    above = levels[-1] + 1
    assert heights(spot.x, spot.y, above) == pytest.approx(known[levels[-1]] + 4.0)


def test_what_has_no_height_is_left_out(maunula, maunula_frames):
    """What has no height on the terrain is left out: the floors, walls, columns,
    doors, shops and outlines; with no heights at all there is nothing to draw.
    Without a network the levels lie on the terrain."""

    def nowhere(*place):
        return np.nan

    assert indoor_groups(IndoorBox(maunula), (0.0, 0.0), nowhere, nowhere) == []

    def two_levels(x, y, level):
        return 10.0 * level if level < 2 else np.nan

    groups = {
        group["name"]: group
        for group in indoor_groups(IndoorBox(maunula), (0.0, 0.0), two_levels)
    }
    walls = groups["Walls (rooms and indoor=wall)"]["items"]
    assert walls and all(np.isfinite(item["h"]) for item in walls)
    assert {item["h"] for item in walls if item["l"] == 1.0} == {1.6}  # no full storey
    with pytest.raises(ValueError, match="no heights in the terrain model"):
        plot_indoor(**maunula_frames, dem=lambda lon, lat: np.full(len(lon), np.nan))
    flat = plot_indoor(maunula_frames["elements"], dem=lambda lon, lat: lon * 0 + 20)
    levels = {level: height for level, height, _ in flat.data["indoor"]["levels"]}
    assert levels == {0.0: 20.0, 1.0: 24.0, 2.0: 28.0}
