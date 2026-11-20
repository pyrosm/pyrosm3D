import json
import os
import shutil
import subprocess
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
def helsinki_centre_osm():
    """pyrosm's reader of the area around Helsinki's railway station, Forum and Kamppi
    in the OpenStreetMap extract of cafein.sampledata's Helsinki files, downloaded on
    first use."""
    import cafein.sampledata.helsinki as helsinki

    box = [24.9270, 60.1655, 24.9470, 60.1740]
    return OSM(str(helsinki.osm_pbf), bounding_box=box)


@pytest.fixture(scope="session")
def helsinki_centre(helsinki_centre_osm):
    """The nodes and edges of the walking network of the centre of Helsinki, with
    indoor elements and lines across walking areas."""
    return helsinki_centre_osm.get_network(
        "walking", nodes=True, indoor_elements=True, walking_areas=True
    )


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


@pytest.fixture(scope="session")
def run_scripts():
    """A function that runs the scripts of an HTML file written by pyrosm3d in node,
    with ``page_harness.js``, and returns the JSON that the harness prints.

    For the page at ``path`` on a page of the ``size`` ("wide" or "small"): what it
    shows when its legend button and each of its level buttons are pressed, the legend
    ``entry`` is switched off, the first point of the trace ``clicked`` is clicked,
    the tags panel is closed and two fingers move on the view. For a figure written
    outside a page: what its scripts set, and the same two fingers."""

    def run(path, entry="-", clicked="-", size="wide"):
        node = shutil.which("node")
        if node is None:
            if os.environ.get("CI"):
                pytest.fail("the scripts are tested with node, which is not installed")
            pytest.skip("node is not installed")
        harness = Path(__file__).parent / "page_harness.js"
        command = [node, str(harness), str(path), entry, clicked, size]
        done = subprocess.run(
            command, capture_output=True, encoding="utf-8", check=True
        )
        return json.loads(done.stdout)

    return run


@pytest.fixture(scope="session")
def run_view():
    """A function that runs the scripts of the page of a ``pyrosm3d.View`` in node,
    with ``view_harness.js`` and stand-ins for deck.gl, and returns what the page
    showed after it started and after each of the ``steps`` (see the harness)."""

    def run(view, steps=(), tmp_path=None, deck=True):
        node = shutil.which("node")
        if node is None:
            if os.environ.get("CI"):
                pytest.fail("the scripts are tested with node, which is not installed")
            pytest.skip("node is not installed")
        path = view.to_html(tmp_path / "view.html")
        harness = Path(__file__).parent / "view_harness.js"
        command = [node, str(harness), str(path), json.dumps(list(steps))]
        command += [] if deck else ["nodeck"]
        done = subprocess.run(
            command, capture_output=True, encoding="utf-8", check=True
        )
        return json.loads(done.stdout)

    return run
