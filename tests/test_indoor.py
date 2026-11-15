from collections import Counter

import numpy as np
import pytest
import shapely
from geopandas import GeoDataFrame, GeoSeries
from shapely.geometry import LineString, Point, box

from pyrosm3d import IndoorElements, indoor_layers
from pyrosm3d.indoor import _marker_points, _with_line_levels, area_kind

_LAYER_COLUMNS = ["id", "osm_type", "kind", "levels", "tags", "geometry"]


def test_indoor_layers_of_maunula_talo(maunula):
    """The layers of a building with three mapped floors, in the metres of its UTM
    zone: the areas with their kinds and levels (a lift through three floors is a
    shaft on all of them, a wall mapped as an area is a wall, the bus and tram
    platforms beside the building, which have no indoor and no level tag, are
    platforms on street level, and so is the square that lines of the network cross,
    a walking area, while a square that no line crosses is left out), the wall mapped
    as a line, the doors, the shops and amenities that have a level as points, the
    building outlines and the walking network with its stairs."""
    assert isinstance(maunula, IndoorElements)
    layers = (maunula.areas, maunula.walls, maunula.doors, maunula.pois)
    frames = layers + (maunula.buildings, maunula.nodes, maunula.edges)
    assert [len(frame) for frame in frames] == [65, 1, 158, 9, 37, 890, 1064]
    assert {frame.crs.to_epsg() for frame in frames} == {32635}

    areas = maunula.areas
    assert list(areas.columns) == _LAYER_COLUMNS
    assert set(areas.geometry.geom_type) == {"Polygon"}
    kinds = {"room": 42, "corridor": 8, "level": 5, "platform": 4, "shaft": 3}
    kinds.update(toilets=1, wall=1, walking_area=1)
    assert Counter(areas["kind"]) == kinds
    platforms = areas[areas["kind"] == "platform"]
    assert set(platforms["levels"]) == {(0.0,)}
    assert not any("indoor" in tags or "level" in tags for tags in platforms["tags"])
    square = areas[areas["kind"] == "walking_area"].iloc[0]
    assert (square["id"], square["levels"]) == (1250318665, (0.0,))
    assert square["tags"]["highway"] == "pedestrian" and "level" not in square["tags"]
    assert square.geometry.area == pytest.approx(579.9, abs=0.1)
    assert 674689752 not in set(areas["id"])
    lift = areas[areas["id"] == 1568797319].iloc[0]
    assert (lift["kind"], lift["levels"]) == ("shaft", (0.0, 1.0, 2.0))
    assert lift["tags"]["level"] == "0-2" and lift["tags"]["room"] == "elevator"
    assert lift.geometry.area == pytest.approx(7.1, abs=0.1)
    wall = areas[areas["kind"] == "wall"].iloc[0]
    assert (wall["id"], wall["levels"]) == (1576010635, (2.0,))

    line = maunula.walls.iloc[0]
    assert (line["id"], line["levels"]) == (1576052067, (1.0,))
    assert line.geometry.geom_type == "LineString"
    door_levels = {(): 89, (1.0,): 39, (2.0,): 29, (0.0,): 1}
    assert Counter(maunula.doors["levels"]) == door_levels
    pois = maunula.pois
    assert Counter(pois["kind"]) == {"amenity": 8, "shop": 1}
    assert set(pois.geometry.geom_type) == {"Point"} and all(pois["levels"])
    assert list(maunula.buildings.columns) == ["id", "osm_type", "tags", "geometry"]
    assert Counter(maunula.edges["vertical"].dropna()) == {"stairs": 13}


