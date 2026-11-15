"""The OSM tags of the rows of a frame read with pyrosm, and the levels and the layer
that tags give an element."""

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
# metres and the levels at its two ends. A text column of one of these names holds the
# OSM tag of that name.
_NETWORK_COLUMNS = ("u", "v", "length", "u_level", "v_level")
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


def row_tags(frame):
    """The OSM tags of each row of ``frame``, a GeoDataFrame read with pyrosm, as a list
    of dicts: the values of its tag columns (see :func:`_tag_columns`) and of its JSON
    ``tags`` column, as the strings OSM stores. A missing value removes the tag of its
    column, also when the JSON holds it."""
    columns = _tag_columns(frame)
    keys = [_tag_key(column) for column in columns]
    tags = [{} for _ in range(len(frame))]
    for column, key in zip(columns, keys):
        values = frame[column]
        present = values.notna().to_numpy()
        rows = np.flatnonzero(present).tolist()
        for row, value in zip(rows, _scalars(values[present])):
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
    see :func:`_is_indoor_network`)."""
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


def _is_missing(value):
    """Whether a tag value is missing: None, NaN, ``pd.NA`` or ``pd.NaT``."""
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    return isinstance(value, (float, np.floating)) and math.isnan(value)


def _with_json_tags(tags, json_tags, column_keys):
    """``tags`` with the tags of the JSON dict (or string) ``json_tags`` added, keeping
    the values ``tags`` already has and leaving out the keys of the tag columns
    (``column_keys``) and the element fields."""
    if isinstance(json_tags, str):
        try:
            json_tags = json.loads(json_tags)
        except ValueError:
            return tags
    if not isinstance(json_tags, dict):
        return tags
    for name, value in json_tags.items():
        key = _tag_key(name)
        if key is None or key in tags or key in column_keys:
            continue
        if str(name) in _JSON_FIELDS and not isinstance(value, str):
            continue
        if _is_missing(value):
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


def level_ranges(value):
    """The levels of an OSM ``level`` value as ``(lowest, highest)`` pairs of floats,
    one for each part separated by a semicolon: ``"-1;0"`` gives ``[(-1.0, -1.0),
    (0.0, 0.0)]`` and ``"0-2"`` gives ``[(0.0, 2.0)]``. Parts that are not a level or a
    range, or whose number is too large for a float, are skipped; None when no part
    is left."""
    if _is_missing(value):
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


def tag_levels(tags):
    """The levels of an element with the OSM ``tags``, as a sorted tuple of floats: the
    ends of each range of its ``level`` tag and the whole levels between them, so
    ``"0-2"`` gives 0, 1 and 2 and ``"0.5;2"`` gives 0.5 and 2. A range over more than
    200 levels is a tagging mistake and gives no levels. Empty without a level."""
    levels = set()
    for low, high in level_ranges(tags.get("level")) or ():
        if high - low > _MAX_LEVEL_SPAN:
            continue
        levels.update((low, high))
        levels.update(map(float, range(math.ceil(low), math.floor(high) + 1)))
    return tuple(sorted(levels))


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
