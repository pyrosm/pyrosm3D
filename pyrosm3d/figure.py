"""A 3D view of the indoor elements of a place, drawn with plotly.

The floors of the areas are plates at the height of their level, 4 m for each level,
open where stairs, an escalator or a moving walkway rises through them, with the
outlines of the areas, the walking network, and the doors and shops as markers. Every
trace is shown on the levels in its ``meta["levels"]``.
"""

import math

import numpy as np
import plotly.graph_objects as go
import shapely

from pyrosm3d.floors import floor_levels, floor_openings, triangles
from pyrosm3d.network import (
    _STYLES,
    _Trace,
    _edge_kinds,
    _edge_text,
    _line_points,
    _lines,
)
from pyrosm3d.styles import (
    AREA_STYLES,
    DOOR_STYLE,
    FLOOR_HEIGHT,
    OUTLINE_COLOUR,
    POI_STYLE,
    VIEW_MARGIN,
    WALL_HEIGHT,
)

# Metres that outlines and network lines are drawn above their floor, to stay visible
_OUTLINE_LIFT = 0.05
_NETWORK_LIFT = 0.15
_POI_LIFT = 0.3
# A floor keeps its colour from every direction
_FLAT_LIGHT = dict(ambient=1, diffuse=0, specular=0, roughness=1, fresnel=0)
# How much taller than to scale the levels are drawn, so that they stand apart
_HEIGHT_STRETCH = 2.2


def plot_indoor(indoor, level=None):
    """A plotly Figure of indoor elements in 3D (see the module docstring).

    Parameters
    ----------
    indoor : IndoorElements
        The elements that :func:`pyrosm3d.read_indoor` returns. The figure shows the
        areas and what lies within 10 m of them.
    level : float (optional)
        Draw only what is on this level; by default all levels.

    Returns
    -------
    plotly.graph_objects.Figure
        A click on a legend entry hides or shows it. The doors and the shops are
        hidden until they are picked in the legend.
    """
    box = _view_box(indoor)
    view = shapely.box(*box)
    origin = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    doors = indoor.doors[indoor.doors.within(view)]
    pois = indoor.pois[indoor.pois.within(view)]
    edges = indoor.edges[indoor.edges.intersects(view)]
    traces = (
        _floor_traces(indoor.areas, floor_openings(edges), origin)
        + _outline_traces(indoor.areas, origin)
        + _network_traces(edges, origin)
        + _marker_traces(doors, DOOR_STYLE, WALL_HEIGHT / 2, origin)
        + _marker_traces(pois, POI_STYLE, _POI_LIFT, origin)
    )
    if level is not None:
        traces = [trace for trace in traces if level in trace.meta["levels"]]
    if not traces:
        raise ValueError(
            "plot_indoor got nothing to draw"
            + ("." if level is None else " on level %g." % level)
        )
    in_legend = set()
    for trace in traces:
        trace.showlegend = trace.legendgroup not in in_legend
        in_legend.add(trace.legendgroup)
    levels = sorted({float(lv) for trace in traces for lv in trace.meta["levels"]})
    return go.Figure(traces, _layout(box, levels))


def _view_box(indoor):
    """``(west, south, east, north)`` of the view: the bounds of the areas, or of the
    network where there are no areas, with a margin."""
    frame = indoor.areas if len(indoor.areas) else indoor.edges
    if frame.empty:
        raise ValueError("plot_indoor got no areas and no network to draw.")
    west, south, east, north = frame.total_bounds
    return (
        west - VIEW_MARGIN,
        south - VIEW_MARGIN,
        east + VIEW_MARGIN,
        north + VIEW_MARGIN,
    )


def _floor_traces(areas, openings, origin):
    """The floors of ``areas`` as meshes of triangles, one for each kind of area and
    level, the kinds in the order of ``AREA_STYLES``; a floor is open where the
    polygon of its level in ``openings`` crosses it."""
    floors = {}
    columns = (areas["kind"], areas["levels"], areas["tags"], areas.geometry)
    for kind, levels, tags, polygon in zip(*columns):
        if kind not in AREA_STYLES:
            continue
        name = tags.get("name") or tags.get("ref") or AREA_STYLES[kind][2]
        for level in floor_levels(kind, levels):
            floor = polygon
            if level in openings and polygon.intersects(openings[level]):
                floor = polygon.difference(openings[level])
            corners = triangles(floor).reshape(-1, 2) - origin
            xy, text = floors.setdefault((kind, level), ([], []))
            xy.append(corners)
            text += ["%s<br>level %g" % (name, level)] * len(corners)
    traces = []
    for kind, (name, colour, _) in AREA_STYLES.items():
        for level in sorted(level for key, level in floors if key == kind):
            xy, text = floors[(kind, level)]
            xy = np.round(np.concatenate(xy), 2)
            corner = np.arange(len(xy)).reshape(-1, 3)
            traces.append(
                go.Mesh3d(
                    x=xy[:, 0],
                    y=xy[:, 1],
                    z=np.full(len(xy), level * FLOOR_HEIGHT),
                    i=corner[:, 0],
                    j=corner[:, 1],
                    k=corner[:, 2],
                    color=colour,
                    name=name,
                    legendgroup=name,
                    flatshading=True,
                    lighting=_FLAT_LIGHT,
                    hoverinfo="text",
                    hovertext=text,
                    meta={"levels": [level]},
                )
            )
    return traces


