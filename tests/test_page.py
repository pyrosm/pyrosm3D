import json
import os
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from shapely.geometry import box

from pyrosm3d.figure import _view_box, layers_figure, level_views
from pyrosm3d.page import _element_notes, layers_page
from pyrosm3d.styles import AREA_STYLES


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
    button for all levels and one for each level, named by its number over the number
    of areas on it (0 on a level that has only a wall; a level between two floors that
    a room has its floor on has a button too), show the traces of that level,
    drawn
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
    path = layers_page(
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
    online = layers_page(maunula, tmp_path / "cdn.html", include_plotlyjs="cdn")
    assert "cdn.plot.ly" in online.read_text(encoding="utf-8")

    figure = layers_figure(maunula)
    shown = _run_page(path, "Rooms", "Rooms")
    assert shown["buttons"] == ["All levels", "0", "1", "2"]
    floors = maunula.areas[maunula.areas["kind"].isin(list(AREA_STYLES))]
    counts = [sum(level in on for on in floors["levels"]) for level in (0.0, 1.0, 2.0)]
    assert counts[0] == 7  # four platforms, the two squares and the lift
    names = ["Level %d, %d areas" % (level, count) for level, count in enumerate(counts)]
    assert shown["names"] == ["All levels"] + names
    assert shown["counts"] == [[]] + [["small %d" % count] for count in counts]
    wall_above = maunula.walls.assign(levels=[(7.0,)])
    rooms = maunula.areas["kind"] == "room"
    between = maunula.areas.assign(
        levels=[
            (0.5,) if row == maunula.areas.index[rooms][0] else levels
            for row, levels in zip(maunula.areas.index, maunula.areas["levels"])
        ]
    )
    path_above = layers_page(
        replace(maunula, walls=wall_above, areas=between),
        tmp_path / "above.html",
        include_plotlyjs=False,
    )
    above = _run_page(path_above, "Rooms", "Rooms")
    assert (above["buttons"][-1], above["names"][-1]) == ("7", "Level 7, 0 areas")
    assert above["counts"][-1] == ["small 0"]
    assert (above["buttons"][2], above["names"][2]) == ("0.5", "Level 0.5, 1 area")
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
    # start anew, and half as far apart around the same point double the distance,
    # also when the browser lists the two in the other order.
    touches = shown["touches"]
    assert touches["kept"] == [False, True, True, True, True, True, False]
    assert touches["distances"] == pytest.approx([4, 2, 2, 2, 4, 4, 4])
    assert touches["pans"] == [[0, pytest.approx(0.2), 0], [0, 0, 0]]
    assert touches["saves"] == [1, 1, 1, 2]


def test_level_counts_leave_out_areas_outside_the_view(maunula, tmp_path):
    """The count on a level's button holds the areas that the figure draws: a walking
    area that lies outside the view of the other areas, or only touches its edge, is
    not counted and has no floor and no outline."""
    areas = maunula.areas
    is_square = areas["id"] == 674689752
    _, south, east, _ = _view_box(maunula)
    beside_the_view = box(east, south, east + 10, south + 10)
    moved = {
        "near": areas.geometry,
        "far": areas.geometry.where(~is_square, areas.translate(5000)),
        "touching": areas.geometry.where(~is_square, beside_the_view),
    }
    counts, drawn = {}, {}
    for name, geometry in moved.items():
        layers = replace(maunula, areas=areas.assign(geometry=geometry))
        path = layers_page(layers, tmp_path / (name + ".html"), include_plotlyjs="cdn")
        page = path.read_text(encoding="utf-8")
        data = json.loads(re.search(r'id="page-data">(.*?)</script>', page, re.S)[1])
        counts[name] = dict(zip(data["levels"], data["counts"]))
        figure = layers_figure(layers)
        drawn[name] = [(trace.name, len(trace.x)) for trace in figure.data]
    assert counts["near"][0.0] == 7  # four platforms, the two squares and the lift
    assert counts["far"] == counts["touching"] == {**counts["near"], 0.0: 6}
    assert drawn["far"] == drawn["touching"] != drawn["near"]


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
