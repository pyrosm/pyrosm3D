"""A 3D view of the indoor elements of a place, drawn with plotly.

The floors of the areas are plates at the height of their level, 4 m for each level,
open where stairs, an escalator or a moving walkway rises through them, with the
outlines of the areas, of the levels and of the buildings that have no level outline,
the walking network, and the doors and shops as markers. The walls of rooms, and walls
mapped as lines or areas, are see-through panels cut away at 40 % of a storey, with a
gap at each door; outer walls stand a full storey high along the outlines of levels,
or of buildings without them. Stairwells and lift shafts are columns through the
floors that they join. Every trace is shown on the levels in its ``meta["levels"]``;
a column has none and is drawn only with all levels.
"""

import numpy as np
import plotly.graph_objects as go
import shapely

from pyrosm3d.columns import shaft_columns
from pyrosm3d.floors import floor_levels, floor_openings, triangles
from pyrosm3d.indoor_view import IndoorBox, _inside, shown_levels
from pyrosm3d.network import _STYLES, _edge_kinds, _edge_text, _line_points
from pyrosm3d.styles import (
    AREA_STYLES,
    AXIS_STYLE,
    BACKGROUND_COLOUR,
    CAMERA,
    COLUMN_STYLES,
    DOOR_STYLE,
    FLOOR_HEIGHT,
    HEIGHT_STRETCH,
    HOVER_LABEL,
    LEVEL_FLOOR_COLOUR,
    LEVEL_OUTLINE_COLOUR,
    OUTER_WALL_NAME,
    OUTLINE_COLOUR,
    POI_STYLE,
    WALL_HEIGHT,
    WALL_NAME,
    WALL_STYLE,
)
from pyrosm3d.tags import element_keys
from pyrosm3d.touch import TouchFigure
from pyrosm3d.walls import building_outlines, inner_walls, outer_walls, wall_panels

# Metres that outlines and network lines are drawn above their floor, to stay visible
_OUTLINE_LIFT = 0.05
_LEVEL_OUTLINE_LIFT = 0.1
_NETWORK_LIFT = 0.15
_POI_LIFT = 0.3
# A floor keeps its colour from every direction
_FLAT_LIGHT = dict(ambient=1, diffuse=0, specular=0, roughness=1, fresnel=0)


class _Trace:
    """The points of one legend entry, lines separated by gaps."""

    def __init__(self):
        self.x, self.y, self.z, self.text = [], [], [], []

    def add(self, x, y, z, text, in_metres=False):
        """Add one line through the points ``x``, ``y``, ``z`` (rounded to hundredths),
        labelled ``text``, and with the height of each point when ``z`` is
        ``in_metres``."""
        self.x += np.round(x, 2).tolist() + [None]
        self.y += np.round(y, 2).tolist() + [None]
        self.z += np.round(z, 2).tolist() + [None]
        if in_metres:
            self.text += ["%s<br>%.1f m" % (text, height) for height in z] + [None]
        else:
            self.text += [text] * len(x) + [None]


def _lines(trace, name, colour, width, dash):
    """A plotly line trace of the points of ``trace``, its own group in the legend."""
    return go.Scatter3d(
        x=trace.x,
        y=trace.y,
        z=trace.z,
        text=trace.text,
        mode="lines",
        name=name,
        legendgroup=name,
        line=dict(color=colour, width=width, dash=dash),
        hovertemplate="%{text}<extra></extra>",
    )


