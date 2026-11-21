import numpy as np
import pytest
import shapely
from geopandas import GeoDataFrame

from pyrosm3d import View
from pyrosm3d.buildings import (
    _level_count,
    _metres,
    building_groups,
    frame_building_groups,
)

KNOWN = "Buildings"
ASSUMED = "Buildings without a height (as high as others of their size)"


def _square(x, y, side):
    """A square ``side`` metres wide with its south-west corner at ``x``, ``y``."""
    return shapely.box(x, y, x + side, y + side)


def _blocks(groups, name):
    """The items of the group called ``name``; none without it."""
    found = {group["name"]: group for group in groups}.get(name)
    return found["items"] if found else []


def _bottom(item):
    """The height of the bottom of a block."""
    (z,) = {point[2] for ring in item["r"] for point in ring}
    return z


def _area(item):
    """The area of the footprint of a block, in square metres."""
    return shapely.Polygon(item["r"][0], item["r"][1:]).area


def test_building_heights_come_from_tags_or_buildings_of_their_size():
    """A building is as high as its height tag, else 4 m a level, and stands from
    0.4 m under the ground; a roof without a height lies flat, as does a building of
    height 0 or 0 levels, also with other tags; a building without a
    height or levels is as high as the median of the mapped buildings of its size, or
    of the nearest size that has five; a broken outline is repaired, and what is not a
    polygon, also after the repair, is left out."""
    shapes = [
        _square(0, 0, 20),
        _square(30, 0, 20),
        _square(60, 0, 20),
        *[_square(100 + 20 * i, 0, 10) for i in range(5)],
        _square(0, 50, 10),
        _square(30, 50, 3),
        shapely.Point(0, 0),
        shapely.Polygon([(0, 80), (10, 90), (10, 80), (0, 90)]),
        shapely.Polygon([(0, 100), (10, 100), (20, 100)]),
        _square(0, 120, 10),
        _square(30, 120, 10),
    ]
    tags = [
        {"building": "yes", "building:levels": "3"},
        {"building": "yes", "height": "10 m", "name": "Tower"},
        {"building": "roof"},
        *[{"building": "house", "building:levels": n, "roof:levels": "1"} for n in "11223"],
        {"building": "house", "addr:street": "Main", "addr:housenumber": "2"},
        {"building": "shed"},
        {"building": "yes"},
        {"building": "yes", "height": "6"},
        {"building": "yes", "height": "6"},
        {"building": "yes", "height": "0", "building:levels": "3"},
        {"building": "yes", "building:levels": "0"},
    ]
    groups = building_groups(np.array(shapes), tags, (0.0, 0.0))
    known, assumed = _blocks(groups, KNOWN), _blocks(groups, ASSUMED)
    assert [group["name"] for group in groups] == [KNOWN, ASSUMED]
    assert [(item["h"], _bottom(item), item["g"]) for item in known[:3]] == [
        (12.4, -0.4, 0.0),
        (10.4, -0.4, 0.0),
        (0.3, 0.0, 0.0),
    ]
    assert known[1]["t"] == "Tower\nbuilding=yes\n10 m high"
    assert known[0]["t"].endswith("3 levels")
    assert len(known) == 12 and len(assumed) == 2
    flat = known[-2:]
    assert [(item["h"], _bottom(item)) for item in flat] == [(0.3, 0.0), (0.3, 0.0)]
    assert [item["t"].split("\n")[-1] for item in flat] == ["0 m high", "0 levels"]
    bow_tie = known[-4:-2]
    assert [item["h"] for item in bow_tie] == [6.4, 6.4]
    assert sum(map(_area, bow_tie)) == pytest.approx(50.0)
    assert [item["h"] for item in assumed] == [12.4, 12.4]
    assert assumed[0]["t"].startswith("Main 2\nbuilding=house\nno height")
    assert "drawn 3 levels high" in assumed[1]["t"]


def test_building_parts_and_what_they_leave_uncovered():
    """A building with parts is drawn by the parts that have a height, each from its
    lowest height to its top, and by what they leave uncovered of it at its own
    height; a part without a height is not drawn. A building that its parts cover,
    but for a strip narrower than 0.6 m, is drawn by its parts alone, and a part from
    the ground stands from under it."""
    shapes = [
        _square(0, 0, 20),
        shapely.box(0, 0, 10, 20),
        shapely.box(10, 10, 20, 20),
        _square(50, 0, 20),
        shapely.box(50, 0, 69.8, 20),
    ]
    tags = [
        {"building": "yes", "building:levels": "2"},
        {"building:part": "yes", "height": "30", "min_height": "10"},
        {"building:part": "yes"},
        {"building": "yes", "building:levels": "2"},
        {"building:part": "yes", "building:levels": "1"},
    ]
    known = _blocks(building_groups(np.array(shapes), tags, (0.0, 0.0)), KNOWN)
    whole = [item for item in known if "part" not in item]
    parts = [item for item in known if "part" in item]
    (rest,) = whole
    assert _area(rest) == pytest.approx(200.0, abs=1.0) and rest["h"] == 8.4
    assert [(item["h"], _bottom(item)) for item in parts] == [(20.0, 10.0), (4.4, -0.4)]
    assert parts[0]["t"].endswith("part from 10 to 30 m above the ground")


