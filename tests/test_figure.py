from dataclasses import replace

import numpy as np
import pytest
from shapely.geometry import box

from pyrosm3d import plot_indoor
from pyrosm3d.floors import floor_levels, floor_openings
from pyrosm3d.styles import AREA_STYLES, VIEW_MARGIN
from pyrosm3d.tags import crosses_area, element_keys


def _floor_area(trace):
    """The area of the triangles of a mesh trace, in square metres."""
    x, y = np.asarray(trace.x, float), np.asarray(trace.y, float)
    i, j, k = (np.asarray(corner) for corner in (trace.i, trace.j, trace.k))
    doubled = (x[j] - x[i]) * (y[k] - y[i]) - (x[k] - x[i]) * (y[j] - y[i])
    return np.abs(doubled).sum() / 2


def _line_length(trace):
    """The length of the lines of a line trace on the ground, in metres."""
    x, y = np.asarray(trace.x, float), np.asarray(trace.y, float)
    return np.nansum(np.hypot(np.diff(x), np.diff(y)))


def _view(areas):
    """The box that a figure of ``areas`` shows: the bounds of the areas other than
    walking areas, with the margin."""
    west, south, east, north = areas[areas["kind"] != "walking_area"].total_bounds
    margin = VIEW_MARGIN
    return box(west - margin, south - margin, east + margin, north + margin)


def _levels(traces, name):
    """``{level: number of points}`` of the traces called ``name`` that are shown on
    one level."""
    return {
        trace.meta["levels"][0]: len(trace.x) for trace in traces if trace.name == name
    }