class _LevelLines:
    """The lines of one legend entry, grouped by the levels they are shown on."""

    def __init__(self):
        self.by_levels = {}

    def add(self, levels, x, y, z, text):
        """Add a line through the points ``x``, ``y``, ``z`` that is shown on
        ``levels``, labelled ``text``."""
        self.by_levels.setdefault(tuple(levels), _Trace()).add(x, y, z, text)

    def traces(self, name, colour, width, dash="solid"):
        """A plotly line trace for each set of levels, lowest first."""
        traces = []
        for levels in sorted(self.by_levels):
            trace = _lines(self.by_levels[levels], name, colour, width, dash)
            traces.append(trace.update(meta={"levels": list(levels)}))
        return traces


def _outline_traces(areas, origin):
    """The outlines of the ``areas`` that have a floor, on each level of their
    floors."""
    lines = _LevelLines()
    for kind, levels, polygon in zip(areas["kind"], areas["levels"], areas.geometry):
        if kind not in AREA_STYLES:
            continue
        for level in floor_levels(kind, levels):
            z = level * FLOOR_HEIGHT + _OUTLINE_LIFT
            for ring in shapely.get_rings(shapely.get_parts(polygon)):
                lines.add([level], *_line_points(ring, z, z, origin), "outline")
    traces = lines.traces("Room and corridor outlines", OUTLINE_COLOUR, 1.5)
    return [trace.update(hoverinfo="skip", hovertemplate=None) for trace in traces]


def _network_traces(edges, origin):
    """The ``edges`` of the walking network as lines, one trace for each kind of edge
    (see :func:`pyrosm3d.plot_network`) and each set of levels an edge is shown on:
    the levels at its two ends, and for a level between two floors the nearest
    floor."""
    lines = {kind: _LevelLines() for kind in _STYLES}
    for row, tags, kind, level_u, level_v in _edge_kinds(edges):
        z_u, z_v = (lv * FLOOR_HEIGHT + _NETWORK_LIFT for lv in (level_u, level_v))
        points = _line_points(row.geometry, z_u, z_v, origin, vertical=kind == "lift")
        ends = {float(level_u), float(level_v)}
        shown = sorted(ends | {float(math.floor(end + 0.5)) for end in ends})
        lines[kind].add(shown, *points, _edge_text(row, tags, kind))
    traces = []
    for kind, (name, colour, width, dash) in _STYLES.items():
        traces += lines[kind].traces(name, colour, width, dash)
    return traces


def _marker_traces(points, style, lift, origin):
    """The ``points`` of a doors or pois layer as markers ``lift`` metres above their
    floor, one trace for each whole level, hidden until picked in the legend;
    ``style`` is ``DOOR_STYLE`` or ``POI_STYLE``."""
    name, colour, symbol, fallback = style
    by_level = {}
    for levels, tags, point in zip(points["levels"], points["tags"], points.geometry):
        label = tags.get("name") or tags.get("shop") or tags.get("amenity") or fallback
        for level in levels:
            if float(level).is_integer():
                x, y, text = by_level.setdefault(level, ([], [], []))
                x.append(round(point.x - origin[0], 2))
                y.append(round(point.y - origin[1], 2))
                text.append("%s<br>level %g" % (label, level))
    return [
        go.Scatter3d(
            x=x,
            y=y,
            z=[level * FLOOR_HEIGHT + lift] * len(x),
            text=text,
            mode="markers",
            name=name,
            legendgroup=name,
            visible="legendonly",
            marker=dict(size=3.5, symbol=symbol, color=colour),
            hovertemplate="%{text}<extra></extra>",
            meta={"levels": [level]},
        )
        for level, (x, y, text) in sorted(by_level.items())
    ]


def _layout(box, levels):
    """The layout of a figure of the view ``box`` (metres) whose traces are on
    ``levels`` (sorted): axes in metres from the middle of the box, the vertical axis
    from the lowest to the highest level and labelled with the whole levels, and the
    heights stretched."""
    width, height = box[2] - box[0], box[3] - box[1]
    longest = max(width, height)
    whole = [shown for shown in levels if shown.is_integer()]
    z_range = [levels[0] * FLOOR_HEIGHT - 1, levels[-1] * FLOOR_HEIGHT + 2]
    z_aspect = (z_range[1] - z_range[0]) * _HEIGHT_STRETCH / longest
    z_aspect = min(1.1, max(0.12, z_aspect))
    return dict(
        scene=dict(
            xaxis=dict(title="east (m)", range=[-width / 2, width / 2]),
            yaxis=dict(title="north (m)", range=[-height / 2, height / 2]),
            zaxis=dict(
                title="level",
                range=z_range,
                tickvals=[shown * FLOOR_HEIGHT for shown in whole],
                ticktext=["%g" % shown for shown in whole],
            ),
            aspectmode="manual",
            aspectratio=dict(x=width / longest, y=height / longest, z=z_aspect),
        ),
        legend=dict(itemclick="toggle"),
        margin=dict(l=0, r=0, t=30, b=0),
    )
