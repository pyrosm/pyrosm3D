import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from pyrosm3d import plot_indoor, to_html
from pyrosm3d.figure import level_views
from pyrosm3d.page import _element_notes


def _run_page(path, entry, clicked, size="wide"):
    """What the page at ``path`` shows on a page of the ``size`` ("wide" or "small")
    when its legend button and each of its level buttons are pressed, the legend
    ``entry`` is switched off, the first point of the trace ``clicked`` is clicked,
    the tags panel is closed and two fingers move on the view: the JSON of
    ``page_harness.js``, which runs the page's scripts in node."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the page script is tested with node, which is not installed")
        pytest.skip("node is not installed")
    harness = Path(__file__).parent / "page_harness.js"
    command = [node, str(harness), str(path), entry, clicked, size]
    done = subprocess.run(command, capture_output=True, encoding="utf-8", check=True)
    return json.loads(done.stdout)


def _on_level(figure, level, legendonly):
    """The numbers of the traces of ``figure`` that are on ``level`` (None: all) and
    are hidden at start (``legendonly``) or not."""
    return [
        number
        for number, trace in enumerate(figure.data)
        if (level is None or level in trace.meta["levels"])
        and (trace.visible == "legendonly") == legendonly
    ]


def test_to_html_writes_a_page_with_level_buttons_and_tags(maunula, tmp_path):
    """The page holds the figure of plot_indoor and loads plotly as asked; the elements
    that its script uses come before the script in the page, and a name that tries to
    end a script block stays text: it adds no script to the page and shows as it is
    in the tags panel, over what the element is and its level. A legend entry cannot
    be shown alone with a double click. A
    button for all levels and one for each level show the traces of that level, drawn
    or switched off as in the figure, list each legend entry once and set the vertical
    axis as plot_indoor does for the level. A click on a legend entry switches it off
    on every level, and a click on a room shows its tags with a link to the element;
    a click on a point without an element leaves the panel as it is, and the panel's
    button brings its first text back. The legend button hides and shows the legend;
    on a small page the legend is hidden at start and lies over the view. Two fingers
    on the view bring the camera closer as they spread and move it sideways with them;
    plotly gets no move of theirs until every finger is lifted, and a third finger
    moves nothing. Whenever the last finger is lifted from the plot the page writes the
    camera to the layout, from which plotly sets the view when the plot changes or a
    tool is picked; a finger elsewhere on the page does not count."""
    hostile = "</ScRiPt><script>alert(1)</script>"
    named = [{**tags, "name": hostile} for tags in maunula.areas["tags"]]
    maunula = replace(maunula, areas=maunula.areas.assign(tags=named))
    path = to_html(
        maunula, tmp_path / "maunula.html", "Maunula-talo <3D>", include_plotlyjs=False
    )
    page = path.read_text(encoding="utf-8")
    assert "<title>Maunula-talo &lt;3D&gt;</title>" in page
    assert 'id="plot"' in page and "cdn.plot.ly" not in page
    assert hostile not in page and page.lower().count("<script") == 2
    assert '"itemdoubleclick":false' in page
    plotted = page.index("Plotly.newPlot")
    used = ('id="levels"', 'id="legend"', 'id="page-data"', 'id="tags"')
    for used_by_the_script in used:
        assert page.index(used_by_the_script) < plotted
    online = to_html(maunula, tmp_path / "cdn.html", include_plotlyjs="cdn")
    assert "cdn.plot.ly" in online.read_text(encoding="utf-8")

    figure = plot_indoor(maunula)
    shown = _run_page(path, "Rooms", "Rooms")
    assert shown["buttons"] == ["All levels", "Level 0", "Level 1", "Level 2"]
    views = level_views(figure)
    for button, level in zip(shown["buttons"], [None, 0.0, 1.0, 2.0]):
        view = shown["views"][button]
        assert view["pressed"] == [button]
        assert view["drawn"] == _on_level(figure, level, legendonly=False)
        assert view["legendonly"] == _on_level(figure, level, legendonly=True)
        groups = [
            trace.legendgroup
            for trace in figure.data
            if level is None or level in trace.meta["levels"]
        ]
        assert view["listed"] == list(dict.fromkeys(groups))
        if level is not None:
            assert view["view"]["scene.zaxis.range"] == views[level]["scene.zaxis.range"]
            assert view["view"]["scene.zaxis.ticktext"] == ["%g" % level]
    assert shown["views"]["All levels"]["view"]["scene.zaxis.ticktext"] == ["0", "1", "2"]

    rooms = [n for n, trace in enumerate(figure.data) if trace.name == "Rooms"]
    assert shown["legendclick"] is False
    assert set(rooms) <= set(shown["afterLegendclick"]["legendonly"])
    assert not set(rooms) & set(shown["afterLegendclick"]["drawn"])
    key = figure.data[rooms[0]].customdata[0]
    room = maunula.areas[maunula.areas["id"] == int(key.split()[1])].iloc[0]
    assert key.startswith("way ") and room["tags"]["indoor"] == "room"
    assert shown["link"] == "https://www.openstreetmap.org/way/%s" % key.split()[1]
    assert key in shown["tags"] and "indoor | room" in shown["tags"]
    note = "room · level %g" % room["levels"][0]
    assert shown["tags"].startswith("Close | %s | %s | %s" % (hostile, note, key))
    assert shown["tagsAfterEmptyClick"] == shown["tags"]
    data = json.loads(page.split('id="page-data">')[1].split("</script>")[0])
    assert set(data["about"]) == set(data["elements"]) and key in data["about"]
    hint = (
        "Click an area, a line, a marker or a column to see what it is and its "
        "OpenStreetMap tags."
    )
    assert shown["tagsAfterClose"] == hint

    assert shown["legendAtStart"] == {"pressed": "true", "layout": {"showlegend": True}}
    assert shown["legendAfterClick"]["pressed"] == "false"
    assert shown["legendAfterClick"]["layout"] == {"showlegend": False}
    small = _run_page(path, "Rooms", "Rooms", size="small")
    over_the_view = {"legend.x": 0, "legend.xanchor": "left"}
    assert small["legendAtStart"]["pressed"] == "false"
    assert small["legendAtStart"]["layout"].items() >= over_the_view.items()
    assert small["legendAtStart"]["layout"]["showlegend"] is False
    assert small["legendAfterClick"]["pressed"] == "true"
    assert small["legendAfterClick"]["layout"].items() >= over_the_view.items()
    assert small["legendAfterClick"]["layout"]["showlegend"] is True

    # A finger on the plot with one on the header is plotly's. Two fingers from 100
    # to 200 px apart: half the distance of 4, and 20 px down on a view 200 px high at
    # the distance 2: 20 * 2 / 200. A third finger moves nothing; the two that stay
    # start anew, and half as far apart around the same point double the distance.
    touches = shown["touches"]
    assert touches["kept"] == [False, True, True, True, True, True, False]
    assert touches["distances"] == pytest.approx([4, 2, 2, 2, 4, 4, 4])
    assert touches["pans"] == [[0, pytest.approx(0.2), 0], [0, 0, 0]]
    assert touches["saves"] == [1, 1, 1, 2]


def test_element_notes_of_maunula_talo(maunula):
    """The note of an element says what it is and its levels: an area by its kind (a
    platform area also for the edges of its outline), an edge of the network by its
    kind and the levels of its ends, a door and a shop or amenity by their levels."""
    notes = _element_notes(maunula)
    assert notes["way 1568797319"] == "stairwell, lift or storage · levels 0, 1, 2"
    assert notes["way 536922648"] == "platform area · level 0"
    assert notes["way 1576010635"] == "wall · level 2"
    assert notes["way 674689746"] == "stairs · level 0"
    assert notes["way 26131689"] == "walkway · level 0"
    doors = maunula.doors
    on_first = doors[doors["levels"].map(lambda levels: levels == (1.0,))]
    assert notes["node %d" % on_first["id"].iloc[0]] == "door or entrance · level 1"
    unlevelled = doors[doors["levels"].map(len) == 0]
    assert notes["node %d" % unlevelled["id"].iloc[0]] == "door or entrance · no level"
    shop = maunula.pois[maunula.pois["kind"] == "shop"].iloc[0]
    key = "%s %d" % (shop["osm_type"], shop["id"])
    assert notes[key] == "shop or amenity · level %g" % shop["levels"][0]
