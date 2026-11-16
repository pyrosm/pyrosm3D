"""The OSM tags and the keys of the rows of a frame read with pyrosm, and what tags say
of an element: its levels, its layer and whether it is a platform."""

import json
import math
import re

import numpy as np
import pandas as pd

# Columns of a frame that hold an element's fields, not its tags.
_FIELD_COLUMNS = {
    "id",
    "osm_type",
    "version",
    "timestamp",
    "changeset",
    "visible",
    "tags",
    "nodes",
    "members",
    "lon",
    "lat",
    "geometry",
}
# Numeric columns that get_network computes: the end node ids of an edge, its length in
# metres and the levels at its two ends; and the heights in metres that
# pyrosm3d.heights.network_heights adds. A text column of one of these names holds the
# OSM tag of that name.
_NETWORK_COLUMNS = ("u", "v", "length", "u_level", "v_level", "u_height", "v_height")
# The values of the column ``vertical`` that get_network(indoor_elements=True) computes.
_VERTICAL_VALUES = {"escalator", "moving_walkway", "stairs", "lift"}
# Element fields the readers put into a JSON ``tags`` dict when they are not columns.
# Their values are not text, unlike those of a tag of the same name.
_JSON_FIELDS = {"version", "timestamp", "visible", "members"}
# One part of a level value: a level, such as "-1" or "0.5", or a range, such as "0-2"
# or "-4--2".
_LEVEL_PART = re.compile(r"\s*(-?\d+(?:\.\d+)?)(?:\s*-\s*(-?\d+(?:\.\d+)?))?\s*")
# The most levels that a range of a level value may span; the tallest buildings have
# fewer than 200 floors.
_MAX_LEVEL_SPAN = 200
# The keys whose value ``platform`` makes an element a platform.
_PLATFORM_KEYS = ("railway", "public_transport", "highway")


def element_keys(frame):
    """A key such as ``"way 123"`` for each row of ``frame``: its ``osm_type`` (way
    without the column) and ``id``. The traces of :func:`pyrosm3d.plot_indoor` carry
    the key of the element at each of their points as ``customdata``."""
    types = frame["osm_type"] if "osm_type" in frame.columns else ["way"] * len(frame)
    return ["%s %s" % element for element in zip(types, frame["id"])]


def row_tags(frame):
    """The OSM tags of each row of ``frame``, a GeoDataFrame read with pyrosm, as a list
    of dicts: the values of its tag columns (see :func:`_tag_columns`) and of its JSON
    ``tags`` column, as the strings OSM stores. A missing value removes the tag of its
    column, also when the JSON holds it. A cell that holds a list, as an edge of a
    simplified graph that joins ways with different values has, gives the different
    values of the list as one value (see :func:`_joined_values`)."""
    columns = _tag_columns(frame)
    keys = [_tag_key(column) for column in columns]
    tags = [{} for _ in range(len(frame))]
    for column, key in zip(columns, keys):
        values = frame[column]
        present = values.notna().to_numpy()
        rows = np.flatnonzero(present).tolist()
        for row, value in zip(rows, _scalars(values[present])):
            if isinstance(value, list):
                value = _joined_values(value)
                if value is None:
                    continue
            tags[row][key] = _tag_text(value)
    if "tags" not in frame.columns:
        return tags
    return [
        _with_json_tags(row, json_tags, set(keys))
        for row, json_tags in zip(tags, frame["tags"].tolist())
    ]


def _scalars(values):
    """The values of a column as Python objects. Floats narrower than 64 bits stay NumPy
    scalars: as a Python float, ``np.float32("1.2")`` is 1.2000000476837158."""
    dtype = values.dtype
    if pd.api.types.is_float_dtype(dtype) and dtype.itemsize < 8:
        return values.to_numpy()
    return values.tolist()


def _tag_columns(frame):
    """The columns of ``frame`` that hold tags: all but its geometry, the element fields
    and the columns get_network computes (numeric ``u``, ``v``, ``length``, ``u_level``
    and ``v_level``, boolean ``walking_area``, and ``vertical`` in an indoor network,
    see :func:`_is_indoor_network`) or :func:`pyrosm3d.heights.network_heights` adds
    (numeric ``u_height`` and ``v_height``)."""
    computed = {
        column
        for column in _NETWORK_COLUMNS
        if column in frame.columns and pd.api.types.is_numeric_dtype(frame[column])
    }
    if _is_boolean_column(frame, "walking_area"):
        computed.add("walking_area")
    if _is_indoor_network(frame):
        computed.add("vertical")
    return [
        column
        for column in frame.columns
        if column != frame.geometry.name
        and str(column) not in _FIELD_COLUMNS
        and str(column) not in computed
        and _tag_key(column) is not None
    ]


def _is_boolean_column(frame, column):
    """Whether ``frame`` has the ``column`` and it holds only booleans (missing values
    allowed); a column of other values holds the OSM tag of that name."""
    if column not in frame.columns:
        return False
    values = frame[column]
    return pd.api.types.is_bool_dtype(values) or all(
        isinstance(value, (bool, np.bool_)) for value in values.dropna()
    )