def test_plot_indoor_draws_maunula_talo(maunula):
    """The floors of each kind of area are plates 4 m apart, one for each area and
    floor level, that cover the areas to within the rounding of the drawn corners
    (0.01 m, so at most 0.01 m2 for a metre of outline): the lift shaft on each of
    its three levels, the platform areas and the square that lines cross on street
    level; no floor for level outlines or a wall mapped as an area. The square
    reaches past the view of the other areas and is drawn, with its outline, as far
    as the view goes. The outlines and the network are on their levels; each legend
    entry is listed once; doors and shops are markers on their levels, hidden at
    start; the vertical axis names the levels."""
    figure = plot_indoor(maunula)
    traces = figure.data
    assert all(len(t.x) == len(t.y) == len(t.z) for t in traces)
    areas = maunula.areas
    view = _view(areas)
    square = areas[areas["kind"] == "walking_area"].geometry.iloc[0]
    assert square.area == pytest.approx(579.9, abs=0.1)
    assert square.intersection(view).area == pytest.approx(378.2, abs=0.1)
    west, _, east, _ = view.bounds
    half = (east - west) / 2
    assert figure.layout.scene.xaxis.range == pytest.approx((-half, half))
    areas = areas.assign(geometry=areas.intersection(view))
    for kind, (name, colour, _) in AREA_STYLES.items():
        rows = areas[areas["kind"] == kind]
        floors = [t for t in traces if t.type == "mesh3d" and t.name == name]
        on_levels = [floor_levels(kind, levels) for levels in rows["levels"]]
        drawn = {(key, t.meta["levels"][0]) for t in floors for key in t.customdata}
        assert drawn == {
            (key, level)
            for key, levels in zip(element_keys(rows), on_levels)
            for level in levels
        }
        columns = (rows.geometry.area, rows.geometry.length, on_levels)
        expected = sum(area * len(levels) for area, _, levels in zip(*columns))
        outline = sum(length * len(levels) for _, length, levels in zip(*columns))
        assert abs(sum(map(_floor_area, floors)) - expected) <= 0.01 * outline
        assert all(floor.color == colour for floor in floors)
        for floor in floors:
            assert set(floor.z) == {floor.meta["levels"][0] * 4.0}
    assert set(_levels(traces, "Rooms")) == {1.0, 2.0}
    assert set(_levels(traces, "Stairwells, lifts, storage")) == {0.0, 1.0, 2.0}
    assert set(_levels(traces, "Platform areas")) == {0.0}
    assert set(_levels(traces, "Walking areas")) == {0.0}
    assert set(_levels(traces, "Room and corridor outlines")) == {0.0, 1.0, 2.0}
    outlines = [t for t in traces if t.name == "Room and corridor outlines"]
    with_floor = maunula.areas[maunula.areas["kind"].isin(list(AREA_STYLES))]
    columns = (with_floor["kind"], with_floor["levels"], with_floor.boundary)
    expected = sum(
        outline.intersection(view).length * len(floor_levels(kind, levels))
        for kind, levels, outline in zip(*columns)
    )
    assert sum(map(_line_length, outlines)) == pytest.approx(expected, abs=1.0)
    assert set(_levels(traces, "Lines across areas")) == {0.0, 1.0, 2.0}
    assert "Platforms" not in {trace.name for trace in traces}

    listed = [trace.legendgroup for trace in traces if trace.showlegend]
    assert listed == list(dict.fromkeys(trace.legendgroup for trace in traces))
    walls = [t for t in traces if t.name == "Walls (rooms and indoor=wall)"]
    assert [wall.meta["levels"] for wall in walls] == [[0.0], [1.0], [2.0]]
    assert [(min(wall.z), max(wall.z)) for wall in walls][1] == (4.0, 5.6)
    assert len(walls[1].i) == 2 * len(walls[1].x) / 4
    outer = [t for t in traces if t.legendgroup.startswith("Outer walls")]
    assert {trace.visible for trace in outer} == {"legendonly"}
    assert [trace.name for trace in outer if trace.showlegend] == [outer[0].name]
    columns = [trace for trace in traces if not trace.meta["levels"]]
    assert [trace.name.split(" (")[0] for trace in columns] == [
        "Stairwells",
        "Lift shafts",
    ]
    assert [(min(trace.z), max(trace.z)) for trace in columns] == [
        (4.0, 9.6),
        (0.0, 9.6),
    ]
    assert set(columns[1].customdata) == {"way 1568797319"}
    stairs = next(trace for trace in traces if trace.name == "Stairs")
    assert stairs.text[0] == "Stairs<br>way 674689746 · steps<br>level 0"
    outlines = [trace for trace in traces if trace.name == "Level outlines"]
    assert [outline.meta["levels"] for outline in outlines] == [[0.0], [1.0], [2.0]]
    assert {z for z in outlines[2].z if z is not None} == {8.1}
    assert "Building outlines" not in {trace.name for trace in traces}
    rooms = replace(maunula, areas=maunula.areas[maunula.areas["kind"] != "level"])
    outlines = [t for t in plot_indoor(rooms).data if t.name == "Building outlines"]
    assert [outline.meta["levels"] for outline in outlines] == [[0.0], [1.0], [2.0]]
    assert {z for z in outlines[1].z if z is not None} == {4.1}
    assert {outline.hoverinfo for outline in outlines} == {"skip"}
    level_floors = _levels(traces, "Level floors")
    assert set(level_floors) == {0.0, 1.0, 2.0}
    assert {t.z[0] for t in outer if t.name == "Level floors"} == {-0.05, 3.95, 7.95}
    doors = [trace for trace in traces if trace.name == "Doors and entrances"]
    assert _levels(traces, "Doors and entrances") == {0.0: 1, 1.0: 39, 2.0: 29}
    assert _levels(traces, "Shops and amenities") == {0.0: 1, 1.0: 5, 2.0: 3}
    assert {door.visible for door in doors} == {"legendonly"}
    assert [set(door.z) for door in doors] == [{0.8}, {4.8}, {8.8}]
    scene = figure.layout.scene
    assert (scene.zaxis.tickvals, scene.zaxis.ticktext) == (
        (0.0, 4.0, 8.0),
        ("0", "1", "2"),
    )
    eye = scene.camera.eye
    assert eye.x > 0 > eye.y and eye.z > 0  # seen from the south-east and above
    assert scene.dragmode == "turntable"
    for axis in (scene.xaxis, scene.yaxis, scene.zaxis):
        assert axis.showbackground is False and axis.gridcolor == "#d6dbe1"
    assert scene.yaxis.title.text == "north (m)" and scene.yaxis.title.font.size == 11
    assert scene.bgcolor == figure.layout.paper_bgcolor == "#ffffff"
    assert figure.layout.hoverlabel.bgcolor == "#ffffff"


def test_plot_indoor_draws_one_level(maunula):
    """With a level, only what is on it is drawn: the first floor of Maunula-talo has
    no platforms or streets; a door on a level between two floors is drawn on its
    whole level only; an edge half a level below the floor is drawn too, with the
    vertical axis reaching down to it; a level with nothing on it is refused."""
    on_first = maunula.doors["levels"].map(lambda levels: levels == (1.0,))
    doors = maunula.doors[on_first].iloc[:1].assign(levels=[(0.5, 1.0)])
    edges = maunula.edges.copy()
    row = edges.index[(edges["u_level"] == 1) & (edges["v_level"] == 1)][0]
    edges.loc[row, ["u_level", "v_level"]] = 0.5
    figure = plot_indoor(replace(maunula, doors=doors, edges=edges), level=1)
    assert all(1.0 in trace.meta["levels"] for trace in figure.data)
    names = [trace.name for trace in figure.data]
    assert "Rooms" in names and "Toilets" in names
    assert "Platforms" not in names and "Walkways at street level" not in names
    assert _levels(figure.data, "Doors and entrances") == {1.0: 1}
    (half,) = [trace for trace in figure.data if trace.meta["levels"] == [0.5, 1.0]]
    assert {z for z in half.z if z is not None} == {2.15}
    axis = figure.layout.scene.zaxis
    assert (tuple(axis.range), axis.ticktext) == ((1.0, 6.0), ("1",))
    with pytest.raises(ValueError, match="nothing to draw on level 5"):
        plot_indoor(maunula, level=5)