def test_indoor_layers_from_frames_made_by_hand():
    """A polygon is an area when it has an indoor tag, is a platform or a lift area, or
    when lines of the network cross it, such as a square or a stair room without an
    indoor tag; another square is left out, and a shop without an indoor tag is a
    marker only. The levels are those of pyrosm's ``levels`` column, which is not a
    tag. Doors are nodes and walls are lines."""
    square = box(24.93, 60.23, 24.931, 60.2305)
    wall = LineString([(24.93, 60.23), (24.931, 60.23)])
    rows = [
        (1, "way", {"indoor": "room"}, "0;1", square),
        (2, "way", {"highway": "pedestrian"}, None, square),
        (3, "way", {"highway": "pedestrian"}, None, square),
        (4, "way", {"shop": "kiosk"}, "0", square),
        (5, "way", {"room": "stairs"}, None, square),
        (6, "node", {"door": "hinged"}, "1", Point(24.93, 60.23)),
        (7, "way", {"indoor": "wall"}, "1", wall),
        (8, "way", {"highway": "elevator"}, "0;1", square),
    ]
    ids, types, tags, levels, shapes = zip(*rows)
    keys = sorted({key for row in tags for key in row})
    columns = {key: [row.get(key) for row in tags] for key in keys}
    elements = GeoDataFrame(
        {"id": ids, "osm_type": types, **columns, "levels": levels},
        geometry=list(shapes),
        crs=4326,
    )
    edges = GeoDataFrame(
        {
            "id": [3, 5, 9],
            "osm_type": ["way"] * 3,
            "walking_area": [True, True, False],
            "u_level": [-1.0, np.nan, 0.0],
            "v_level": [-1.0, np.nan, 0.0],
        },
        geometry=[wall] * 3,
        crs=4326,
    )
    indoor = indoor_layers(elements, None, edges, None)
    areas = indoor.areas
    found = list(zip(areas["id"], areas["kind"], areas["levels"]))
    assert found == [
        (1, "room", (0.0, 1.0)),
        (3, "walking_area", (-1.0,)),
        (5, "shaft", (0.0,)),
        (8, "shaft", (0.0, 1.0)),
    ]
    assert all("levels" not in row for row in areas["tags"])
    pois, doors = indoor.pois, indoor.doors
    assert (pois["id"].tolist(), pois["kind"].tolist()) == ([4], ["shop"])
    assert pois.geometry.iloc[0].within(areas.geometry.iloc[0])
    assert (doors["id"].tolist(), doors["levels"].tolist()) == ([6], [(1.0,)])
    assert indoor.walls["id"].tolist() == [7]


def test_indoor_layers_where_reads_find_nothing():
    """A layer that pyrosm finds nothing for (None) is a frame without rows that has
    the layer's columns; without any element and network there is nothing to draw."""
    line = LineString([(24.93, 60.23), (24.931, 60.23)])
    edges = GeoDataFrame({"id": [1]}, geometry=[line], crs=4326)
    nodes = GeoDataFrame({"id": [1, 2]}, geometry=list(line.boundary.geoms), crs=4326)
    indoor = indoor_layers(None, nodes, edges, None)
    assert isinstance(indoor, IndoorElements)
    assert len(indoor.edges) == 1 and indoor.edges.crs.to_epsg() == 32635
    assert indoor.edges.geometry.length.iloc[0] == pytest.approx(55.4, abs=0.5)
    layers = (indoor.areas, indoor.walls, indoor.doors, indoor.pois, indoor.buildings)
    assert [len(layer) for layer in layers] == [0] * 5
    assert list(indoor.areas.columns) == list(indoor.pois.columns) == _LAYER_COLUMNS
    with pytest.raises(ValueError, match="no indoor elements and no walking network"):
        indoor_layers()