def test_buildings_stand_on_the_ground():
    """On a terrain a block stands from under the lowest ground along its outline to
    its height over the median ground there, its footprint on that median; a building
    where the terrain has no height is left out, with its parts, and an infinite
    height counts as none. Each corner of the outline counts once, so where the
    outline starts, or a corner given twice, does not matter. A part from the ground
    stands from under the lowest ground of its building."""
    turned = shapely.Polygon([(0, 20), (0, 0), (0, 0), (20, 0), (20, 20)])
    shapes = [_square(0, 0, 20), _square(100, 0, 20), _square(100, 0, 10), turned]
    shapes += [_square(60, 0, 10), _square(20, 0, 20), _square(20, 0, 20)]
    tags = [{"building": "yes", "building:levels": "1"}] * 2
    tags += [{"building:part": "yes", "building:levels": "3"}]
    tags += [{"building": "yes", "building:levels": "1"}] * 3
    tags += [{"building:part": "yes", "building:levels": "2"}]

    def slope(x, y):
        return np.select([x < 50, x == 60, x == 70], [x / 10, 3.0, np.inf], np.nan)

    item, same, beside, part = _blocks(
        building_groups(np.array(shapes), tags, (10.0, 0.0), slope), KNOWN
    )
    assert (item["h"], _bottom(item), item["g"]) == (5.4, -0.4, 1.0)
    assert (same["h"], _bottom(same), same["g"]) == (5.4, -0.4, 1.0)
    assert (beside["h"], _bottom(beside), beside["g"]) == (4.4, 2.6, 3.0)
    # a part from the ground on the slope: from under its building's lowest ground
    # (2 m) to 8 m over the median (3 m); the building it covers is not drawn
    assert (part["h"], _bottom(part), part["g"]) == (9.4, 1.6, 3.0)
    assert item["r"][0][0][:2] == [10.0, 0.0]


@pytest.mark.parametrize("shapes", [[], [shapely.Point(0, 0), None]])
def test_no_buildings_without_polygons(shapes):
    """Without a polygon among the shapes there are no groups."""
    tags = [{"building": "yes"}] * len(shapes)
    assert building_groups(np.array(shapes, dtype=object), tags, (0.0, 0.0)) == []


@pytest.mark.parametrize(
    "value, height, levels",
    [
        ("12", 12.0, 12.0),
        ("12.5 m", 12.5, None),
        ("3m", 3.0, None),
        ("2.5", 2.5, 2.5),
        ("inf", None, None),
        ("nan", None, None),
        ("1e400", None, None),
        ("9" * 400, None, None),
        ("12 ft", None, None),
        ("-3", None, None),
        (None, None, None),
    ],
)
def test_tag_numbers(value, height, levels):
    """A height is a number, maybe in metres, and a level count a plain number; any
    other value, also one that would be infinite, is none."""
    assert (_metres(value), _level_count(value)) == (height, levels)


def test_too_many_levels_count_as_none():
    """A level count so large that its metres are infinite counts as no levels, and so
    do two that are infinite together: such a building is as high as the median of
    the buildings with levels, a building with a valid count of roof levels besides
    is as high as those,
    and a part with such a lowest level stands on the ground. A polygon deep in nested
    collections counts."""
    huge = "1" + "0" * 308
    nested = shapely.GeometryCollection(
        [shapely.GeometryCollection([shapely.GeometryCollection([_square(0, 0, 10)])])]
    )
    half = "3" + "0" * 307
    shapes = [nested, _square(50, 0, 10), _square(50, 0, 5), _square(80, 0, 10)]
    shapes += [_square(100, 0, 10)]
    tags = [
        {"building": "yes", "building:levels": huge},
        {"building": "yes", "building:levels": "1"},
        {"building:part": "yes", "building:levels": "2", "building:min_level": huge},
        {"building": "yes", "building:levels": huge, "roof:levels": "2"},
        {"building": "yes", "building:levels": half, "roof:levels": half},
    ]
    groups = building_groups(np.array(shapes, dtype=object), tags, (0.0, 0.0))
    # the median of 1 and 2 levels: 6 m, from 0.4 m under the ground
    assert [item["h"] for item in _blocks(groups, ASSUMED)] == [6.4, 6.4]
    known = _blocks(groups, KNOWN)
    assert [(item["h"], _bottom(item)) for item in known if "part" in item] == [
        (8.4, -0.4)
    ]
    assert known[-2]["h"] == 8.4  # the roof levels of the fourth building