def test_plot_indoor_opens_floors_for_stairs(maunula):
    """Where stairs climb from the first to the second floor, the floors of the second
    floor are open along them: they are drawn smaller by what the opening takes of
    the areas."""
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

    def second_floor(figure):
        floors = [t for t in figure.data if t.type == "mesh3d"]
        return sum(_floor_area(t) for t in floors if t.meta["levels"] == [2.0])

    closed = second_floor(plot_indoor(maunula))
    opened = second_floor(plot_indoor(replace(maunula, edges=edges)))
    assert closed - opened == pytest.approx(taken, rel=0.01)


def test_plot_indoor_draws_platform_lines_without_a_floor(maunula):
    """The outline of a platform mapped as a closed way is an edge of the network.
    Where the platform has a floor, with an outline of its own, the edge is not drawn
    as a "Platforms" line; without the floor it is, where it reaches the view."""
    areas, edges = maunula.areas, maunula.edges
    no_floors = replace(maunula, areas=areas[areas["kind"] != "platform"])
    lines = [t for t in plot_indoor(no_floors).data if t.name == "Platforms"]
    assert [line.meta["levels"] for line in lines] == [[0.0]]
    platforms = set(element_keys(areas[areas["kind"] == "platform"]))
    of_platform = np.array([key in platforms for key in element_keys(edges)])
    outlines = edges[of_platform & ~crosses_area(edges)]
    assert len(outlines) == 27
    in_view = outlines[outlines.intersects(_view(no_floors.areas))]
    assert _line_length(lines[0]) == pytest.approx(in_view.length.sum(), abs=0.5)
    assert "Platforms" not in {trace.name for trace in plot_indoor(maunula).data}


def test_plot_indoor_view_follows_the_other_areas(maunula):
    """A walking area does not widen the view: one that lies outside the view of the
    other areas has no floor and no outline. Where the walking areas are the only
    areas, the view is theirs and their floors are whole."""
    areas = maunula.areas
    is_square = areas["kind"] == "walking_area"
    far = areas.assign(geometry=areas.geometry.where(~is_square, areas.translate(5000)))
    figure = plot_indoor(replace(maunula, areas=far))
    assert "Walking areas" not in {trace.name for trace in figure.data}
    assert all(len(t.x) == len(t.y) == len(t.z) for t in figure.data)
    unmoved = plot_indoor(maunula)
    assert figure.layout.scene.xaxis.range == unmoved.layout.scene.xaxis.range

    figure = plot_indoor(replace(maunula, areas=areas[is_square]))
    (floor,) = [trace for trace in figure.data if trace.name == "Walking areas"]
    square = areas[is_square].geometry.iloc[0]
    assert _floor_area(floor) == pytest.approx(square.area, abs=0.01 * square.length)
    west, _, east, _ = square.bounds
    axis = figure.layout.scene.xaxis
    assert axis.range[1] - axis.range[0] == pytest.approx(east - west + 2 * VIEW_MARGIN)


def test_plot_indoor_without_areas(maunula):
    """Without areas the view is the network, and a wall mapped as a line is still
    drawn, unless it lies outside the view; without a network too there is nothing to
    draw."""
    no_areas = replace(maunula, areas=maunula.areas.iloc[:0])
    figure = plot_indoor(no_areas)
    meshes = [trace.name for trace in figure.data if trace.type == "mesh3d"]
    assert meshes == ["Walls (rooms and indoor=wall)"]
    far = maunula.walls.assign(levels=[(7.0,)])
    far.geometry = far.translate(5000, 0)
    figure = plot_indoor(replace(no_areas, walls=far))
    assert {trace.type for trace in figure.data} == {"scatter3d"}
    with pytest.raises(ValueError, match="nothing to draw on level 7"):
        plot_indoor(replace(maunula, walls=far), level=7)
    assert "Walkways at street level" in [trace.name for trace in figure.data]
    with pytest.raises(ValueError, match="no areas and no network"):
        plot_indoor(replace(no_areas, edges=maunula.edges.iloc[:0]))
