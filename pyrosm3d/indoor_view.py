"""The indoor elements of a place as the groups of a 3D view (see
:class:`pyrosm3d.View`), at heights in metres.

The view shows the areas and what lies within 10 m of them: the floors of the areas,
open where stairs, an escalator or a moving walkway rises through them, with their
outlines; the walls of rooms, and walls mapped as lines or areas, as thin see-through
blocks cut away at 40 % of a storey, with a gap at each door; stairwells and lift
shafts as see-through columns; doors and shops as points, off at the start. The
indoor view alone also draws the outlines of levels and of buildings, and the outer
walls, a full storey high along those outlines, over the floors of their levels, both
off at the start. Each item on one level carries it (``l``), for the level picker of
the indoor view; a column through several floors has none.
"""

from dataclasses import replace

import numpy as np
import shapely

from pyrosm3d.columns import shaft_columns
from pyrosm3d.floors import floor_levels, floor_openings, floors_between_levels
from pyrosm3d.indoor import indoor_layers
from pyrosm3d.network import (
    _edge_kinds,
    _edge_points,
    _flat_ground,
    _NetworkLines,
    _start_view,
)
from pyrosm3d.styles import (
    AREA_STYLES,
    BACKGROUND_COLOUR,
    COLUMN_STYLES,
    DOOR_STYLE,
    FLOOR_HEIGHT,
    HEIGHT_STRETCH,
    LEVEL_FLOOR_COLOUR,
    LEVEL_OUTLINE_COLOUR,
    OUTER_WALL_NAME,
    OUTLINE_COLOUR,
    POI_STYLE,
    VIEW_MARGIN,
    WALL_HEIGHT,
    WALL_NAME,
    WALL_STYLE,
    metres_of_levels,
)
from pyrosm3d.tags import element_keys
from pyrosm3d.view import View
from pyrosm3d.walls import building_outlines, inner_walls, outer_walls

# Metres that a wall is thick
_WALL_THICKNESS = 0.12
# How opaque (0 to 255) each face of a wall is: a look through a wall passes two faces
# of its block, which together tint as much as one panel of WALL_STYLE's opacity
_WALL_ALPHA = round(255 * (1 - (1 - WALL_STYLE["opacity"]) ** 0.5))
_COLUMN_ALPHA = 77
# Metres under the height of its level that a floor lies, so that the lines of the
# network stay on it, and that the floor of a whole level lies under that
_FLOOR_DROP = 0.15
_LEVEL_FLOOR_DROP = 0.25
# Metres under the height of its level that the outline of a level or a building lies:
# over the floors, under the lines of the network
_OUTLINE_DROP = 0.05
# Metres over their floor that doors and shops stand
_DOOR_LIFT, _POI_LIFT = WALL_HEIGHT / 2, 0.3
# Pixels that outlines are wide in the indoor view: of rooms and corridors, of levels,
# of buildings
_ROOM_OUTLINE, _LEVEL_OUTLINE, _BUILDING_OUTLINE = 1.5, 2.5, 2.0
# The drawn height of the indoor view, 1 m under its lowest level to 2 m over its
# highest, stays between these shares of the longest side of its box
_LOWEST_SHARE, _HIGHEST_SHARE = 0.12, 1.1


def level_heights(x, y, level):
    """The height in metres of ``level`` at the place ``x``, ``y``: that of
    :func:`pyrosm3d.styles.metres_of_levels`, the same everywhere."""
    return float(metres_of_levels(level))


def levels_text(levels):
    """``"level 1"``, ``"levels 1, 2"`` or ``"no level"`` for the ``levels`` of an
    element."""
    if not levels:
        return "no level"
    listed = ", ".join("%g" % level for level in levels)
    return ("level %s" if len(levels) == 1 else "levels %s") % listed


def _view_box(indoor):
    """``(west, south, east, north)`` of the indoor view: the bounds of the areas other
    than walking areas, of the walking areas where there are no others, or of the
    network where there are no areas, with a margin."""
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
    """The areas of ``indoor`` (an IndoorLayers) that its indoor view draws: those with
    a part inside its box (see :func:`_view_box`, :func:`_areas_inside`)."""
    return _areas_inside(indoor.areas, shapely.box(*_view_box(indoor)))


def _areas_inside(areas, view):
    """The rows of ``areas`` with a part inside the box ``view`` (see
    :func:`_inside`). A walking area that lies outside the view of the other areas,
    or only touches it, is left out: it has no floor and no outline in the view."""
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


