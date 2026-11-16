"""The layers that plot_indoor draws, from the frames that pyrosm reads: areas such as
rooms, corridors, platforms and squares, walls, doors, shops and amenities, building
outlines and the walking network, in the metres of one UTM zone."""

from dataclasses import dataclass

import numpy as np
import shapely
from geopandas import GeoDataFrame, GeoSeries

from pyrosm3d.tags import (
    crosses_area,
    element_keys,
    float_column,
    is_platform,
    layer_level,
    row_tags,
)

# The rooms that are shafts: a space between floors, or one that people do not use
_SHAFT_ROOMS = {"stairs", "elevator", "utility", "storage", "technical"}
# The amenities that are drawn as shops
_FOOD_AMENITIES = {
    "fast_food",
    "restaurant",
    "cafe",
    "pub",
    "bar",
    "food_court",
    "ice_cream",
}
_AREA_SHAPES = ("Polygon", "MultiPolygon")
_LINE_SHAPES = ("LineString", "MultiLineString")


@dataclass
class IndoorLayers:
    """The layers of a place that :func:`pyrosm3d.plot_indoor` draws, as
    :func:`indoor_layers` makes them from pyrosm's frames: GeoDataFrames in the metres
    of one UTM zone.

    Apart from the network, each frame has the columns ``id`` and ``osm_type`` of its
    elements, ``tags`` (a dict of an element's OSM tags) and the geometry. ``levels``
    is a tuple of the levels an element is on, as pyrosm lists them in its ``levels``
    column. An area without a level that is a platform or a walking area, or that
    lines of the network cross, has the level of its lines in the network; where these
    have none, its layer when that is below street level, else street level (0).

    Attributes
    ----------
    areas : GeoDataFrame
        The polygons with an ``indoor`` tag, the platform areas (``railway``,
        ``public_transport`` or ``highway`` is ``platform``), the lift areas
        (``highway=elevator``), the walking areas, such as a square or a station hall
        mapped as ``highway=pedestrian``, and the other areas that lines of the network
        cross, with ``levels`` and a ``kind``: ``wall``, ``level`` (the outline of a
        floor),
        ``platform``, ``corridor``, ``shaft`` (stairwells, lifts and technical
        rooms), ``walking_area`` (an area without an ``indoor`` tag that is none of
        these), ``toilets``, ``shop``, ``room``, or ``indoor`` for ``indoor=yes`` and
        ``indoor=no``.
    walls : GeoDataFrame
        The lines tagged ``indoor=wall``, with ``levels``.
    doors : GeoDataFrame
        The nodes with a ``door`` or an ``entrance`` tag, with ``levels``.
    pois : GeoDataFrame
        The shops and amenities that have a level, as points, with ``levels`` and a
        ``kind``: ``shop`` (also places to eat and drink) or ``amenity``.
    buildings : GeoDataFrame
        The outlines of the buildings.
    nodes, edges : GeoDataFrame
        The network of ``get_network("walking", nodes=True, indoor_elements=True,
        walking_areas=True)``, with pyrosm's columns.
    """

    areas: GeoDataFrame
    walls: GeoDataFrame
    doors: GeoDataFrame
    pois: GeoDataFrame
    buildings: GeoDataFrame
    nodes: GeoDataFrame
    edges: GeoDataFrame


def indoor_layers(elements=None, nodes=None, edges=None, buildings=None):
    """The layers of one place for :func:`pyrosm3d.plot_indoor`, from frames read with
    pyrosm (``osm`` is a ``pyrosm.OSM`` object); a read that found nothing gives None,
    which stands for a frame without rows.

    Parameters
    ----------
    elements : GeoDataFrame (optional)
        ``osm.get_indoor_elements(walking_areas=True)``.
    nodes, edges : GeoDataFrame (optional)
        ``osm.get_network("walking", nodes=True, indoor_elements=True,
        walking_areas=True)``.
    buildings : GeoDataFrame (optional)
        ``osm.get_buildings()``.

    Returns
    -------
    IndoorLayers
    """
    elements, buildings = _found(elements), _found(buildings)
    nodes, edges = _found(nodes), _found(edges)
    crs = _utm_crs([elements, buildings, edges])
    edges = edges.to_crs(crs)
    crossed = _crossed_areas(edges)

    listed = elements.get("levels", [None] * len(elements))
    levels = [_listed_levels(text) for text in listed]
    tags = row_tags(elements.drop(columns="levels", errors="ignore"))
    keys = element_keys(elements)
    is_area = _has_shape(elements, _AREA_SHAPES) & np.array(
        [key in crossed or _is_drawn_as_area(row) for key, row in zip(keys, tags)],
        dtype=bool,
    )
    is_wall = _where(tags, lambda row: row.get("indoor") == "wall")
    is_wall_line = is_wall & _has_shape(elements, _LINE_SHAPES)
    is_door = _where(tags, lambda row: "door" in row or "entrance" in row)
    is_door_node = is_door & _has_shape(elements, ("Point",))
    is_poi = _where(tags, lambda row: "shop" in row or "amenity" in row)
    has_level = np.array([bool(found) for found in levels], dtype=bool)
    is_outline = _has_shape(buildings, _AREA_SHAPES)

    pois = _layer(elements, tags, levels, is_poi & has_level, crs, kind=_poi_kind)
    pois.geometry = _marker_points(pois.geometry)
    areas = _layer(elements, tags, levels, is_area, crs, kind=area_kind)
    return IndoorLayers(
        areas=_with_line_levels(areas, edges, crossed),
        walls=_layer(elements, tags, levels, is_wall_line, crs),
        doors=_layer(elements, tags, levels, is_door_node, crs),
        pois=pois,
        buildings=_layer(buildings, row_tags(buildings), None, is_outline, crs),
        nodes=nodes.to_crs(crs),
        edges=edges,
    )


