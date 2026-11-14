"""Walls as upright panels with a gap at each door: the walls of rooms and the walls
mapped as lines or areas, and the outer walls along level and building outlines."""

import numpy as np
import shapely

from pyrosm3d.styles import DOOR_GAP, DOOR_REACH, FLOOR_HEIGHT, WALL_HEIGHT
from pyrosm3d.tags import _MAX_LEVEL_SPAN

# A wall segment shorter than this is left out (metres)
_SHORTEST_WALL = 0.05
_NO_DOORS = np.empty((0, 2))


def wall_panels(path, doors, z_low, z_high):
    """The wall along ``path`` (xy points, an array of the shape (points, 2)) from the
    height ``z_low`` to ``z_high`` as panels: the x, y and z of the four corners of
    each, the two at the bottom first, as an array of the shape (panels, 4, 3). Each
    of the ``doors`` (xy points) within ``DOOR_REACH`` of a segment of the wall leaves
    a gap ``DOOR_GAP`` wide, centred on the door."""
    panels = []
    for start, end in zip(path[:-1], path[1:]):
        along = end - start
        length = float(np.hypot(*along))
        if length < _SHORTEST_WALL:
            continue
        for t_from, t_to in _closed_parts(start, along, length, doors):
            a, b = start + t_from * along, start + t_to * along
            panels.append([(*a, z_low), (*b, z_low), (*b, z_high), (*a, z_high)])
    return np.array(panels, dtype=float).reshape(-1, 4, 3)


def _closed_parts(start, along, length, doors):
    """The parts of a wall segment that the gaps of ``doors`` leave closed, as
    ``(from, to)`` in fractions of the segment, which runs ``along`` (a vector of
    ``length`` metres) from ``start``."""
    middles = (doors - start) @ along / length**2
    beside = np.hypot(*(start + middles[:, None] * along - doors).T)
    on_wall = (middles >= -0.01) & (middles <= 1.01) & (beside <= DOOR_REACH)
    half = DOOR_GAP / 2 / length
    parts, closed_from = [], 0.0
    for middle in np.sort(middles[on_wall]):
        gap_from = min(middle - half, 1.0)
        if gap_from > closed_from:
            parts.append((closed_from, gap_from))
        closed_from = max(closed_from, middle + half)
    if closed_from < 1:
        parts.append((closed_from, 1.0))
    return parts


def inner_walls(indoor):
    """``{level: panels}`` of the walls inside the buildings of ``indoor`` (an
    IndoorElements), see :func:`wall_panels`: along the outlines of the rooms
    (``indoor=room``, apart from ``room=corridor``) on their whole levels, and along
    the walls mapped as lines or as areas on each of their levels. Walls are cut away
    at ``WALL_HEIGHT``; a tall room over several levels has walls a full storey high on
    every level from its lowest up to the one below its highest."""
    doors = _doors_by_level(indoor.doors)
    areas, panels = indoor.areas, {}
    columns = (areas["kind"], areas["levels"], areas["tags"], areas.geometry)
    for kind, levels, tags, polygon in zip(*columns):
        if kind == "wall":
            heights = dict.fromkeys(levels, WALL_HEIGHT)
        elif tags.get("indoor") == "room" and tags.get("room") != "corridor":
            heights = _room_wall_heights(kind, levels)
        else:
            continue
        _add_walls(panels, _paths(polygon), heights, doors)
    for levels, line in zip(indoor.walls["levels"], indoor.walls.geometry):
        _add_walls(panels, _paths(line), dict.fromkeys(levels, WALL_HEIGHT), doors)
    return {level: np.concatenate(found) for level, found in panels.items()}


def outer_walls(indoor, view):
    """``({level: panels}, {level: polygons})``: the outer walls of ``indoor`` (an
    IndoorElements) inside the box ``view``, and the floors under them. The walls
    stand a full storey high, with door gaps, along the level outlines
    (``indoor=level``) on their whole levels, and along the outline of each building
    that holds indoor areas but no level outline, on the whole levels of those
    areas."""
    doors = _doors_by_level(indoor.doors)
    areas = indoor.areas[indoor.areas["kind"] == "level"]
    outlines = [
        (levels, _paths(polygon), polygon)
        for levels, polygon in zip(areas["levels"], areas.geometry)
    ]
    panels, floors = {}, {}
    for levels, paths, floor in outlines + _building_shells(indoor, view):
        whole = [level for level in levels if float(level).is_integer()]
        _add_walls(panels, paths, dict.fromkeys(whole, FLOOR_HEIGHT), doors)
        for level in whole:
            floors.setdefault(level, []).append(floor)
    panels = {level: np.concatenate(found) for level, found in panels.items()}
    return panels, floors