def _platform_floors(areas, view):
    """The keys of the platform areas among ``areas`` that have a floor in the box
    ``view`` (see :func:`pyrosm3d.tags.element_keys`)."""
    platforms = areas[(areas["kind"] == "platform") & areas.intersects(view)]
    columns = (element_keys(platforms), platforms["levels"])
    return {key for key, levels in zip(*columns) if floor_levels("platform", levels)}


def shown_levels(level_u, level_v, between):
    """The levels on which the indoor view shows an edge from ``level_u`` to
    ``level_v``: those of its ends, and for an end between two floors also the nearest
    whole level, unless an area has its floor there (one of the levels ``between``)."""
    ends = {float(level_u), float(level_v)}
    beside = {float(np.floor(end + 0.5)) for end in ends - set(between)}
    return sorted(ends | beside)


class IndoorBox:
    """What the indoor view shows of ``indoor`` (an IndoorLayers).

    Attributes
    ----------
    box : tuple
        ``(west, south, east, north)`` in metres (see :func:`_view_box`).
    shape : shapely.Polygon
        The box.
    indoor : IndoorLayers
        The layers inside the box: the areas with a part in it, the walls and the edges
        that cross it, the doors and the shops in it.
    between : set
        The levels that are not whole on which an area has its floor.
    platform_floors : set
        The keys of the platform areas that have a floor in the box: the outline of
        such a platform, mapped as a closed way, is an edge that the view leaves out.
    """

    def __init__(self, indoor):
        self.box = _view_box(indoor)
        self.shape = shapely.box(*self.box)
        self.indoor = replace(
            indoor,
            areas=_areas_inside(indoor.areas, self.shape),
            walls=indoor.walls[indoor.walls.intersects(self.shape)],
            doors=indoor.doors[indoor.doors.within(self.shape)],
            pois=indoor.pois[indoor.pois.within(self.shape)],
            edges=indoor.edges[indoor.edges.intersects(self.shape)],
        )
        self.between = floors_between_levels(self.indoor.areas)
        self.platform_floors = _platform_floors(self.indoor.areas, self.shape)


def indoor_stretch(box, low, high):
    """How much taller than to scale the indoor view of ``box`` (west, south, east,
    north in metres) draws its heights from ``low`` to ``high`` metres:
    ``HEIGHT_STRETCH``, as far as its drawn height, 1 m under ``low`` to 2 m over
    ``high``, then stays between ``_LOWEST_SHARE`` and ``_HIGHEST_SHARE`` of the
    longest side of the box."""
    west, south, east, north = box
    longest = max(east - west, north - south)
    tall = high - low + 3.0
    share = min(_HIGHEST_SHARE, max(_LOWEST_SHARE, tall * HEIGHT_STRETCH / longest))
    return share * longest / tall


def _polygons(shape):
    """The polygons of ``shape`` as a MultiPolygon, empty when it has none."""
    parts = shapely.get_parts(shape)
    return shapely.MultiPolygon(
        [part for part in parts if part.geom_type == "Polygon" and not part.is_empty]
    )


def _rings(shape, z, origin):
    """The rings of each polygon of ``shape`` (in metres) as lists of ``[x, y, z]``
    points in metres from ``origin``, at the height ``z``."""
    found = []
    for polygon in shapely.get_parts(shape):
        rings = []
        for ring in (polygon.exterior, *polygon.interiors):
            xy = shapely.get_coordinates(ring) - origin
            rings.append(np.column_stack([xy, np.full(len(xy), z)]).round(2).tolist())
        found.append(rings)
    return found


