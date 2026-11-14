from dataclasses import replace

import numpy as np
import pytest

from pyrosm3d import plot_indoor
from pyrosm3d.floors import floor_levels
from pyrosm3d.styles import AREA_STYLES


def _floor_area(trace):
    """The area of the triangles of a mesh trace, in square metres."""
    x, y = np.asarray(trace.x, float), np.asarray(trace.y, float)
    i, j, k = (np.asarray(corner) for corner in (trace.i, trace.j, trace.k))
    doubled = (x[j] - x[i]) * (y[k] - y[i]) - (x[k] - x[i]) * (y[j] - y[i])
    return np.abs(doubled).sum() / 2


def _levels(traces, name):
    """``{level: number of points}`` of the traces called ``name`` that are shown on
    one level."""
    return {
        trace.meta["levels"][0]: len(trace.x) for trace in traces if trace.name == name
    }


def test_plot_indoor_draws_maunula_talo(maunula):
    """The floors of each kind of area are plates 4 m apart that cover the areas (the
    lift shaft on each of its three levels; no floor for level outlines or a wall
    mapped as an area), with outlines and the network on their levels; each legend
    entry is listed once; doors and shops are markers on their levels, hidden at
    start; the vertical axis names the levels."""
    figure = plot_indoor(maunula)
    traces = figure.data
    areas = maunula.areas
    for kind, (name, colour, _) in AREA_STYLES.items():
        rows = areas[areas["kind"] == kind]
        floors = [t for t in traces if t.type == "mesh3d" and t.name == name]
        expected = sum(
            polygon.area * len(floor_levels(kind, levels))
            for polygon, levels in zip(rows.geometry, rows["levels"])
        )
        assert sum(map(_floor_area, floors)) == pytest.approx(expected, rel=1e-3)
        assert all(floor.color == colour for floor in floors)
        for floor in floors:
            assert set(floor.z) == {floor.meta["levels"][0] * 4.0}
    assert set(_levels(traces, "Rooms")) == {1.0, 2.0}
    assert set(_levels(traces, "Stairwells, lifts, storage")) == {0.0, 1.0, 2.0}
    assert set(_levels(traces, "Room and corridor outlines")) == {0.0, 1.0, 2.0}
    assert set(_levels(traces, "Lines across areas")) == {0.0, 1.0, 2.0}
    assert set(_levels(traces, "Platforms")) == {0.0}

    listed = [trace.name for trace in traces if trace.showlegend]
    assert listed == list(dict.fromkeys(trace.name for trace in traces))
    doors = [trace for trace in traces if trace.name == "Doors and entrances"]
    assert _levels(traces, "Doors and entrances") == {0.0: 1, 1.0: 39, 2.0: 29}
    assert _levels(traces, "Shops and amenities") == {0.0: 1, 1.0: 5, 2.0: 3}
    assert {door.visible for door in doors} == {"legendonly"}
    assert [set(door.z) for door in doors] == [{0.8}, {4.8}, {8.8}]
    axis = figure.layout.scene.zaxis
    assert (axis.tickvals, axis.ticktext) == ((0.0, 4.0, 8.0), ("0", "1", "2"))


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


def test_plot_indoor_without_areas(maunula):
    """Without areas the view is the network; without a network too there is nothing
    to draw."""
    no_areas = replace(maunula, areas=maunula.areas.iloc[:0])
    figure = plot_indoor(no_areas)
    assert {trace.type for trace in figure.data} == {"scatter3d"}
    assert "Walkways at street level" in [trace.name for trace in figure.data]
    with pytest.raises(ValueError, match="no areas and no network"):
        plot_indoor(replace(no_areas, edges=maunula.edges.iloc[:0]))
