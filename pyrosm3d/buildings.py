"""The buildings of a place as blocks of a 3D view (see :class:`pyrosm3d.View`).

A building is a block as high as its ``height`` tag, else 4 m for each of its
``building:levels`` and ``roof:levels``; a height or a level count of 0, as of a
building below ground, lies flat on the ground. A building with ``building:part`` areas
inside it is drawn by those of its parts that have a height or levels, each from its
``min_height`` (else 4 m for each ``building:min_level``) to its top, and by what they
leave uncovered of its outline, at its own height: the parts of a building often cover
only some of it. A building without a height or levels is drawn as high as the median
level count of the mapped buildings of its size that have levels, in a paler colour
of its own; a roof
or a canopy without one, which has no walls, lies flat on the ground.
"""

import math
import re

import numpy as np
import shapely

from pyrosm3d.styles import FLOOR_HEIGHT, GROUND_DROP
from pyrosm3d.tags import is_missing, row_tags
from pyrosm3d.view import polygon_parts, polygon_rings

# The buildings that have no walls, flat on the ground without a height
_FLAT = ("roof", "canopy")
# Metres that a flat building is high
_FLAT_HEIGHT = 0.3
# Footprints (square metres) that split the buildings into size classes, and how many
# buildings with levels a class needs for the median of its levels
_SIZES = [0, 15, 30, 60, 120, 250, 500, 1000, float("inf")]
_COUNTED = 5
# What the parts of a building leave uncovered is drawn where it is at least this many
# metres wide: narrower strips come from outlines that do not quite meet
_LEFT_OVER = 0.6
# A height: a number, maybe in metres; a level count: a plain number
_HEIGHT = re.compile(r"\s*(\d+(?:\.\d+)?)\s*(?:m)?\s*")
_COUNT = re.compile(r"\s*(\d+(?:\.\d+)?)\s*")
# The colours of the buildings with a height in OpenStreetMap and without one, and of
# their edges
_FILL, _ASSUMED_FILL, _EDGE = "#e3c99a", "#efe3cb", "#8c6f43"


def _tag_number(pattern, text):
    """The finite number in a tag value of the form of ``pattern``; None for any
    other value."""
    found = pattern.fullmatch(str(text))
    value = float(found[1]) if found else math.inf
    return value if math.isfinite(value) else None


def _metres(text):
    """The metres of a height such as ``"12"``, ``"12.5"`` or ``"12 m"``; None for any
    other value."""
    return _tag_number(_HEIGHT, text)


def _level_count(text):
    """The number of levels such as ``"3"``; None for any other value, or for so many
    levels that their metres are not a number."""
    count = _tag_number(_COUNT, text)
    if count is None or not math.isfinite(count * FLOOR_HEIGHT):
        return None
    return count


def _levels(tags):
    """The levels of a building or part with ``tags``: its ``building:levels`` and
    its ``roof:levels`` (see :func:`_level_count`); None without either, or for so many
    together that their metres are not a number."""
    found = [_level_count(tags.get(key)) for key in ("building:levels", "roof:levels")]
    if found == [None, None]:
        return None
    total = sum(count or 0.0 for count in found)
    return total if math.isfinite(total * FLOOR_HEIGHT) else None


def _rise(tags):
    """Metres from the ground to the top of a building or part with ``tags``: its
    height, else 4 m for each of its levels (see :func:`_levels`); None without
    either."""
    height = _metres(tags.get("height"))
    if height is not None:
        return height
    levels = _levels(tags)
    return None if levels is None else levels * FLOOR_HEIGHT


def _levels_by_size(counted, areas):
    """``(levels, size)``: the median level count of each size class of ``_SIZES``, and
    the class of each building, from the level counts of the buildings (NaN where a
    building has none) and their footprints. Only buildings with at least one level
    count: a building of 0 levels lies below ground or is a roof, and would draw the
    buildings that stand above ground too low. A class with fewer than ``_COUNTED``
    such buildings takes the median of the nearest class that has them; without any
    such class, the median of all of them (1 without any)."""
    have = np.isfinite(counted) & (counted > 0)
    size = np.digitize(areas, _SIZES) - 1
    classes = range(len(_SIZES) - 1)
    medians = {
        found: float(np.median(counted[have & (size == found)]))
        for found in classes
        if (have & (size == found)).sum() >= _COUNTED
    }
    every = float(np.median(counted[have])) if have.any() else 1.0
    levels = {}
    for found in classes:
        nearest = sorted(medians, key=lambda other: abs(other - found))
        levels[found] = medians[nearest[0]] if nearest else every
    return levels, size