def _floor_groups(view, heights, origin):
    """The floors of the areas of ``view`` (an IndoorBox), a group for each kind of
    ``AREA_STYLES``, in their order: on each level of
    :func:`pyrosm3d.floors.floor_levels`, inside the box, open where
    :func:`pyrosm3d.floors.floor_openings` says, at the height that ``heights`` gives
    the level at the area, with outlines."""
    areas = view.indoor.areas
    openings = floor_openings(view.indoor.edges)
    items = {kind: [] for kind in AREA_STYLES}
    columns = (areas["kind"], areas["levels"], areas["tags"], areas.geometry)
    for key, kind, levels, tags, area in zip(element_keys(areas), *columns):
        if kind not in AREA_STYLES:
            continue
        polygon = _polygons(_inside(area, view.shape))
        spot = polygon.representative_point()
        for level in floor_levels(kind, levels):
            floor = polygon
            if level in openings and polygon.intersects(openings[level]):
                floor = _polygons(polygon.difference(openings[level]))
            name = tags.get("name") or tags.get("ref")
            what = (name, AREA_STYLES[kind][2], "%s · level %g" % (key, level))
            text = "\n".join(filter(None, what))
            z = heights(spot.x, spot.y, level) - _FLOOR_DROP
            items[kind] += [
                {"r": rings, "k": kind, "t": text, "l": float(level)}
                for rings in _rings(floor, z, origin)
            ]
    return [
        dict(
            name=name,
            kind="floors",
            colour=colour,
            colours={kind: colour},
            edge=OUTLINE_COLOUR,
            alpha=235,
            throughAlpha=170,
            edgeAlpha=170,
            edgeWidth=0.7,
            plotEdge=_ROOM_OUTLINE,
            visible=True,
            items=items[kind],
        )
        for kind, (name, colour, _) in AREA_STYLES.items()
    ]


def _wall_items(walls, heights, origin):
    """The walls of each level (``{level: panels}``, see
    :func:`pyrosm3d.walls.wall_panels`) as items: each panel a thin block from the
    height that ``heights`` gives its level at its middle, as high as the panel; a
    panel a full storey high reaches the height of the next level."""
    items = []
    for level, panels in sorted(walls.items()):
        for panel in panels:
            start, end = panel[0, :2], panel[1, :2]
            middle = (start + end) / 2
            low = heights(middle[0], middle[1], level)
            tall = panel[2, 2] - panel[0, 2]
            if tall >= FLOOR_HEIGHT - 0.01:
                tall = heights(middle[0], middle[1], level + 1) - low
            along = (end - start) / np.hypot(*(end - start))
            side = np.array([-along[1], along[0]]) * _WALL_THICKNESS / 2
            corners = [start + side, end + side, end - side, start - side]
            xy = np.array(corners + corners[:1]) - origin
            ring = np.column_stack([xy, np.full(5, low)]).round(2).tolist()
            items.append({"r": [ring], "h": round(float(tall), 2), "l": float(level)})
    return items


def _level_floor_items(floors, heights, origin):
    """The floors under the outer walls (``{level: polygons}``, see
    :func:`pyrosm3d.walls.outer_walls`) as items, under the floors of the areas on
    their level."""
    items = []
    for level, polygons in sorted(floors.items()):
        for polygon in polygons:
            spot = polygon.representative_point()
            z = heights(spot.x, spot.y, level) - _FLOOR_DROP - _LEVEL_FLOOR_DROP
            text = "Floor of level %g" % level
            items += [
                {"r": rings, "k": "level", "t": text, "l": float(level)}
                for rings in _rings(polygon, z, origin)
            ]
    return items


def _column_groups(indoor, heights, origin):
    """The stairwells and the lift shafts of ``indoor`` (an IndoorLayers) as see-through
    columns, a group for each of the two (see :func:`pyrosm3d.columns.shaft_columns`):
    from the height of the lowest floor of a column to wall height over its highest,
    along the outline of its largest room."""
    groups = []
    for room, (name, colour, fallback) in COLUMN_STYLES.items():
        items = []
        for outline, bottom, top, levels, names, key in shaft_columns(indoor, room):
            spot = outline.representative_point()
            low = heights(spot.x, spot.y, bottom)
            high = heights(spot.x, spot.y, top) + WALL_HEIGHT
            text = "%s\n%s · %s" % (
                ", ".join(names) or fallback,
                key,
                levels_text(levels),
            )
            items += [
                {"r": rings, "h": round(high - low, 2), "t": text}
                for rings in _rings(outline, low, origin)
            ]
        groups.append(
            dict(
                name=name,
                kind="glass",
                colour=colour,
                alpha=_COLUMN_ALPHA,
                pickable=True,
                visible=True,
                items=items,
            )
        )
    return groups


def _point_group(points, style, lift, between, heights, origin):
    """The ``points`` of a doors or pois layer as a group of points ``lift`` metres
    over their floor on each of their whole levels and of the levels ``between``, off
    at the start; ``style`` is ``DOOR_STYLE`` or ``POI_STYLE``."""
    name, colour, _, fallback = style
    items = []
    columns = (points["levels"], points["tags"], points.geometry)
    for key, levels, tags, point in zip(element_keys(points), *columns):
        label = tags.get("name") or tags.get("shop") or tags.get("amenity") or fallback
        for level in levels:
            if float(level).is_integer() or level in between:
                z = heights(point.x, point.y, level) + lift
                place = [point.x - origin[0], point.y - origin[1], z]
                items.append(
                    {
                        "c": [round(value, 2) for value in place],
                        "t": "%s\n%s · level %g" % (label, key, level),
                        "l": float(level),
                    }
                )
    width = 3.0 if style is DOOR_STYLE else 3.5
    return dict(
        name=name, kind="points", colour=colour, width=width, visible=False, items=items
    )


