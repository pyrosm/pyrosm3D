"""The indoor elements of a place, read with pyrosm: areas such as rooms, corridors,
platforms and squares, walls, doors, shops and amenities, building outlines and the
walking network, in the metres of one UTM zone."""

import inspect
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
    tag_levels,
)

# What is read for the areas and the walls: the elements with an indoor tag, the lifts
# mapped as areas and the platforms
_INDOOR_FILTER = {
    "indoor": True,
    "highway": ["elevator", "platform"],
    "railway": ["platform"],
    "public_transport": ["platform"],
}
# The keys by which pyrosm also picks areas to draw lines across: a square or a hall
# mapped as ``highway=pedestrian``, a room tagged as a walkway
_CROSSED_AREA_KEYS = ("highway", "room")
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
class IndoorElements:
    """The indoor elements of a place, as :func:`read_indoor` reads them: GeoDataFrames
    in the metres of one UTM zone.

    Apart from the network, each frame has the columns ``id`` and ``osm_type`` of its
    elements, ``tags`` (a dict of an element's OSM tags) and the geometry. ``levels``
    is a tuple of the levels an element is on, from its ``level`` tag: the ends of each
    range and the whole levels between them. An area without a level (no ``level``
    tag, or one that gives no level) that is a platform, or that lines of the network
    cross, has the level of its lines in the network; where these have none, its layer
    when that is below street level, else street level (0).

    Attributes
    ----------
    areas : GeoDataFrame
        The polygons with an ``indoor`` tag, the platform areas (``railway``,
        ``public_transport`` or ``highway`` is ``platform``), the lift areas
        (``highway=elevator``) and the other areas that lines of the network cross,
        such as a square or a station hall mapped as ``highway=pedestrian``, with
        ``levels`` and a ``kind``: ``wall``, ``level`` (the outline of a floor),
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


def read_indoor(osm):
    """Read the indoor elements of the area of a ``pyrosm.OSM`` object.

    Parameters
    ----------
    osm : pyrosm.OSM
        The reader of a PBF file; a ``bounding_box`` given to ``pyrosm.OSM`` limits
        what is read. The reads need a pyrosm that reads indoor elements
        (``get_network(..., indoor_elements=True)``).

    Returns
    -------
    IndoorElements
    """
    _require_indoor_reads(osm)
    nodes, edges = osm.get_network(
        "walking", nodes=True, indoor_elements=True, walking_areas=True
    )
    nodes, edges = _found(nodes), _found(edges)
    crossed = _crossed_areas(edges)
    indoor = osm.get_data_by_custom_criteria(_area_filter(crossed), keep_nodes=False)
    doors = osm.get_data_by_custom_criteria(
        {"door": True, "entrance": True}, keep_ways=False, keep_relations=False
    )
    pois = osm.get_pois(custom_filter={"shop": True, "amenity": True})
    frames = [_found(frame) for frame in (indoor, doors, pois, osm.get_buildings())]
    indoor, doors, pois, buildings = frames
    crs = _utm_crs(frames + [edges])

    tags = row_tags(indoor)
    is_area = _has_shape(indoor, _AREA_SHAPES) & np.array(
        [
            key in crossed or _fits(row, _INDOOR_FILTER)
            for key, row in zip(element_keys(indoor), tags)
        ],
        dtype=bool,
    )
    is_wall = np.array([row.get("indoor") == "wall" for row in tags], dtype=bool)
    is_wall_line = is_wall & _has_shape(indoor, _LINE_SHAPES)
    is_door = _has_shape(doors, ("Point",))
    is_outline = _has_shape(buildings, _AREA_SHAPES)
    poi_tags = row_tags(pois)
    has_level = np.array([bool(tag_levels(row)) for row in poi_tags], dtype=bool)
    pois = _layer(pois, poi_tags, has_level, crs, kind=_poi_kind, levels=tag_levels)
    pois.geometry = pois.geometry.representative_point()
    areas = _layer(indoor, tags, is_area, crs, kind=area_kind, levels=tag_levels)
    return IndoorElements(
        areas=_with_line_levels(areas, edges, crossed),
        walls=_layer(indoor, tags, is_wall_line, crs, levels=tag_levels),
        doors=_layer(doors, row_tags(doors), is_door, crs, levels=tag_levels),
        pois=pois,
        buildings=_layer(buildings, row_tags(buildings), is_outline, crs),
        nodes=nodes.to_crs(crs),
        edges=edges.to_crs(crs),
    )


def area_kind(tags):
    """The kind of an indoor area with the OSM ``tags`` (see :class:`IndoorElements`),
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


