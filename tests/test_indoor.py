from collections import Counter

import numpy as np
import pytest
from geopandas import GeoDataFrame
from shapely.geometry import LineString, box

from pyrosm3d import IndoorElements, read_indoor
from pyrosm3d.indoor import _with_platform_levels, area_kind

_LAYER_COLUMNS = ["id", "osm_type", "kind", "levels", "tags", "geometry"]


def test_read_indoor_reads_maunula_talo(maunula):
    """The layers of a building with three mapped floors, in the metres of its UTM
    zone: the areas with their kinds and levels (a lift through three floors is a
    shaft on all of them, a wall mapped as an area is a wall, the bus and tram
    platforms beside the building, which have no indoor and no level tag, are
    platforms on street level), the wall mapped as a line, the doors, the shops and
    amenities that have a level as points, the building outlines and the walking
    network with its stairs."""
    assert isinstance(maunula, IndoorElements)
    layers = (maunula.areas, maunula.walls, maunula.doors, maunula.pois)
    frames = layers + (maunula.buildings, maunula.nodes, maunula.edges)
    assert [len(frame) for frame in frames] == [64, 1, 158, 9, 37, 890, 1064]
    assert {frame.crs.to_epsg() for frame in frames} == {32635}

    areas = maunula.areas
    assert list(areas.columns) == _LAYER_COLUMNS
    assert set(areas.geometry.geom_type) == {"Polygon"}
    kinds = {"room": 42, "corridor": 8, "level": 5, "platform": 4, "shaft": 3}
    assert Counter(areas["kind"]) == {**kinds, "toilets": 1, "wall": 1}
    platforms = areas[areas["kind"] == "platform"]
    assert set(platforms["levels"]) == {(0.0,)}
    assert not any("indoor" in tags or "level" in tags for tags in platforms["tags"])
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


class _NothingFound:
    """Stands in for a pyrosm.OSM whose reads find nothing but the network given."""

    def __init__(self, network=(None, None)):
        self.network = network

    def get_network(self, network_type, nodes, indoor_elements, walking_areas):
        return self.network

    def get_data_by_custom_criteria(self, custom_filter, **kwargs):
        return None

    def get_pois(self, custom_filter):
        return None

    def get_buildings(self):
        return None


def test_read_indoor_where_reads_find_nothing():
    """A layer that pyrosm finds nothing for is a frame without rows that has the
    layer's columns; a read that finds no element at all is refused."""
    line = LineString([(24.93, 60.23), (24.931, 60.23)])
    edges = GeoDataFrame({"id": [1]}, geometry=[line], crs=4326)
    nodes = GeoDataFrame({"id": [1, 2]}, geometry=list(line.boundary.geoms), crs=4326)
    indoor = read_indoor(_NothingFound((nodes, edges)))
    assert len(indoor.edges) == 1 and indoor.edges.crs.to_epsg() == 32635
    assert indoor.edges.geometry.length.iloc[0] == pytest.approx(55.4, abs=0.5)
    layers = (indoor.areas, indoor.walls, indoor.doors, indoor.pois, indoor.buildings)
    assert [len(layer) for layer in layers] == [0] * 5
    assert list(indoor.areas.columns) == list(indoor.pois.columns) == _LAYER_COLUMNS
    with pytest.raises(ValueError, match="no indoor elements and no walking network"):
        read_indoor(_NothingFound())


def test_read_indoor_needs_a_pyrosm_with_indoor_reads():
    """An object whose get_network has no indoor_elements parameter, such as the OSM
    of a pyrosm release without the indoor reads, is refused with the install
    command."""

    class Released:
        def get_network(self, network_type="walking", nodes=False):
            raise AssertionError("read_indoor must not read")

    for osm in (Released(), object()):
        with pytest.raises(TypeError, match="install pyrosm from its main branch"):
            read_indoor(osm)


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
    platform, a corridor, a shaft, toilets, a shop or place to eat, else a room, or
    ``indoor`` for an area tagged only indoor=yes or indoor=no."""
    assert area_kind(tags) == kind


def test_platform_areas_without_a_level_get_one():
    """A platform area without a level is on the lowest level that pyrosm gave its
    lines in the network (the lines of another element with its id do not count),
    without one on its layer below street level, else on street level, also when its
    ``level`` tag gives no level; the levels of its own ``level`` tag stay, and so
    does the missing level of another kind of area."""
    cases = [
        (1, "way", "platform", (), {}, (-2.0,)),
        (2, "relation", "platform", (), {"layer": "-1"}, (-1.0,)),
        (3, "way", "platform", (), {"layer": "1"}, (0.0,)),
        (6, "way", "platform", (), {"level": "ground"}, (0.0,)),
        (4, "way", "platform", (1.0,), {"level": "1"}, (1.0,)),
        (5, "way", "room", (), {}, ()),
    ]
    ids, types, kinds, levels, tags, expected = zip(*cases)
    areas = GeoDataFrame(
        {"id": ids, "osm_type": types, "kind": kinds, "levels": levels, "tags": tags},
        geometry=[box(0, 0, 1, 1)] * len(cases),
        crs=32635,
    )
    edges = GeoDataFrame(
        {
            "id": [1, 1, 2, 4, 5],
            "osm_type": ["way"] * 5,
            "u_level": [np.nan, -2.0, -3.0, 0.0, 2.0],
            "v_level": [np.nan, -1.0, -3.0, 0.0, 2.0],
        },
        geometry=[LineString([(0, 0), (1, 1)])] * 5,
        crs=32635,
    )
    assert tuple(_with_platform_levels(areas, edges)["levels"]) == expected