def _outline_items(paths, level, heights, origin):
    """The lines through ``paths`` (xy arrays in metres) on ``level`` as items, under
    the height that ``heights`` gives the level at the middle of each."""
    items = []
    for path in paths:
        middle = path.mean(axis=0)
        z = heights(middle[0], middle[1], level) - _OUTLINE_DROP
        points = np.column_stack([path - origin, np.full(len(path), z)])
        items.append({"p": points.round(2).tolist(), "l": float(level)})
    return items


def _outline_groups(view, heights, origin):
    """The outlines of the levels among the areas of ``view`` (an IndoorBox), on each
    of their levels, and of the buildings drawn as lines (see
    :func:`pyrosm3d.walls.building_outlines`), each a group for the indoor view
    only."""
    levels, buildings = [], []
    areas = view.indoor.areas
    for kind, on_levels, area in zip(areas["kind"], areas["levels"], areas.geometry):
        if kind == "level":
            paths = [
                shapely.get_coordinates(line)
                for line in _inside(area.boundary, view.shape)
            ]
            for level in on_levels:
                levels += _outline_items(paths, level, heights, origin)
    for level, paths in sorted(building_outlines(view.indoor, view.shape).items()):
        buildings += _outline_items(paths, level, heights, origin)
    found = (("Level outlines", _LEVEL_OUTLINE, levels),)
    found += (("Building outlines", _BUILDING_OUTLINE, buildings),)
    return [
        dict(
            name=name,
            kind="outlines",
            only="indoor",
            colour=LEVEL_OUTLINE_COLOUR,
            width=width,
            visible=True,
            items=items,
        )
        for name, width, items in found
    ]


def indoor_groups(view, origin, heights=level_heights):
    """The groups of the indoor elements of ``view`` (an IndoorBox), in metres from
    ``origin`` (x, y in the metres of the layers) at the heights ``(x, y, level) ->
    metres`` that ``heights`` gives (see the module docstring); groups without items
    are left out."""
    origin = np.asarray(origin, dtype=float)
    indoor = view.indoor
    outer, level_floors = outer_walls(indoor, view.shape)
    walls = (
        (WALL_NAME, None, True, _wall_items(inner_walls(indoor), heights, origin)),
        (OUTER_WALL_NAME, "indoor", False, _wall_items(outer, heights, origin)),
    )
    groups = _floor_groups(view, heights, origin) + _outline_groups(
        view, heights, origin
    )
    for name, only, visible, items in walls:
        group = dict(
            name=name,
            kind="glass",
            colour=WALL_STYLE["color"],
            alpha=_WALL_ALPHA,
            visible=visible,
            items=items,
        )
        groups.append(dict(group, only=only) if only else group)
    groups.append(
        dict(
            name="Level floors",
            kind="floors",
            only="indoor",
            colour=LEVEL_FLOOR_COLOUR,
            colours={"level": LEVEL_FLOOR_COLOUR},
            edge=OUTLINE_COLOUR,
            alpha=255,
            throughAlpha=255,
            edgeAlpha=0,
            edgeWidth=0,
            plotEdge=0,
            visible=False,
            items=_level_floor_items(level_floors, heights, origin),
        )
    )
    groups += _column_groups(indoor, heights, origin)
    for points, style, lift in (
        (indoor.doors, DOOR_STYLE, _DOOR_LIFT),
        (indoor.pois, POI_STYLE, _POI_LIFT),
    ):
        groups.append(_point_group(points, style, lift, view.between, heights, origin))
    return [group for group in groups if group["items"]]