def _crossed_areas(edges):
    """``{key: tags}`` of the areas that lines of ``edges`` cross (see
    :func:`pyrosm3d.tags.crosses_area`): a line across an area has the id, the type
    and the tags of its area; the key as :func:`pyrosm3d.tags.element_keys` gives it."""
    across = edges[crosses_area(edges)]
    return dict(zip(element_keys(across), row_tags(across)))


def _area_filter(crossed):
    """The filter of the read for the areas and the walls: :data:`_INDOOR_FILTER`, and
    for each area among ``crossed`` (see :func:`_crossed_areas`) that it leaves out the
    value of the first of :data:`_CROSSED_AREA_KEYS` that the area has."""
    criteria = dict(_INDOOR_FILTER)
    for tags in crossed.values():
        key = next((key for key in _CROSSED_AREA_KEYS if key in tags), None)
        if key is not None and not _fits(tags, _INDOOR_FILTER):
            criteria[key] = sorted({*criteria.get(key, ()), tags[key]})
    return criteria


def _fits(tags, criteria):
    """Whether an element with the OSM ``tags`` fits ``criteria``, a filter of
    ``get_data_by_custom_criteria``: it has one of the keys with one of that key's
    values, or with any value where the filter says True."""
    return any(
        key in tags and (values is True or tags[key] in values)
        for key, values in criteria.items()
    )


def _with_line_levels(areas, edges, crossed):
    """``areas`` with a level for each area that has none (no ``level`` tag, or one
    that gives no level) and is a platform or among ``crossed`` (see
    :func:`_crossed_areas`): the lowest level that pyrosm gave its lines among
    ``edges`` (``u_level`` and ``v_level``); where these have none, the level of
    :func:`pyrosm3d.tags.layer_level`."""
    ends = (float_column(edges, "u_level"), float_column(edges, "v_level"))
    on_lines = {}
    for key, level in zip(element_keys(edges), np.fmin(*ends).tolist()):
        if not np.isnan(level):
            on_lines[key] = min(level, on_lines.get(key, level))
    levels = areas["levels"].tolist()
    columns = (element_keys(areas), areas["kind"], areas["tags"])
    for row, (key, kind, tags) in enumerate(zip(*columns)):
        if not levels[row] and (kind == "platform" or key in crossed):
            levels[row] = (on_lines.get(key, layer_level(tags)),)
    return areas.assign(levels=levels)


def _poi_kind(tags):
    """``shop`` for a shop or a place to eat or drink with the OSM ``tags``, else
    ``amenity``."""
    if tags.get("shop") or tags.get("amenity") in _FOOD_AMENITIES:
        return "shop"
    return "amenity"


def _require_indoor_reads(osm):
    """Raise a TypeError unless ``osm`` has a ``get_network`` that reads indoor
    elements."""
    get_network = getattr(osm, "get_network", None)
    if (
        get_network is None
        or "indoor_elements" not in inspect.signature(get_network).parameters
    ):
        raise TypeError(
            "read_indoor needs a pyrosm.OSM object of a pyrosm that reads indoor "
            "elements (get_network(..., indoor_elements=True)). No pyrosm release has "
            "them yet; install pyrosm from its main branch: "
            'pip install "pyrosm @ git+https://github.com/pyrosm/pyrosm@main"'
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
        raise ValueError("read_indoor found no indoor elements and no walking network")
    west, south = bounds[:, :2].min(axis=0)
    east, north = bounds[:, 2:].max(axis=0)
    middle = shapely.Point((west + east) / 2, (south + north) / 2)
    return GeoSeries([middle], crs=4326).estimate_utm_crs()


def _layer(frame, tags, keep, crs, **columns):
    """The rows of ``frame`` that the boolean array ``keep`` marks, in ``crs``: their
    ``id`` and ``osm_type``, a column for each of ``columns`` (a function of a row's
    tags), their ``tags`` (dicts, from the ``tags`` of all rows) and their geometry."""
    rows = np.flatnonzero(keep)
    kept = [tags[row] for row in rows]
    data = {name: frame[name].to_numpy()[rows] for name in ("id", "osm_type")}
    for name, value in columns.items():
        data[name] = [value(row) for row in kept]
    data["tags"] = kept
    geometry = frame.geometry.to_numpy()[rows]
    return GeoDataFrame(data, geometry=geometry, crs=frame.crs).to_crs(crs)