def _building_shells(indoor, view):
    """``[(levels, paths, floor)]`` of the buildings that hold indoor areas but no
    level outline: the whole levels of those areas, the part of the building's own
    outline inside the box ``view`` as xy arrays (where the box cuts through the
    building, the cut is no wall) and the building's floor inside the box. An area
    counts for the smallest building around a point inside it."""
    buildings = [b for b in indoor.buildings.geometry if b.intersects(view)]
    if not buildings:
        return []
    tree = shapely.STRtree(buildings)
    levels_in, outlined = {}, set()
    areas = indoor.areas
    for kind, levels, polygon in zip(areas["kind"], areas["levels"], areas.geometry):
        around = tree.query(polygon.representative_point(), predicate="within")
        if not len(around):
            continue
        smallest = min(around, key=lambda found: buildings[found].area)
        if kind == "level":
            outlined.add(smallest)
        else:
            whole = (level for level in levels if float(level).is_integer())
            levels_in.setdefault(smallest, set()).update(whole)
    shells = []
    for found, whole in sorted(levels_in.items()):
        if found in outlined or not whole:
            continue
        outline = buildings[found].boundary.intersection(view)
        paths = [path for path in _paths(outline) if len(path) > 1]
        shells.append((sorted(whole), paths, buildings[found].intersection(view)))
    return shells


def _room_wall_heights(kind, levels):
    """``{level: height}`` of the walls of a room of ``kind`` on ``levels`` (sorted):
    cut away on each whole level; a tall room, on several whole levels and not a
    shaft, has full walls on every level below its highest, also on levels that its
    ``level`` tag leaves out."""
    whole = [level for level in levels if float(level).is_integer()]
    if kind == "shaft" or len(whole) < 2 or whole[-1] - whole[0] > _MAX_LEVEL_SPAN:
        return dict.fromkeys(whole, WALL_HEIGHT)
    below_top = map(float, range(int(whole[0]), int(whole[-1])))
    heights = dict.fromkeys(below_top, FLOOR_HEIGHT)
    heights[whole[-1]] = WALL_HEIGHT
    return heights


def _doors_by_level(doors):
    """``{level: xy array}`` of the points of the ``doors`` layer on each of their
    levels."""
    by_level = {}
    for levels, point in zip(doors["levels"], doors.geometry):
        for level in levels:
            by_level.setdefault(level, []).append((point.x, point.y))
    return {level: np.array(points) for level, points in by_level.items()}


def _paths(geometry):
    """The rings of a polygon, or the lines of a line geometry, as xy arrays; nothing
    for a point."""
    parts = shapely.get_parts(geometry)
    if geometry.geom_type in ("Polygon", "MultiPolygon"):
        parts = shapely.get_rings(parts)
    lines = [part for part in parts if part.geom_type in ("LineString", "LinearRing")]
    return [shapely.get_coordinates(line) for line in lines]


def _add_walls(panels, paths, heights, doors):
    """Add to ``panels`` (``{level: [panels]}``) the walls along ``paths`` (xy arrays)
    on each level of ``heights`` (``{level: height}``), with gaps at the ``doors``
    (``{level: xy array}``) of that level that lie in the bounds of a path."""
    for level, height in heights.items():
        z_low = level * FLOOR_HEIGHT
        on_level = doors.get(level, _NO_DOORS)
        for path in paths:
            low, high = path.min(axis=0) - DOOR_REACH, path.max(axis=0) + DOOR_REACH
            near = on_level[((on_level >= low) & (on_level <= high)).all(axis=1)]
            found = wall_panels(path, near, z_low, z_low + height)
            if len(found):
                panels.setdefault(level, []).append(found)
