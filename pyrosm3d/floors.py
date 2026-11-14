"""The floors of indoor areas: the levels an area has a floor on, and its triangles."""

import shapely


def floor_levels(kind, levels):
    """The levels on which an area of ``kind`` that is on ``levels`` (sorted) has a
    floor: its whole levels. An area on two or more of them is one tall space with its
    floor on the lowest, unless it is a shaft, which has a floor on each."""
    whole = [level for level in levels if float(level).is_integer()]
    if kind == "shaft":
        return whole
    return whole[:1]


def triangles(polygon):
    """The triangles that cover ``polygon`` (a Polygon or MultiPolygon), as an array of
    corner coordinates of the shape (triangles, 3, 2)."""
    parts = shapely.constrained_delaunay_triangles(polygon.buffer(0))
    return shapely.get_coordinates(parts).reshape(-1, 4, 2)[:, :3]