def plot_indoor(elements, edges=None, nodes=None, buildings=None, level=None):
    """A 3D view of indoor elements (see the module docstring), from frames read with
    pyrosm (``osm`` is a ``pyrosm.OSM`` object); ``osm.in3d.plot_indoor()`` makes
    these reads itself.

    Parameters
    ----------
    elements : GeoDataFrame
        ``osm.get_indoor_elements(walking_areas=True)``. The view shows the areas
        and what lies within 10 m of them; a walking area, such as a square or a
        pedestrian street, is drawn as far as the other areas' view reaches.
    edges, nodes : GeoDataFrame (optional)
        ``osm.get_network("walking", nodes=True, indoor_elements=True,
        walking_areas=True)``, drawn on its levels.
    buildings : GeoDataFrame (optional)
        ``osm.get_buildings()``, for the outlines.
    level : float (optional)
        The level that the indoor view opens on; by default all levels.

    Returns
    -------
    pyrosm3d.View
        In a notebook the view is the output of the cell; ``view.to_html(path)`` writes
        it as a page and ``view.show()`` shows it. It opens in the indoor view, where
        one level or all can be picked, with the heights drawn taller unless "True
        heights" is on; a level is drawn 4 m from the next above the ground floor and
        6 m below it. The outer walls, the doors and the shops are off until they are
        switched on in the list of layers. The solid model and the see-through map
        show the elements on a flat ground at street level.
    """
    return layers_view(indoor_layers(elements, nodes, edges, buildings), level)


def _levels_of(groups):
    """The levels of the items of ``groups``: an item's level, or the levels that the
    indoor view shows a line on."""
    found = set()
    for group in groups:
        for item in group["items"]:
            if "l" in item:
                found.add(item["l"])
            elif group["kind"] == "lines":
                found.update(item.get("ls", [item.get("a", 0.0)]))
    return found


def _points_of(groups):
    """The points of the items of ``groups``, as a list of paths: the lines, the outer
    rings of the polygons and the points."""
    paths = []
    for group in groups:
        for item in group["items"]:
            if "p" in item:
                paths.append(item["p"])
            elif "r" in item:
                paths.append(item["r"][0])
            else:
                paths.append([item["c"]])
    return paths


def layers_view(indoor, level=None):
    """The view of :func:`plot_indoor` for the layers ``indoor`` (an IndoorLayers, see
    :func:`pyrosm3d.indoor.indoor_layers`): the groups of :func:`indoor_groups` and
    the walking network in metres from the middle of the indoor view's box; the
    platform edges of the platforms with a floor are left out. The level picker lists
    the whole levels and those between them with floors, apart from what only doors
    and shops are on. Raises a ValueError for a ``level`` that it does not list."""
    shown = IndoorBox(indoor)
    west, south, east, north = shown.box
    origin = ((west + east) / 2, (south + north) / 2)
    lines = _NetworkLines(in_metres=False)
    edges = shown.indoor.edges
    for key, (row, tags, kind, level_u, level_v) in zip(
        element_keys(edges), _edge_kinds(edges)
    ):
        if kind == "platform" and key in shown.platform_floors:
            continue
        points = _edge_points(row.geometry, kind, level_u, level_v, origin, False)
        on_levels = shown_levels(level_u, level_v, shown.between)
        lines.add(
            kind, row, tags, level_u, level_v, np.column_stack(points), 0.0, on_levels
        )
    drawn = indoor_groups(shown, origin)
    points = [group for group in drawn if group["kind"] == "points"]
    groups = [group for group in drawn if group["kind"] != "points"]
    groups += lines.groups() + points
    picked = sorted(
        found
        for found in _levels_of(groups[: len(groups) - len(points)])
        if float(found).is_integer() or found in shown.between
    )
    if level is not None and float(level) not in picked:
        raise ValueError("plot_indoor got nothing to draw on level %g." % level)
    every = sorted(_levels_of(groups))
    low, high = (level_heights(0.0, 0.0, found) for found in (every[0], every[-1]))
    corners = (west - origin[0], south - origin[1], east - origin[0], north - origin[1])
    paths = _points_of(groups)
    view, fit = _start_view(paths, lambda x, y: 0.0, turned=False, radius=None)
    data = dict(
        mode="indoor",
        view=view,
        fit=fit,
        stretch=HEIGHT_STRETCH,
        tables=lines.tables(),
        indoor=dict(
            box=[round(value, 1) for value in corners],
            levels=[[found, level_heights(0.0, 0.0, found)] for found in picked],
            ground=0.0,
            background=BACKGROUND_COLOUR,
            stretch=round(indoor_stretch(shown.box, low, high), 3),
        ),
        groups=[_flat_ground(paths)] + groups,
    )
    if level is not None:
        data["indoor"]["level"] = float(level)
    about = (
        "The indoor elements of a place at their levels: the floors of the areas, "
        "walls, stairwells and lift shafts, and the walking network."
    )
    return View(data, title="Indoor elements", about=about)