def layers_figure(indoor):
    """The plotly figure of the layers ``indoor`` (an IndoorLayers, see
    :func:`pyrosm3d.indoor.indoor_layers`) that the web page of
    :func:`pyrosm3d.to_html` shows (see the module docstring)."""
    shown = IndoorBox(indoor)
    box, view, indoor = shown.box, shown.shape, shown.indoor
    origin = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    outer, level_floors = outer_walls(indoor, view)
    between, platform_floors = shown.between, shown.platform_floors
    traces = (
        _floor_traces(indoor.areas, floor_openings(indoor.edges), origin, view)
        + _outline_traces(indoor.areas, origin, view)
        + _building_outline_traces(building_outlines(indoor, view), origin)
        + _wall_traces(inner_walls(indoor), WALL_NAME, origin)
        + _wall_traces(outer, OUTER_WALL_NAME, origin, hidden=True)
        + _level_floor_traces(level_floors, origin)
        + _column_traces(indoor, origin)
        + _network_traces(indoor.edges, origin, platform_floors, between)
        + _marker_traces(indoor.doors, DOOR_STYLE, WALL_HEIGHT / 2, origin, between)
        + _marker_traces(indoor.pois, POI_STYLE, _POI_LIFT, origin, between)
    )
    in_legend = set()
    for trace in traces:
        trace.showlegend = trace.legendgroup not in in_legend
        in_legend.add(trace.legendgroup)
    levels = sorted({float(lv) for trace in traces for lv in trace.meta["levels"]})
    return TouchFigure(traces, _layout(box, levels, between))


def _floor_traces(areas, openings, origin, view):
    """The floors of ``areas`` inside the box ``view`` as meshes of triangles, one for
    each kind of area and level, the kinds in the order of ``AREA_STYLES``; a floor is
    open where the polygon of its level in ``openings`` crosses it."""
    floors = {}
    columns = (areas["kind"], areas["levels"], areas["tags"], areas.geometry)
    for key, kind, levels, tags, polygon in zip(element_keys(areas), *columns):
        if kind not in AREA_STYLES:
            continue
        name = tags.get("name") or tags.get("ref") or AREA_STYLES[kind][2]
        polygon = shapely.MultiPolygon(_inside(polygon, view))
        for level in floor_levels(kind, levels) if not polygon.is_empty else ():
            floor = polygon
            if level in openings and polygon.intersects(openings[level]):
                floor = polygon.difference(openings[level])
            corners = triangles(floor).reshape(-1, 2) - origin
            xy, text, keys = floors.setdefault((kind, level), ([], [], []))
            xy.append(corners)
            text += ["%s<br>level %g" % (name, level)] * len(corners)
            keys += [key] * len(corners)
    traces = []
    for kind, (name, colour, _) in AREA_STYLES.items():
        for level in sorted(level for found, level in floors if found == kind):
            xy, text, keys = floors[(kind, level)]
            floor = _floor_mesh(xy, level, colour, name, legendgroup=name)
            floor.update(hoverinfo="text", hovertext=text, customdata=keys)
            traces.append(floor)
    return traces


class _LevelLines:
    """The lines of one legend entry, grouped by the levels they are shown on."""

    def __init__(self):
        self.by_levels = {}
        self.keys = {}

    def add(self, levels, x, y, z, text, key=None):
        """Add a line through the points ``x``, ``y``, ``z`` that is shown on
        ``levels``, labelled ``text``, of the element with the ``key``."""
        levels = tuple(levels)
        self.by_levels.setdefault(levels, _Trace()).add(x, y, z, text)
        self.keys.setdefault(levels, []).extend([key] * len(x) + [None])

    def traces(self, name, colour, width, dash="solid"):
        """A plotly line trace for each set of levels, lowest first, with the keys of
        the elements as ``customdata`` where lines have them."""
        traces = []
        for levels in sorted(self.by_levels):
            trace = _lines(self.by_levels[levels], name, colour, width, dash)
            trace.update(meta={"levels": list(levels)})
            if any(self.keys[levels]):
                trace.update(customdata=self.keys[levels])
            traces.append(trace)
        return traces


def _floor_mesh(corners, level, colour, name, lift=0.0, **more):
    """A flat mesh of the triangles whose corners are in ``corners`` (xy arrays, three
    rows for a triangle), ``lift`` metres above the height of ``level``."""
    xy = np.round(np.concatenate(corners), 2)
    corner = np.arange(len(xy)).reshape(-1, 3)
    return go.Mesh3d(
        x=xy[:, 0],
        y=xy[:, 1],
        z=np.full(len(xy), level * FLOOR_HEIGHT + lift),
        i=corner[:, 0],
        j=corner[:, 1],
        k=corner[:, 2],
        color=colour,
        name=name,
        flatshading=True,
        lighting=_FLAT_LIGHT,
        hoverinfo="skip",
        meta={"levels": [level]},
        **more,
    )


