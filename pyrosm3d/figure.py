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

import math
from dataclasses import replace

import numpy as np
import plotly.graph_objects as go
import shapely

from pyrosm3d.columns import shaft_columns
from pyrosm3d.floors import (
    floor_levels,
    floor_openings,
    floors_between_levels,
    triangles,
)
from pyrosm3d.indoor import indoor_layers
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
    VIEW_MARGIN,
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


def plot_indoor(elements, edges=None, nodes=None, buildings=None, level=None):
    """A plotly Figure of indoor elements in 3D (see the module docstring), from frames
    read with pyrosm (``osm`` is a ``pyrosm.OSM`` object); ``osm.in3d.plot_indoor()``
    makes these reads itself.

    Parameters
    ----------
    elements : GeoDataFrame
        ``osm.get_indoor_elements(walking_areas=True)``. The figure shows the areas
        and what lies within 10 m of them; a walking area, such as a square or a
        pedestrian street, is drawn as far as the other areas' view reaches.
    edges, nodes : GeoDataFrame (optional)
        ``osm.get_network("walking", nodes=True, indoor_elements=True,
        walking_areas=True)``, drawn on its levels.
    buildings : GeoDataFrame (optional)
        ``osm.get_buildings()``, for the outlines.
    level : float (optional)
        Draw only what is on this level, without the columns of stairwells and lift
        shafts; by default all levels.

    Returns
    -------
    plotly.graph_objects.Figure
        A click on a legend entry hides or shows it. The outer walls, the doors and
        the shops are hidden until they are picked in the legend. As HTML the figure
        has the controls for touch screens of :class:`pyrosm3d.touch.TouchFigure`.
    """
    return layers_figure(indoor_layers(elements, nodes, edges, buildings), level)


def layers_figure(indoor, level=None):
    """The figure of :func:`plot_indoor` for the layers ``indoor`` (an IndoorLayers,
    see :func:`pyrosm3d.indoor.indoor_layers`)."""
    box = _view_box(indoor)
    view = shapely.box(*box)
    origin = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    indoor = replace(
        indoor,
        areas=_areas_inside(indoor.areas, view),
        walls=indoor.walls[indoor.walls.intersects(view)],
        doors=indoor.doors[indoor.doors.within(view)],
        pois=indoor.pois[indoor.pois.within(view)],
        edges=indoor.edges[indoor.edges.intersects(view)],
    )
    outer, level_floors = outer_walls(indoor, view)
    between = floors_between_levels(indoor.areas)
    platform_floors = _platform_floors(indoor.areas, view)
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
    return TouchFigure(traces, _layout(box, levels, between))


def _view_box(indoor):
    """``(west, south, east, north)`` of the view: the bounds of the areas other than
    walking areas, of the walking areas where there are no others, or of the network
    where there are no areas, with a margin."""
    areas = indoor.areas
    frames = (areas[areas["kind"] != "walking_area"], areas, indoor.edges)
    frame = next((frame for frame in frames if len(frame)), None)
    if frame is None:
        raise ValueError("plot_indoor got no areas and no network to draw.")
    west, south, east, north = frame.total_bounds
    return (
        west - VIEW_MARGIN,
        south - VIEW_MARGIN,
        east + VIEW_MARGIN,
        north + VIEW_MARGIN,
    )


def areas_in_view(indoor):
    """The areas of ``indoor`` (an IndoorLayers) that its figure draws: those with a
    part inside its view (see :func:`_view_box`, :func:`_areas_inside`)."""
    return _areas_inside(indoor.areas, shapely.box(*_view_box(indoor)))


def _areas_inside(areas, view):
    """The rows of ``areas`` with a part inside the box ``view`` (see
    :func:`_inside`). A walking area that lies outside the view of the other areas,
    or only touches it, is left out: it has no floor and no outline in the figure."""
    in_view = [bool(_inside(shape, view)) for shape in areas.geometry]
    return areas[np.array(in_view, dtype=bool)]


def _inside(shape, view):
    """The parts of ``shape``, a polygon or lines, inside the box ``view``: a list of
    polygons or of lines, empty where ``shape`` lies outside the box."""
    if view.contains(shape):
        return list(shapely.get_parts(shape))
    kind = "Polygon" if shape.geom_type.endswith("Polygon") else "LineString"
    parts = shapely.get_parts(shape.intersection(view))
    return [part for part in parts if part.geom_type == kind and not part.is_empty]


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


def _platform_floors(areas, view):
    """The keys of the platform areas among ``areas`` that have a floor in the box
    ``view`` (see :func:`pyrosm3d.tags.element_keys`)."""
    platforms = areas[(areas["kind"] == "platform") & areas.intersects(view)]
    columns = (element_keys(platforms), platforms["levels"])
    return {key for key, levels in zip(*columns) if floor_levels("platform", levels)}


def _network_traces(edges, origin, platform_floors=(), between=()):
    """The ``edges`` of the walking network as lines, one trace for each kind of edge
    (see :func:`pyrosm3d.plot_network`) and each set of levels an edge is shown on:
    the levels at its two ends, and for a level between two floors also the nearest
    whole level, unless an area has its floor there (the levels ``between``, see
    :func:`pyrosm3d.floors.floors_between_levels`). The platform edges of the
    elements among ``platform_floors`` (keys, see :func:`_platform_floors`) are left
    out: the outline of a platform mapped as a closed way is an edge, and its floor
    is drawn with an outline already."""
    lines = {kind: _LevelLines() for kind in _STYLES}
    kinds = zip(element_keys(edges), _edge_kinds(edges))
    for key, (row, tags, kind, level_u, level_v) in kinds:
        if kind == "platform" and key in platform_floors:
            continue
        z_u, z_v = (lv * FLOOR_HEIGHT + _NETWORK_LIFT for lv in (level_u, level_v))
        points = _line_points(row.geometry, z_u, z_v, origin, vertical=kind == "lift")
        ends = {float(level_u), float(level_v)}
        beside = {float(math.floor(end + 0.5)) for end in ends - set(between)}
        shown = sorted(ends | beside)
        text = _edge_text(row, tags, kind, level_u, level_v)
        lines[kind].add(shown, *points, text, key)
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
    :func:`plot_indoor` with all levels, and each level between two floors that an
    area has its floor on: the range and the ticks of the vertical axis and the aspect
    ratio of the scene that ``plot_indoor(level=...)`` gives that level, as plotly's
    ``relayout`` takes them."""
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