def _uncovered(shape, parts):
    """What ``parts`` leave uncovered of ``shape`` (all in metres), without the strips
    narrower than ``_LEFT_OVER``; None when nothing is left."""
    rest = shapely.difference(shape, shapely.union_all(parts))
    half = _LEFT_OVER / 2
    rest = rest.buffer(-half, join_style="mitre").buffer(half, join_style="mitre")
    polygons = [
        part
        for part in shapely.get_parts(rest)
        if part.geom_type == "Polygon" and not part.is_empty
    ]
    return shapely.MultiPolygon(polygons) if polygons else None


def _text(tags, what):
    """The text of a building or a part: its name, else its address, its
    ``building`` (or ``building:part``) value and ``what``."""
    address = (tags.get("addr:street"), tags.get("addr:housenumber"))
    name = tags.get("name") or " ".join(filter(None, address))
    kind = tags.get("building", tags.get("building:part"))
    return "\n".join(filter(None, (name, "building=%s" % kind, what)))


def _ground_of(shape, ground):
    """``(lowest, middle)``: the lowest and the median height that ``ground`` gives
    at the corners of the outline of ``shape``, each corner once; None where it gives
    none."""
    xy = np.unique(shapely.get_coordinates(shape), axis=0)
    heights = np.asarray(ground(xy[:, 0], xy[:, 1]), dtype=float)
    heights = heights[np.isfinite(heights)]
    if not len(heights):
        return None
    return float(heights.min()), float(np.median(heights))


def _street_level(x, y):
    """The ground of a view without a terrain model: street level, 0 m."""
    return np.zeros(len(x))


