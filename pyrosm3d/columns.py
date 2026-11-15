"""Stairwells and lift shafts as columns through the floors that they join."""

import math

import numpy as np
import pandas as pd
import shapely

from pyrosm3d.tags import float_column

# The ``vertical`` value of the edges that run inside each kind of column
_CLIMBS = {"stairs": "stairs", "elevator": "lift"}


def shaft_columns(indoor, room):
    """The columns of ``indoor`` (an IndoorElements) for one kind of shaft:
    ``room="stairs"`` for stairwells (``room=stairs``) and ``room="elevator"`` for
    lift shafts (``room=elevator`` or ``highway=elevator``).

    The rooms of the kind that lie over each other on consecutive floors, or with one
    floor missing between them, form one column (see :func:`_stacks`). Returns a list
    of ``(outline, bottom, top, levels, names)``: the outline of the stack's largest
    room, the levels of the lowest and highest floor the column reaches, the whole
    levels of its rooms, and the names or refs of the rooms. Stairs or lift edges of
    the network inside the outline stretch the column to the levels they reach."""
    areas = indoor.areas
    rooms = []
    columns = (areas["kind"], areas["levels"], areas["tags"], areas.geometry)
    for kind, levels, tags, polygon in zip(*columns):
        is_room = tags.get("room") == room
        is_lift = room == "elevator" and tags.get("highway") == "elevator"
        whole = [level for level in levels if float(level).is_integer()]
        if kind == "shaft" and (is_room or is_lift) and whole:
            rooms.append((_outline(polygon), whole, tags))
    climb_xy, climb_levels = _climbs(indoor.edges, _CLIMBS[room])
    found = []
    for stack in _stacks(rooms):
        outline = max((outline for outline, _, _ in stack), key=lambda o: o.area)
        levels = sorted({level for _, whole, _ in stack for level in whole})
        inside = shapely.contains_xy(outline, climb_xy[:, 0], climb_xy[:, 1])
        reached = np.r_[levels, climb_levels[inside].ravel()]
        names = [tags.get("name") or tags.get("ref") for _, _, tags in stack]
        names = list(dict.fromkeys(name for name in names if name))
        bottom, top = math.floor(reached.min()), math.ceil(reached.max())
        found.append((outline, bottom, top, levels, names))
    return found


def _outline(polygon):
    """The area inside the outer ring of ``polygon`` (of its first part)."""
    return shapely.Polygon(shapely.get_parts(polygon)[0].exterior)


def _climbs(edges, vertical):
    """The edges of the network with the ``vertical`` value that join two different
    levels: the middle of the points of each (an xy array) and its two levels."""
    verticals = edges.get("vertical", pd.Series(None, index=edges.index)).fillna("")
    of_kind = np.array([value == vertical for value in verticals], dtype=bool)
    levels = np.column_stack(
        [float_column(edges, "u_level"), float_column(edges, "v_level")]
    )
    climbs = of_kind & np.isfinite(levels).all(axis=1) & (levels[:, 0] != levels[:, 1])
    lines = edges.geometry.to_numpy()[climbs]
    middles = [shapely.get_coordinates(line).mean(axis=0) for line in lines]
    return np.array(middles).reshape(-1, 2), levels[climbs]


def _stacks(rooms):
    """The ``rooms`` (``(outline, whole levels, tags)``) grouped into stacks. A room
    joins a room one or two levels above its highest level when the middle of the
    outline of one lies inside the outline of the other. Rooms with different room
    numbers (see :func:`_room_number`) never share a stack."""
    parent = list(range(len(rooms)))
    numbers = [{_room_number(tags)} - {None} for _, _, tags in rooms]
    rings = [shapely.get_coordinates(outline.exterior) for outline, _, _ in rooms]
    middles = [ring.mean(axis=0) for ring in rings]

    def root(room):
        while parent[room] != room:
            room = parent[room]
        return room

    def overlap(one, other):
        return shapely.contains_xy(rooms[other][0], *middles[one]) or (
            shapely.contains_xy(rooms[one][0], *middles[other])
        )

    for below, (_, levels, _) in enumerate(rooms):
        over = levels[-1] + 1
        for above, (_, upper, _) in enumerate(rooms):
            if (over in upper or over + 1 in upper) and overlap(below, above):
                a, b = root(below), root(above)
                if a != b and len(numbers[a] | numbers[b]) <= 1:
                    parent[a] = b
                    numbers[b] |= numbers[a]
    stacks = {}
    for room, entry in enumerate(rooms):
        stacks.setdefault(root(room), []).append(entry)
    return list(stacks.values())


def _room_number(tags):
    """The number that a room keeps on every floor, from a ``ref`` in several parts
    such as "AA 01 35": its first and last part, here "AA 35". None for a ``ref`` in
    one part or no ``ref``."""
    parts = str(tags.get("ref") or "").split()
    return "%s %s" % (parts[0], parts[-1]) if len(parts) > 1 else None