def _level_floor_traces(floors, origin):
    """The floors under the outer walls (``{level: polygons}``) as meshes just below
    the other floors, hidden and shown with the outer walls."""
    traces = []
    for level in sorted(floors):
        corners = [triangles(floor).reshape(-1, 2) - origin for floor in floors[level]]
        floor = _floor_mesh(corners, level, LEVEL_FLOOR_COLOUR, "Level floors", -0.05)
        traces.append(floor.update(legendgroup=OUTER_WALL_NAME, visible="legendonly"))
    return traces


def _wall_traces(walls, name, origin, hidden=False):
    """The walls of each level (``{level: panels}``, see
    :func:`pyrosm3d.walls.wall_panels`) as see-through meshes called ``name``, two
    triangles for a panel; ``hidden`` until picked in the legend."""
    traces = []
    for level in sorted(walls):
        corners = walls[level].reshape(-1, 3)
        first = np.arange(0, len(corners), 4)
        traces.append(
            go.Mesh3d(
                x=np.round(corners[:, 0] - origin[0], 2),
                y=np.round(corners[:, 1] - origin[1], 2),
                z=corners[:, 2],
                i=np.r_[first, first],
                j=np.r_[first + 1, first + 2],
                k=np.r_[first + 2, first + 3],
                name=name,
                legendgroup=name,
                hoverinfo="skip",
                visible="legendonly" if hidden else True,
                meta={"levels": [level]},
                **WALL_STYLE,
            )
        )
    return traces


def _column_traces(indoor, origin):
    """The stairwells and the lift shafts of ``indoor`` as see-through columns, a
    trace for each of the two (see :func:`pyrosm3d.columns.shaft_columns`): walls
    along a column's outline from its lowest floor to wall height on its highest, and
    a lid, with the key of the column's largest room as ``customdata``. A column
    passes through several levels, so its trace has no level."""
    traces = []
    for room, (name, colour, fallback) in COLUMN_STYLES.items():
        corners, text, keys, i, j, k = [], [], [], [], [], []
        for outline, bottom, top, levels, names, key in shaft_columns(indoor, room):
            z_low, z_high = bottom * FLOOR_HEIGHT, top * FLOOR_HEIGHT + WALL_HEIGHT
            ring = shapely.get_coordinates(outline.exterior)
            sides = wall_panels(ring, np.empty((0, 2)), z_low, z_high).reshape(-1, 3)
            lid = triangles(outline).reshape(-1, 2)
            lid = np.column_stack([lid, np.full(len(lid), z_high)])
            side = len(text) + np.arange(0, len(sides), 4)
            top_corner = len(text) + len(sides) + np.arange(0, len(lid), 3)
            i += [*side, *side, *top_corner]
            j += [*(side + 1), *(side + 2), *(top_corner + 1)]
            k += [*(side + 2), *(side + 3), *(top_corner + 2)]
            corners += [sides, lid]
            on_levels = ", ".join("%g" % level for level in levels)
            label = "%s<br>level %s" % (", ".join(names) or fallback, on_levels)
            text += [label] * (len(sides) + len(lid))
            keys += [key] * (len(sides) + len(lid))
        if corners:
            xyz = np.concatenate(corners)
            traces.append(
                go.Mesh3d(
                    x=np.round(xyz[:, 0] - origin[0], 2),
                    y=np.round(xyz[:, 1] - origin[1], 2),
                    z=xyz[:, 2],
                    i=i,
                    j=j,
                    k=k,
                    color=colour,
                    opacity=0.3,
                    name=name,
                    legendgroup=name,
                    flatshading=True,
                    lighting=_FLAT_LIGHT,
                    hoverinfo="text",
                    hovertext=text,
                    customdata=keys,
                    meta={"levels": []},
                )
            )
    return traces


