from pathlib import Path

import pytest
from pyrosm import OSM, get_data

from pyrosm3d import read_indoor


@pytest.fixture(scope="session")
def helsinki_indoor():
    """The osm reader, nodes and edges of pyrosm's bundled Helsinki file read with
    indoor elements."""
    osm = OSM(get_data("helsinki_pbf"))
    nodes, edges = osm.get_network("walking", nodes=True, indoor_elements=True)
    return osm, nodes, edges


@pytest.fixture(scope="session")
def maunula():
    """The indoor elements of Maunula-talo, a community centre in Helsinki with three
    mapped floors."""
    path = Path(__file__).parent / "data" / "maunula.osm.pbf"
    return read_indoor(OSM(str(path)))