def building_groups(shapes, tags, origin, ground=_street_level, keep=None):
    """The buildings as the groups of a view (see the module docstring): those with a
    height in OpenStreetMap, and those drawn as high as others of their size.

    Parameters
    ----------
    shapes : array of shapely geometries
        The outlines of the buildings and of their parts, in metres; a broken outline
        is repaired first, and only polygons count.
    tags : list of dict
        The OpenStreetMap tags of each shape; a shape with ``building:part`` and
        without ``building`` is a part.
    origin : (x, y)
        The point, in the metres of ``shapes``, that the view's metres start from.
    ground : function (optional)
        ``(x, y) -> heights`` of the ground at points in the metres of ``shapes``;
        street level, 0 m, by default. A block stands from ``GROUND_DROP`` under the
        lowest ground along its outline, so that no gap shows under it, to its top
        over the median ground there; a building where the ground has no height is
        left out.
    keep : function (optional)
        Of the outlines of the buildings in metres, those to draw (booleans), each
        with all its parts; all by default.

    Returns
    -------
    list of dict
        The groups that have buildings. Each item is a block: its rings ``r`` at its
        bottom, its height ``h``, the height of the ground ``g`` under its footprint, a
        text ``t``, and ``part`` for a part.
    """
    origin = np.asarray(origin, dtype=float)
    shapes = [polygon_parts(shape) for shape in shapely.make_valid(np.asarray(shapes))]
    polygonal = [not shape.is_empty for shape in shapes]
    shapes = np.array([shape for shape in shapes if not shape.is_empty], dtype=object)
    tags = [found for found, keep in zip(tags, polygonal) if keep]
    is_part = np.array(
        ["building:part" in t and "building" not in t for t in tags], dtype=bool
    )
    rows = np.flatnonzero(~is_part)
    levels = [_levels(tags[row]) for row in rows]
    counted = np.array([np.nan if count is None else count for count in levels])
    by_size, size = _levels_by_size(counted, shapely.area(shapes[rows]))
    size_of = dict(zip(rows.tolist(), size.tolist()))
    parts_of, drawn = {}, {}
    for part in np.flatnonzero(is_part).tolist():
        top = _rise(tags[part])
        low = _metres(tags[part].get("min_height"))
        level = _level_count(tags[part].get("building:min_level"))
        bottom = low if low is not None else (level or 0.0) * FLOOR_HEIGHT
        within = shapely.contains(shapes[rows], shapely.point_on_surface(shapes[part]))
        if top is not None and top > bottom and within.any():
            home = rows[within][np.argmin(shapely.area(shapes[rows[within]]))]
            parts_of.setdefault(int(home), []).append(part)
            drawn[part] = (int(home), bottom, top)
    known, assumed, grounds = [], [], {}
    kept = np.ones(len(rows), dtype=bool) if keep is None else keep(shapes[rows])
    for row in rows[np.asarray(kept, dtype=bool)].tolist():
        found = _ground_of(shapes[row], ground)
        if found is None:
            continue
        lowest, middle = found
        grounds[row] = found
        shape = shapes[row]
        if row in parts_of:
            shape = _uncovered(shape, shapes[parts_of[row]])
            if shape is None:
                continue
        rise = _rise(tags[row])
        if rise is not None:
            what = (
                "%g m high" % rise
                if _metres(tags[row].get("height")) is not None
                else ("%g levels" % (rise / FLOOR_HEIGHT))
            )
        if rise is not None and rise > 0:
            items, bottom, top = known, lowest - GROUND_DROP, middle + rise
        elif rise == 0 or tags[row].get("building") in _FLAT:
            what = "no height in OpenStreetMap" if rise is None else what
            items, bottom, top = known, middle, middle + _FLAT_HEIGHT
        else:
            levels = by_size[size_of[row]]
            what = (
                "no height in OpenStreetMap: drawn %g levels high, as buildings of "
                "its size" % levels
            )
            items, bottom = assumed, lowest - GROUND_DROP
            top = middle + levels * FLOOR_HEIGHT
        text = _text(tags[row], what)
        items += [
            {"r": rings, "h": round(top - bottom, 1), "g": round(middle, 1), "t": text}
            for rings in polygon_rings(shape, bottom, origin, decimals=1)
        ]
    for part, (home, bottom, top) in drawn.items():
        if home not in grounds:
            continue
        lowest, middle = grounds[home]
        # a part from the ground stands from under the lowest ground, as a building
        base = lowest - GROUND_DROP if bottom == 0 else middle + bottom
        what = "part from %g to %g m above the ground" % (bottom, top)
        text = _text(tags[part], what)
        known += [
            {
                "r": rings,
                "h": round(middle + top - base, 1),
                "g": round(middle, 1),
                "t": text,
                "part": 1,
            }
            for rings in polygon_rings(shapes[part], base, origin, decimals=1)
        ]
    groups = (
        ("Buildings", _FILL, 150, known),
        (
            "Buildings without a height (as high as others of their size)",
            _ASSUMED_FILL,
            110,
            assumed,
        ),
    )
    return [
        dict(
            name=name,
            kind="buildings",
            colour=colour,
            edge=_EDGE,
            alpha=240,
            edgeAlpha=edge_alpha,
            edgeWidth=0.8,
            visible=True,
            items=items,
        )
        for name, colour, edge_alpha, items in groups
        if items
    ]


def _element(kind, found):
    """``(kind, id)`` of an OSM element, the id a whole number as an int, so that an
    id read as 7 and as 7.0 is one element; None without an id."""
    if is_missing(found):
        return None
    if isinstance(found, (float, np.floating)) and float(found).is_integer():
        found = int(found)
    return (str(kind), found)


def frame_building_groups(frames, crs, origin, ground=_street_level, keep=None):
    """The groups of :func:`building_groups` for frames read with pyrosm, such as
    ``osm.get_buildings()`` and the building parts of
    ``osm.get_data_by_custom_criteria({"building:part": True})``, in the metres of
    ``crs``. The tags of each frame are read on their own: a frame made by joining the
    two would lose the parts' heights. An element in several frames, such as an area
    tagged with both ``building`` and ``building:part``, counts once; a row without an
    id counts. ``keep`` picks the buildings to draw (see :func:`building_groups`); a
    frame that is None or empty is skipped."""
    shapes, tags, seen = [], [], set()
    for frame in frames:
        if frame is None or not len(frame):
            continue
        types = frame.get("osm_type", ["way"] * len(frame))
        ids = frame.get("id", [None] * len(frame))
        keys = [_element(kind, found) for kind, found in zip(types, ids)]
        found = frame.to_crs(crs).geometry.to_numpy()
        for shape, tag, key in zip(found, row_tags(frame), keys):
            if key is None or key not in seen:
                seen.add(key)
                shapes.append(shape)
                tags.append(tag)
    if not shapes:
        return []
    return building_groups(np.array(shapes, dtype=object), tags, origin, ground, keep)