def test_the_page_draws_buildings_solid_and_as_footprints(tmp_path, run_view):
    """The solid model draws a building as a block with the outline of its roof, not
    of its parts; the see-through map draws the footprints on the ground, hiding
    nothing; the indoor view draws no buildings."""
    shapes = np.array([_square(0, 0, 20), shapely.box(0, 0, 10, 20)])
    tags = [
        {"building": "yes", "building:levels": "2"},
        {"building:part": "yes", "height": "12"},
    ]
    groups = building_groups(shapes, tags, (0.0, 0.0), lambda x, y: np.full(len(x), 3.0))
    data = dict(
        mode="solid",
        view=dict(target=[0, 0, 0], rotationX=40, rotationOrbit=0, zoom=1),
        indoor=dict(box=[0, 0, 20, 20], levels=[[0, 0.0, 1]], ground=0.0, background="#ffffff", stretch=2.2),
        groups=groups,
    )
    steps = [["layersAt", mode, None, 1] for mode in ("solid", "through", "indoor")]
    _, solid, through, indoor = run_view(View(data), steps, tmp_path)
    solid = {layer["id"]: layer for layer in solid["at"]}
    assert list(solid) == ["buildings-Buildings", "roofs-Buildings"]
    assert solid["buildings-Buildings"]["extruded"] is True
    assert solid["buildings-Buildings"]["getElevation"] == [8.4, 12.4]
    roofs = solid["roofs-Buildings"]
    assert roofs["items"] == 1 and {point[2] for point in roofs["getPath"][0]} == {11.0}
    through = {layer["id"]: layer for layer in through["at"]}
    assert list(through) == ["footprints-Buildings", "footprint-edges-Buildings"]
    assert through["footprint-edges-Buildings"]["items"] == 2  # the part has one too
    footprint = through["footprints-Buildings"]["getPolygon"][0][0]
    assert {point[2] for point in footprint} == {3.0}
    assert through["footprints-Buildings"]["parameters"] == {"depthMask": False}
    assert indoor["at"] == []


def test_frames_count_an_element_once():
    """An element that two reads both return, as an area tagged with both building
    and building:part, is drawn once, also when one read gives its id as 7 and the
    other as 7.0; rows without an id each count, also in a frame whose other rows
    have one."""
    both = dict(id=[7, None], osm_type=["way", "way"], building=["university", "yes"])
    both["building:part"] = ["yes", None]
    both["building:levels"] = ["2", "2"]
    square = shapely.box(24.0, 60.0, 24.0002, 60.0001)
    beside = shapely.box(24.001, 60.0, 24.0012, 60.0001)
    one = GeoDataFrame(both, geometry=[square, beside], crs=4326)  # ids 7.0, NaN
    whole = one.iloc[:1].astype({"id": int})  # the id 7 as an integer
    loose = GeoDataFrame({"building": ["yes", "yes"]}, geometry=[square] * 2, crs=4326)
    crs = one.estimate_utm_crs()
    origin = one.to_crs(crs).geometry.iloc[0].centroid.coords[0]
    groups = frame_building_groups((one, one, whole, loose), crs, origin)
    assert [len(group["items"]) for group in groups] == [3, 2]


def test_keep_picks_whole_buildings_with_their_parts():
    """The buildings to draw are picked whole: a building that reaches into what is
    kept brings all its parts, also those outside it, and what they leave of it; a
    building outside brings none of its parts."""
    shapes = [
        _square(0, 0, 20),
        shapely.box(0, 0, 8, 20),
        shapely.box(12, 0, 20, 20),
        _square(100, 0, 10),
        _square(100, 0, 5),
    ]
    tags = [
        {"building": "yes", "building:levels": "1"},
        {"building:part": "yes", "height": "30"},
        {"building:part": "yes", "height": "20"},
        {"building": "yes", "building:levels": "1"},
        {"building:part": "yes", "height": "10"},
    ]
    near = shapely.box(-5, -5, 5, 25)
    groups = building_groups(
        np.array(shapes), tags, (0.0, 0.0), keep=lambda found: shapely.intersects(found, near)
    )
    known = _blocks(groups, KNOWN)
    assert sorted(item["h"] for item in known if "part" in item) == [20.4, 30.4]
    (rest,) = [item for item in known if "part" not in item]
    assert _area(rest) == pytest.approx(80.0, abs=1.0)
