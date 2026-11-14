import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from pyrosm3d import plot_indoor, to_html
from pyrosm3d.figure import level_views


def _run_page(path, entry, clicked):
    """What the page at ``path`` shows when each of its level buttons is pressed, the
    legend ``entry`` is switched off and the first point of the trace ``clicked`` is
    clicked: the JSON of ``page_harness.js``, which runs the page's scripts in node."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the page script is tested with node, which is not installed")
        pytest.skip("node is not installed")
    harness = Path(__file__).parent / "page_harness.js"
    command = [node, str(harness), str(path), entry, clicked]
    done = subprocess.run(command, capture_output=True, text=True, check=True)
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
    in the tags panel. A legend entry cannot be shown alone with a double click. A
    button for all levels and one for each level show the traces of that level, drawn
    or switched off as in the figure, list each legend entry once and set the vertical
    axis as plot_indoor does for the level. A click on a legend entry switches it off
    on every level, and a click on a room shows its tags with a link to the element;
    a click on a point without an element leaves the panel as it is."""
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
    for used_by_the_script in ('id="levels"', 'id="page-data"', 'id="tags"'):
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
    assert shown["tags"].startswith(hostile)
    assert shown["tagsAfterEmptyClick"] == shown["tags"]