def _listed_levels(text):
    """The levels of a value of pyrosm's ``levels`` column (``"0;1;2"``) as a tuple of
    floats; empty for a missing value."""
    if not isinstance(text, str):
        return ()
    return tuple(float(level) for level in text.split(";"))


def _is_drawn_as_area(tags):
    """Whether a polygon with the OSM ``tags`` is an area also where no line crosses
    it: it has an ``indoor`` tag, is a platform, or has a ``highway`` tag (a lift area,
    or a walking area such as a square). A shop or an amenity mapped as a polygon
    without these is a marker only."""
    return "indoor" in tags or "highway" in tags or is_platform(tags)


def _crossed_areas(edges):
    """The keys (see :func:`pyrosm3d.tags.element_keys`) of the areas that lines of
    ``edges`` cross (see :func:`pyrosm3d.tags.crosses_area`): a line across an area
    has the id and the type of its area."""
    return set(element_keys(edges[crosses_area(edges)]))


def _where(tags, fits):
    """Which rows, by their ``tags`` (a list of dicts), ``fits`` says yes to."""
    return np.array([bool(fits(row)) for row in tags], dtype=bool)


def area_kind(tags):
    """The kind of an indoor area with the OSM ``tags`` (see :class:`IndoorLayers`),
    the first that fits."""
    indoor, room, amenity = (tags.get(key) for key in ("indoor", "room", "amenity"))
    if indoor in ("wall", "level"):
        return indoor
    if is_platform(tags):
        return "platform"
    if indoor in ("corridor", "area") or room == "corridor":
        return "corridor"
    if room in _SHAFT_ROOMS or tags.get("highway") == "elevator":
        return "shaft"
    if indoor is None:
        return "walking_area"
    if amenity == "toilets" or room == "toilets":
        return "toilets"
    if _poi_kind(tags) == "shop":
        return "shop"
    return "indoor" if indoor in ("yes", "no") else "room"


def _with_line_levels(areas, edges, crossed):
    """``areas`` with a level for each area that has none and is a platform, a walking
    area or among ``crossed`` (see :func:`_crossed_areas`): the lowest level that
    pyrosm gave its lines among ``edges`` (``u_level`` and ``v_level``); where these
    have none, the level of :func:`pyrosm3d.tags.layer_level`."""
    ends = (float_column(edges, "u_level"), float_column(edges, "v_level"))
    on_lines = {}
    for key, level in zip(element_keys(edges), np.fmin(*ends).tolist()):
        if not np.isnan(level):
            on_lines[key] = min(level, on_lines.get(key, level))
    levels = areas["levels"].tolist()
    columns = (element_keys(areas), areas["kind"], areas["tags"])
    for row, (key, kind, tags) in enumerate(zip(*columns)):
        placed_by_lines = kind in ("platform", "walking_area") or key in crossed
        if not levels[row] and placed_by_lines:
            levels[row] = (on_lines.get(key, layer_level(tags)),)
    return areas.assign(levels=levels)


def _poi_kind(tags):
    """``shop`` for a shop or a place to eat or drink with the OSM ``tags``, else
    ``amenity``."""
    if tags.get("shop") or tags.get("amenity") in _FOOD_AMENITIES:
        return "shop"
    return "amenity"


def _marker_points(shapes):
    """A point inside each of ``shapes`` (a GeoSeries) for its marker. Lines that
    close into an area, such as the member ways of a relation that groups them, give
    a point inside that area, not one on its outline."""
    values = shapes.to_numpy()
    enclosed = shapely.build_area(values)
    is_closed_line = (shapely.get_dimensions(values) == 1) & ~shapely.is_empty(enclosed)
    values = np.where(is_closed_line, enclosed, values)
    return GeoSeries(
        shapely.point_on_surface(values), index=shapes.index, crs=shapes.crs
    )


def _found(frame):
    """``frame``, or a frame without rows when a read found nothing and gave None."""
    if frame is None:
        return GeoDataFrame({"id": [], "osm_type": []}, geometry=[], crs=4326)
    return frame


def _has_shape(frame, shapes):
    """Which rows of ``frame`` have a geometry of one of the types ``shapes``."""
    return np.isin(frame.geometry.geom_type.to_numpy(), shapes)


def _utm_crs(frames):
    """The UTM zone at the middle of the bounds of ``frames``, which are in WGS 84."""
    bounds = np.array([frame.total_bounds for frame in frames if len(frame)])
    if not len(bounds):
        raise ValueError("indoor_layers got no indoor elements and no walking network")
    west, south = bounds[:, :2].min(axis=0)
    east, north = bounds[:, 2:].max(axis=0)
    middle = shapely.Point((west + east) / 2, (south + north) / 2)
    return GeoSeries([middle], crs=4326).estimate_utm_crs()


def _layer(frame, tags, levels, keep, crs, **columns):
    """The rows of ``frame`` that the boolean array ``keep`` marks, in ``crs``: their
    ``id`` and ``osm_type``, a column for each of ``columns`` (a function of a row's
    tags), their ``levels`` (from the ``levels`` of all rows; no column for None),
    their ``tags`` (dicts, from the ``tags`` of all rows) and their geometry."""
    rows = np.flatnonzero(keep)
    kept = [tags[row] for row in rows]
    data = {name: frame[name].to_numpy()[rows] for name in ("id", "osm_type")}
    for name, value in columns.items():
        data[name] = [value(row) for row in kept]
    if levels is not None:
        data["levels"] = [levels[row] for row in rows]
    data["tags"] = kept
    geometry = frame.geometry.to_numpy()[rows]
    return GeoDataFrame(data, geometry=geometry, crs=frame.crs).to_crs(crs)