def _is_indoor_network(frame):
    """Whether ``frame`` holds the edges of get_network(indoor_elements=True): numeric
    ``u_level`` and ``v_level`` columns, and a ``vertical`` column of its values."""
    if "vertical" not in frame.columns:
        return False
    if not all(
        column in frame.columns and pd.api.types.is_numeric_dtype(frame[column])
        for column in ("u_level", "v_level")
    ):
        return False
    return set(frame["vertical"].dropna()) <= _VERTICAL_VALUES


def _tag_key(column):
    """The OSM tag key of a column or tag name, or None for an empty name: ``id_tag``,
    the name the readers give a tag keyed ``id``, is ``id`` again."""
    key = str(column)
    if key == "id_tag":
        return "id"
    return key or None


def _tag_text(value):
    """A tag value as the string OSM stores."""
    if isinstance(value, (bool, np.bool_)):
        return "yes" if value else "no"
    if isinstance(value, (float, np.floating)):
        return str(int(value)) if float(value).is_integer() else str(value)
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return str(value)


def is_missing(value):
    """Whether a tag value is missing: None, NaN, ``pd.NA`` or ``pd.NaT``."""
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    return isinstance(value, (float, np.floating)) and math.isnan(value)


def _joined_values(values):
    """The different ``values`` that are not missing as one tag value: the strings OSM
    stores, in their order, joined with semicolons, as OSM writes several values of a
    key; None when every value is missing."""
    texts = dict.fromkeys(_tag_text(value) for value in values if not is_missing(value))
    return ";".join(texts) or None


def _with_json_tags(tags, json_tags, column_keys):
    """``tags`` with the tags of ``json_tags`` added (see :func:`_json_tags`), without
    the keys of the tag columns (``column_keys``). A list of JSON tags, those of the
    ways that an edge of a simplified graph joins, gives each key the different values
    of the ways as one value (see :func:`_joined_values`)."""
    if not isinstance(json_tags, list):
        tags.update(_json_tags(json_tags, column_keys))
        return tags
    ways = [_json_tags(way_tags, column_keys) for way_tags in json_tags]
    for key in dict.fromkeys(key for way in ways for key in way):
        tags[key] = _joined_values(way.get(key) for way in ways)
    return tags


def _json_tags(json_tags, column_keys):
    """The tags of the JSON dict (or string) ``json_tags`` as strings, without the keys
    of the tag columns (``column_keys``), the element fields and the missing values;
    none for a string that is not JSON or for a value that is not a dict."""
    if isinstance(json_tags, str):
        try:
            json_tags = json.loads(json_tags)
        except ValueError:
            return {}
    if not isinstance(json_tags, dict):
        return {}
    tags = {}
    for name, value in json_tags.items():
        key = _tag_key(name)
        if key is None or key in tags or key in column_keys:
            continue
        if str(name) in _JSON_FIELDS and not isinstance(value, str):
            continue
        if is_missing(value):
            continue
        tags[key] = _tag_text(value)
    return tags


def float_column(frame, column):
    """The ``column`` of ``frame`` as an array of floats, NaN where a value is missing
    or not a number (all NaN without the column)."""
    if column not in frame.columns:
        return np.full(len(frame), np.nan)
    numbers = pd.to_numeric(frame[column], errors="coerce")
    return numbers.to_numpy(dtype=float, na_value=np.nan)


def crosses_area(edges):
    """Which rows of ``edges`` are lines across an area: those that
    ``get_network(..., walking_areas=True)`` marks in its ``walking_area`` column; none
    without the column."""
    marks = edges.get("walking_area", pd.Series(False, index=edges.index))
    return marks.fillna(False).to_numpy(dtype=bool)


def level_ranges(value):
    """The levels of an OSM ``level`` value as ``(lowest, highest)`` pairs of floats,
    one for each part separated by a semicolon: ``"-1;0"`` gives ``[(-1.0, -1.0),
    (0.0, 0.0)]`` and ``"0-2"`` gives ``[(0.0, 2.0)]``. Parts that are not a level or a
    range, or whose number is too large for a float, are skipped; None when no part
    is left."""
    if is_missing(value):
        return None
    ranges = []
    for part in str(value).split(";"):
        match = _LEVEL_PART.fullmatch(part)
        if match:
            first = float(match.group(1))
            last = float(match.group(2)) if match.group(2) is not None else first
            if math.isfinite(first) and math.isfinite(last):
                ranges.append((min(first, last), max(first, last)))
    return ranges or None


def tag_layer(tags):
    """The layer of an element with the OSM ``tags``: its ``layer`` tag as a float (0
    when missing or not a finite number), at most -1 for a tunnel without a positive
    layer."""
    try:
        layer = float(tags.get("layer", 0))
    except (TypeError, ValueError):
        layer = 0.0
    if not math.isfinite(layer):
        layer = 0.0
    if tags.get("tunnel") == "yes" and layer <= 0:
        layer = min(layer, -1.0)
    return layer


def layer_level(tags):
    """The level given to an element with the OSM ``tags`` that has no level: its
    layer (see :func:`tag_layer`) when that is below street level, else street level
    (0)."""
    return min(tag_layer(tags), 0.0)


def is_platform(tags):
    """Whether an element with the OSM ``tags`` is a platform: its ``railway``,
    ``public_transport`` or ``highway`` tag is ``platform``."""
    return any(tags.get(key) == "platform" for key in _PLATFORM_KEYS)
