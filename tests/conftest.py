from pathlib import Path

import pytest
from pyrosm import OSM, get_data

from pyrosm3d import In3D
from pyrosm3d.indoor import indoor_layers


@pytest.fixture(scope="session")
def helsinki_indoor():
    """The osm reader, nodes and edges of pyrosm's bundled Helsinki file read with
    indoor elements."""
    osm = OSM(get_data("helsinki_pbf"))
    nodes, edges = osm.get_network("walking", nodes=True, indoor_elements=True)
    return osm, nodes, edges


@pytest.fixture(scope="session")
def helsinki_dem():
    """The terrain model of cafein.sampledata's Helsinki files, downloaded on first
    use: the National Land Survey of Finland's elevation model, in 10 m pixels and
    whole metres (EPSG:3067)."""
    import cafein.sampledata.helsinki as helsinki

    return helsinki.dem


@pytest.fixture(scope="session")
def maunula_osm():
    """pyrosm's reader of Maunula-talo, a community centre in Helsinki with three
    mapped floors."""
    path = Path(__file__).parent / "data" / "maunula.osm.pbf"
    return OSM(str(path))


@pytest.fixture(scope="session")
def maunula_frames(maunula_osm):
    """The frames that the ``in3d`` accessor reads for the indoor views of
    Maunula-talo, as the arguments of ``plot_indoor``."""
    return In3D(maunula_osm)._indoor_frames()


@pytest.fixture(scope="session")
def maunula(maunula_frames):
    """The layers of Maunula-talo that the indoor views draw."""
    return indoor_layers(**maunula_frames)
