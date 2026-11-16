import numpy as np
import pandas as pd
import pytest
from geopandas import GeoDataFrame
from shapely.geometry import Point

from pyrosm3d.tags import float_column, level_ranges, row_tags, tag_layer


def test_row_tags_of_a_network_read(helsinki_indoor):
    """The tags of an edge come from its tag columns and its JSON tags, without the
    columns get_network computes; the tags of a node from its JSON tags."""
    _, nodes, edges = helsinki_indoor
    edge = (edges["u"] == 779180872) & (edges["v"] == 922394981)
    (tags,) = [tags for tags, found in zip(row_tags(edges), edge) if found]
    assert tags["highway"] == "residential" and tags["lanes"] == "2"
    assert tags["name"] == "Pohjoinen Makasiinikatu"
    assert tags["name:sv"] == "Norra Magasingatan" and tags["maxlength"] == "12"
    computed = {"u", "v", "length", "u_level", "v_level", "vertical", "walking_area"}
    assert not computed & set(tags) and "id" not in tags
    entrance = (nodes["id"] == 189427137).to_numpy()
    (tags,) = [tags for tags, found in zip(row_tags(nodes), entrance) if found]
    assert tags["railway"] == "subway_entrance" and tags["ref"] == "D"


def test_row_tags_of_a_frame_made_by_hand():
    """Values are the strings OSM stores (yes and no for booleans, whole floats without
    a decimal, a 32-bit float with its own digits); ``id_tag`` is the tag ``id``; a
    column without a name and the columns of an indoor network, also those of its
    heights in metres, are left out; a column's value wins over the JSON tag of its
    key, and its missing value removes that tag; JSON tags may be a string or a dict,
    their element fields (a version that is not text) and missing values (None, NaN,
    ``pd.NA``, ``pd.NaT``) are left out, and a string that is not JSON gives no tags."""
    missing = {"a": pd.NA, "b": pd.NaT, "c": np.float32("nan")}
    frame = GeoDataFrame(
        {
            "id": [1, 2, 3],
            "highway": ["footway", None, "steps"],
            "covered": [True, False, None],
            "width": [1.0, 0.5, np.nan],
            "est_width": np.array([1.2, 2.0, np.nan], dtype=np.float32),
            "lanes": [3, 4, 5],
            "id_tag": ["a", None, None],
            "": ["x", "x", "x"],
            "u": [10, 11, 12],
            "v": [11, 12, 13],
            "length": [5.0, 6.0, 7.0],
            "u_level": [0.0, np.nan, 1.0],
            "v_level": [0.0, np.nan, 2.0],
            "u_height": [7.5, np.nan, 7.5],
            "v_height": [7.5, np.nan, 11.5],
            "vertical": [None, None, "stairs"],
            "walking_area": [False, True, False],
            "tags": [
                '{"name": "A", "highway": "path", "version": 3, "level": null, "old": NaN}',
                {"highway": "corridor", "version": "2", "note": 1.5, **missing},
                "not json",
            ],
        },
        geometry=[Point(0, 0)] * 3,
        crs=4326,
    )
    assert row_tags(frame) == [
        {
            "highway": "footway",
            "covered": "yes",
            "width": "1",
            "est_width": "1.2",
            "lanes": "3",
            "id": "a",
            "name": "A",
        },
        {
            "covered": "no",
            "width": "0.5",
            "est_width": "2",
            "lanes": "4",
            "version": "2",
            "note": "1.5",
        },
        {"highway": "steps", "lanes": "5"},
    ]


def test_row_tags_joins_the_values_of_lists():
    """A cell that holds a list, as an edge of a simplified graph that joins several
    ways has, gives its different values in their order, joined with semicolons and
    without the missing ones; a list of missing values gives no tag. A list of JSON
    tags gives each key the different values of its dicts."""
    frame = GeoDataFrame(
        {
            "name": [["A", np.nan, "B", "A"]],
            "tunnel": [[None, np.nan]],
            "lanes": [[2, 2.0, None]],
            "tags": [['{"layer":"-1","name":"x"}', np.nan, '{"layer":"-2","lit":"no"}']],
        },
        geometry=[Point(0, 0)],
        crs=4326,
    )
    assert row_tags(frame) == [
        {"name": "A;B", "lanes": "2", "layer": "-1;-2", "lit": "no"}
    ]


@pytest.mark.parametrize("levels", [{}, {"u_level": [0.0], "v_level": [1.0]}])
def test_row_tags_keeps_text_columns_named_as_network_columns(levels):
    """Text columns named ``length`` and ``walking_area`` hold the tags of those names,
    and so does ``vertical`` where the frame is not an indoor network (no level columns,
    or a value get_network does not give)."""
    columns = {"length": ["12 m"], "walking_area": ["yes"], "vertical": ["up"]}
    frame = GeoDataFrame({**columns, **levels}, geometry=[Point(0, 0)], crs=4326)
    assert row_tags(frame) == [
        {"length": "12 m", "walking_area": "yes", "vertical": "up"}
    ]


@pytest.mark.parametrize(
    "values, expected",
    [
        ([1.5, None], [1.5, np.nan]),
        (["12 m", "3"], [np.nan, 3.0]),
        (pd.array([1, pd.NA], dtype="Int64"), [1.0, np.nan]),
        (pd.array([0.5, pd.NA], dtype="Float64"), [0.5, np.nan]),
        (pd.array(["2", pd.NA], dtype="string"), [2.0, np.nan]),
    ],
)
def test_float_column(values, expected):
    """A column as floats, NaN where a value is missing or not a number, also in
    pandas' nullable columns; all NaN for a column the frame does not have."""
    frame = GeoDataFrame({"level": values}, geometry=[Point(0, 0)] * 2, crs=4326)
    np.testing.assert_array_equal(float_column(frame, "level"), expected)
    assert np.isnan(float_column(frame, "missing")).all()


@pytest.mark.parametrize(
    "value, expected",
    [
        ("0-2", [(0.0, 2.0)]),
        ("-4--2", [(-4.0, -2.0)]),
        ("2-0", [(0.0, 2.0)]),
        ("-1;0.5; x", [(-1.0, -1.0), (0.5, 0.5)]),
        (1.0, [(1.0, 1.0)]),
        pytest.param("1;" + "9" * 400, [(1.0, 1.0)], id="too large for a float"),
        ("ground", None),
        (None, None),
        (np.nan, None),
        (pd.NA, None),
        (pd.NaT, None),
    ],
)
def test_level_ranges(value, expected):
    """A range gives its lowest and highest level, whichever comes first; parts that
    are not a level are skipped; a value without a level, or a missing one, gives
    None."""
    assert level_ranges(value) == expected


@pytest.mark.parametrize(
    "tags, expected",
    [
        ({}, 0.0),
        ({"layer": "-2"}, -2.0),
        ({"layer": "x"}, 0.0),
        ({"layer": "inf"}, 0.0),
        ({"layer": None}, 0.0),
        ({"tunnel": "yes"}, -1.0),
        ({"tunnel": "yes", "layer": "-3"}, -3.0),
        ({"tunnel": "yes", "layer": "1"}, 1.0),
    ],
)
def test_tag_layer(tags, expected):
    """The layer tag as a number, 0 when it is missing or not a finite number; a tunnel
    is at -1 or lower unless its layer is above 0."""
    assert tag_layer(tags) == expected