def test_marker_points_lie_inside_closed_lines():
    """The marker of lines that close into an area, such as the member ways of a
    relation that groups them, lies inside the area; that of a polygon inside it, that
    of an open line on it, and a point stays where it is."""
    ring = LineString([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    shapes = GeoSeries(
        [
            shapely.GeometryCollection([ring]),
            ring,
            box(20, 0, 30, 10),
            LineString([(0, 20), (10, 20)]),
            Point(5, 30),
        ],
        crs=32635,
    )
    points = _marker_points(shapes)
    assert points.crs == shapes.crs and set(points.geom_type) == {"Point"}
    inside = [box(0, 0, 10, 10), box(0, 0, 10, 10), box(20, 0, 30, 10)]
    assert all(point.within(area) for point, area in zip(points, inside))
    assert points.iloc[3].distance(shapes.iloc[3]) == 0
    assert points.iloc[4].equals(shapes.iloc[4])


@pytest.mark.parametrize(
    "tags, kind",
    [
        ({"indoor": "wall", "room": "stairs"}, "wall"),
        ({"indoor": "level"}, "level"),
        ({"indoor": "area", "public_transport": "platform"}, "platform"),
        ({"indoor": "room", "railway": "platform"}, "platform"),
        ({"highway": "platform", "area": "yes"}, "platform"),
        ({"indoor": "area"}, "corridor"),
        ({"indoor": "room", "room": "corridor"}, "corridor"),
        ({"indoor": "room", "room": "technical"}, "shaft"),
        ({"highway": "elevator"}, "shaft"),
        ({"highway": "pedestrian", "amenity": "toilets"}, "walking_area"),
        ({"indoor": "room", "amenity": "toilets"}, "toilets"),
        ({"indoor": "room", "room": "toilets"}, "toilets"),
        ({"indoor": "room", "shop": "kiosk"}, "shop"),
        ({"indoor": "room", "amenity": "cafe"}, "shop"),
        ({"indoor": "room", "amenity": "library"}, "room"),
        ({"indoor": "yes"}, "indoor"),
        ({"indoor": "no", "shop": "bakery"}, "shop"),
    ],
)
def test_area_kind(tags, kind):
    """The kind of an area is the first that fits: a wall or a level outline, a
    platform, a corridor, a shaft, a walking area (no indoor tag), toilets, a shop or
    place to eat, else a room, or ``indoor`` for an area tagged only indoor=yes or
    indoor=no."""
    assert area_kind(tags) == kind


def test_areas_without_a_level_get_one():
    """A platform area without a level, and an area without one that lines of the
    network cross, is on the lowest level that pyrosm gave its lines in the network
    (the lines of another element with its id do not count), without one on its layer
    below street level, else on street level, also when its ``level`` tag gives no
    level; the levels of its own ``level`` tag stay, and so does the missing level of
    another area that no line crosses."""
    cases = [
        (1, "way", "platform", (), {}, (-2.0,)),
        (2, "relation", "platform", (), {"layer": "-1"}, (-1.0,)),
        (3, "way", "platform", (), {"layer": "1"}, (0.0,)),
        (6, "way", "platform", (), {"level": "ground"}, (0.0,)),
        (4, "way", "platform", (1.0,), {"level": "1"}, (1.0,)),
        (5, "way", "room", (), {}, ()),
        (7, "way", "walking_area", (), {"highway": "pedestrian"}, (0.0,)),
        (8, "way", "corridor", (), {"indoor": "area"}, (2.0,)),
    ]
    ids, types, kinds, levels, tags, expected = zip(*cases)
    areas = GeoDataFrame(
        {"id": ids, "osm_type": types, "kind": kinds, "levels": levels, "tags": tags},
        geometry=[box(0, 0, 1, 1)] * len(cases),
        crs=32635,
    )
    edges = GeoDataFrame(
        {
            "id": [1, 1, 2, 4, 5, 7, 8],
            "osm_type": ["way"] * 7,
            "u_level": [np.nan, -2.0, -3.0, 0.0, 2.0, np.nan, 3.0],
            "v_level": [np.nan, -1.0, -3.0, 0.0, 2.0, np.nan, 2.0],
        },
        geometry=[LineString([(0, 0), (1, 1)])] * 7,
        crs=32635,
    )
    crossed = {"way 7", "way 8"}
    assert tuple(_with_line_levels(areas, edges, crossed)["levels"]) == expected