def _outline_traces(areas, origin, view):
    """The outlines of the ``areas`` inside the box ``view`` as lines: of those that
    have a floor, on each level of their floors, and of the level outlines, on each of
    their levels."""
    rooms, levels = _LevelLines(), _LevelLines()
    for kind, on_levels, area in zip(areas["kind"], areas["levels"], areas.geometry):
        if kind == "level":
            lines, lift = levels, _LEVEL_OUTLINE_LIFT
        elif kind in AREA_STYLES:
            lines, lift, on_levels = rooms, _OUTLINE_LIFT, floor_levels(kind, on_levels)
        else:
            continue
        outline = _inside(area.boundary, view)
        for level in on_levels:
            z = level * FLOOR_HEIGHT + lift
            for line in outline:
                lines.add([level], *_line_points(line, z, z, origin), "outline")
    traces = rooms.traces("Room and corridor outlines", OUTLINE_COLOUR, 1.5)
    traces += levels.traces("Level outlines", LEVEL_OUTLINE_COLOUR, 2.5)
    return [trace.update(hoverinfo="skip", hovertemplate=None) for trace in traces]


def _building_outline_traces(outlines, origin):
    """The building outlines of each level (``{level: [xy arrays]}``, see
    :func:`pyrosm3d.walls.building_outlines`) as lines."""
    lines = _LevelLines()
    for level, paths in outlines.items():
        z = level * FLOOR_HEIGHT + _LEVEL_OUTLINE_LIFT
        for path in paths:
            heights = np.full(len(path), z)
            xy = path - origin
            lines.add([level], xy[:, 0], xy[:, 1], heights, "outline")
    traces = lines.traces("Building outlines", LEVEL_OUTLINE_COLOUR, 2)
    return [trace.update(hoverinfo="skip", hovertemplate=None) for trace in traces]


def _network_traces(edges, origin, platform_floors=(), between=()):
    """The ``edges`` of the walking network as lines, one trace for each kind of edge
    (see :func:`pyrosm3d.plot_network`) and each set of levels an edge is shown on:
    those of :func:`pyrosm3d.indoor_view.shown_levels` with the levels ``between``.
    The platform edges of the elements among ``platform_floors`` (keys, see
    :class:`pyrosm3d.indoor_view.IndoorBox`) are left out: the outline of a platform
    mapped as a closed way is an edge, and its floor is drawn with an outline
    already."""
    lines = {kind: _LevelLines() for kind in _STYLES}
    kinds = zip(element_keys(edges), _edge_kinds(edges))
    for key, (row, tags, kind, level_u, level_v) in kinds:
        if kind == "platform" and key in platform_floors:
            continue
        z_u, z_v = (lv * FLOOR_HEIGHT + _NETWORK_LIFT for lv in (level_u, level_v))
        points = _line_points(row.geometry, z_u, z_v, origin, vertical=kind == "lift")
        text = _edge_text(row, tags, kind, level_u, level_v)
        lines[kind].add(shown_levels(level_u, level_v, between), *points, text, key)
    traces = []
    for kind, (name, colour, width, dash) in _STYLES.items():
        traces += lines[kind].traces(name, colour, width, dash)
    return traces


