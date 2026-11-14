"""The floors of indoor areas: the levels an area has a floor on, the openings that
stairs and escalators need in a floor, and the triangles of a floor."""

import math

import pandas as pd
import shapely
from shapely.ops import substring

from pyrosm3d.styles import LANDING, OPENING_WIDTHS
from pyrosm3d.tags import _MAX_LEVEL_SPAN, float_column

# An edge shorter than this, or a part of one, opens no floor (metres)
_SHORTEST_CLIMB = 0.5
_SHORTEST_OPENING = 0.1


def floor_levels(kind, levels):
    """The levels on which an area of ``kind`` that is on ``levels`` (sorted) has a
    floor: its whole levels. An area on two or more of them is one tall space with its
    floor on the lowest, unless it is a shaft, which has a floor on each."""
    whole = [level for level in levels if float(level).is_integer()]
    if kind == "shaft":
        return whole
    return whole[:1]


def floor_openings(edges):
    """``{level: polygon}``: the openings that the floors of each whole level need for
    the stairs, escalators and moving walkways among ``edges`` (the network in metres)
    that rise through them.

    An edge that climbs from level a to level b passes up through every whole level L
    with a < L <= b. The level changes along the edge in proportion to its length, so
    the floor on L is open over the part of the edge that is below L, as wide as
    ``OPENING_WIDTHS`` gives for the edge's ``vertical`` value; where the edge ends
    on L, a landing stays closed."""
    verticals = edges.get("vertical", pd.Series(None, index=edges.index))
    columns = (float_column(edges, "u_level"), float_column(edges, "v_level"))
    openings = {}
    for line, start, end, vertical in zip(edges.geometry, *columns, verticals):
        width = OPENING_WIDTHS.get(vertical) if isinstance(vertical, str) else None
        if width is None or line.length < _SHORTEST_CLIMB:
            continue
        if start > end:  # follow the line upwards
            line, start, end = line.reverse(), end, start
        if not 0 < end - start <= _MAX_LEVEL_SPAN:
            continue
        for level in range(math.floor(start) + 1, math.floor(end) + 1):
            below = line.length * (level - start) / (end - start)
            if level == end:
                below -= LANDING
            if below > _SHORTEST_OPENING:
                part = substring(line, 0.0, below)
                opening = part.buffer(width / 2, cap_style="flat")
                openings.setdefault(float(level), []).append(opening)
    return {level: shapely.union_all(parts) for level, parts in openings.items()}


def triangles(polygon):
    """The triangles that cover ``polygon`` (a Polygon or MultiPolygon), as an array of
    corner coordinates of the shape (triangles, 3, 2)."""
    parts = shapely.constrained_delaunay_triangles(polygon.buffer(0))
    return shapely.get_coordinates(parts).reshape(-1, 4, 2)[:, :3]