def _marker_traces(points, style, lift, origin, between=()):
    """The ``points`` of a doors or pois layer as markers ``lift`` metres above their
    floor, one trace for each whole level and each of the levels ``between`` (see
    :func:`pyrosm3d.floors.floors_between_levels`), hidden until picked in the legend;
    ``style`` is ``DOOR_STYLE`` or ``POI_STYLE``."""
    name, colour, symbol, fallback = style
    by_level = {}
    columns = (points["levels"], points["tags"], points.geometry)
    for key, levels, tags, point in zip(element_keys(points), *columns):
        label = tags.get("name") or tags.get("shop") or tags.get("amenity") or fallback
        for level in levels:
            if float(level).is_integer() or level in between:
                x, y, text, keys = by_level.setdefault(level, ([], [], [], []))
                x.append(round(point.x - origin[0], 2))
                y.append(round(point.y - origin[1], 2))
                text.append("%s<br>level %g" % (label, level))
                keys.append(key)
    return [
        go.Scatter3d(
            x=x,
            y=y,
            z=[level * FLOOR_HEIGHT + lift] * len(x),
            text=text,
            customdata=keys,
            mode="markers",
            name=name,
            legendgroup=name,
            visible="legendonly",
            marker=dict(size=3.5, symbol=symbol, color=colour),
            hovertemplate="%{text}<extra></extra>",
            meta={"levels": [level]},
        )
        for level, (x, y, text, keys) in sorted(by_level.items())
    ]


def level_views(figure):
    """``{level: scene}`` for each whole level of ``figure``, a figure of
    :func:`layers_figure`, and each level between two floors that an area has its
    floor on: the range and the ticks of the vertical axis and the aspect ratio of the
    scene of what is on that level alone, as plotly's ``relayout`` takes them."""
    scene = figure.layout.scene
    (west, east), (south, north) = scene.xaxis.range, scene.yaxis.range
    on_levels = [trace.meta["levels"] for trace in figure.data]
    whole = {lv for levels in on_levels for lv in levels if float(lv).is_integer()}
    floor_names = {name for name, _, _ in AREA_STYLES.values()}
    floors = [trace for trace in figure.data if trace.legendgroup in floor_names]
    between = {lv for trace in floors for lv in trace.meta["levels"]} - whole
    views = {}
    for level in sorted(whole | between):
        shown = sorted({lv for levels in on_levels if level in levels for lv in levels})
        scene = _layout((west, south, east, north), shown, between)["scene"]
        views[level] = {
            "scene.zaxis.range": scene["zaxis"]["range"],
            "scene.zaxis.tickvals": scene["zaxis"]["tickvals"],
            "scene.zaxis.ticktext": scene["zaxis"]["ticktext"],
            "scene.aspectratio": scene["aspectratio"],
        }
    return views


def _layout(box, levels, between=()):
    """The layout of a figure of the view ``box`` (metres) whose traces are on
    ``levels`` (sorted): axes in metres from the middle of the box, the vertical axis
    from the lowest to the highest level and labelled with the whole levels and those
    of the levels ``between`` (see :func:`pyrosm3d.floors.floors_between_levels`),
    and the heights stretched; a white scene without axis panes, seen from the
    south-east, that turns about its vertical axis."""
    width, height = box[2] - box[0], box[3] - box[1]
    longest = max(width, height)
    labelled = [lv for lv in levels if lv.is_integer() or lv in between]
    z_range = [levels[0] * FLOOR_HEIGHT - 1, levels[-1] * FLOOR_HEIGHT + 2]
    z_aspect = (z_range[1] - z_range[0]) * HEIGHT_STRETCH / longest
    z_aspect = min(1.1, max(0.12, z_aspect))
    return dict(
        scene=dict(
            xaxis=dict(
                title_text="east (m)", range=[-width / 2, width / 2], **AXIS_STYLE
            ),
            yaxis=dict(
                title_text="north (m)", range=[-height / 2, height / 2], **AXIS_STYLE
            ),
            zaxis=dict(
                title_text="level",
                range=z_range,
                tickvals=[shown * FLOOR_HEIGHT for shown in labelled],
                ticktext=["%g" % shown for shown in labelled],
                **AXIS_STYLE,
            ),
            aspectmode="manual",
            aspectratio=dict(x=width / longest, y=height / longest, z=z_aspect),
            camera=CAMERA,
            dragmode="turntable",
            bgcolor=BACKGROUND_COLOUR,
        ),
        paper_bgcolor=BACKGROUND_COLOUR,
        hoverlabel=HOVER_LABEL,
        legend=dict(itemclick="toggle"),
        margin=dict(l=0, r=0, t=30, b=0),
    )
