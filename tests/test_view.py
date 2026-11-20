import html
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pyrosm3d.view import DECK_GL, View

SQUARE = [[[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [0, 0, 0]]]
LINE = dict(minPixels=0.5, maxPixels=4, alpha=200, belowShare=0.5, visible=True)


def _page_data(mode="solid"):
    """The data of a page with a group of every kind of the views of a city, one item
    each, two lines (the second below ground) and a group that is off at the start;
    the points come first."""
    return dict(
        mode=mode,
        view=dict(target=[0, 0, 0], rotationX=40, rotationOrbit=20, zoom=1),
        tables=dict(names=["Main street"], highways=["footway", "steps"]),
        groups=[
            dict(name="Route ends", kind="points", colour="#e8002d", width=7.0,
                 visible=True, items=[dict(c=[0, 0, 0], t="route start")]),
            dict(name="Ground", kind="ground", colour="#dde1e6", visible=True,
                 grid=dict(x=0, y=0, step=10, rows=3, columns=3,
                           z=[0, 0, 0, 0, 1, 0, None, 0, 0])),
            dict(name="Stairs", kind="lines", colour="#444b55", metres=0.9, **LINE,
                 items=[dict(p=[[0, 0, 0], [5, 0, 4]], w=7, h=1, a=0.0, c=1.0),
                        dict(p=[[0, 5, -6], [5, 5, -6]], w=8, h=0, n=0, a=-1.0,
                             e=2, b=1)]),
            dict(name="Route", kind="lines", colour="#e8002d", metres=1.6,
                 rounded=True, always=True, **LINE,
                 items=[dict(p=[[0, 0, 0], [5, 0, 4]], t="route")]),
            dict(name="Entrances", kind="points", colour="#1f2329", width=3.5,
                 visible=False, items=[dict(c=[1, 1, 0], t="entrance 5")]),
        ],
    )


def _group(data, name):
    """The group of ``data`` called ``name``."""
    return next(group for group in data["groups"] if group["name"] == name)


def _layers(note):
    """``{id: layer note}`` of the layers that a page showed."""
    return {layer["id"]: layer for layer in note["layers"]}


def test_to_html_writes_the_data_the_library_and_the_scripts(tmp_path):
    """A page holds its data, the deck.gl library and the scripts of pyrosm3d. A name
    in the data that tries to end the data's script element, start one or stand for a
    part of the page stays text, and the page has three script elements: the data, the
    library and the scripts. The library comes from jsDelivr unless another copy is
    named; written to a file, the page is the same text."""
    data = _page_data()
    data["tables"]["names"] = ['</script><script>alert("x")</script> & @@SCRIPT@@']
    view = View(data, title="Kamppi & <Forum>", about="a <b>test</b>")
    page = view.to_html()
    assert page.count("<script") == 3
    assert "<title>Kamppi &amp; &lt;Forum&gt;</title>" in page
    assert "a &lt;b&gt;test&lt;/b&gt;" in page
    assert '<script src="%s"></script>' % DECK_GL in page
    held = re.search(r'<script id="data" type="application/json">(.*?)</script>', page)
    assert json.loads(held[1]) == data
    assert page.index("function layersOf(") < page.index("function begin(")
    written = view.to_html(tmp_path / "page.html", deck_gl="deck.min.js")
    assert written.read_text(encoding="utf-8") == page.replace(DECK_GL, "deck.min.js")


def test_each_group_needs_a_name_of_its_own():
    """The page lists the groups by name and switches them on and off: a view whose
    groups share a name is refused, also when a name is changed after the view was
    made."""
    data = _page_data()
    _group(data, "Stairs")["name"] = "Ground"
    with pytest.raises(ValueError, match="a name of its own"):
        View(data)
    view = View(_page_data())
    _group(view.data, "Stairs")["name"] = "Ground"
    with pytest.raises(ValueError, match="a name of its own"):
        view.to_html()


def test_a_view_in_a_notebook_is_a_frame_of_its_page():
    """The output of a notebook cell is a frame whose ``srcdoc`` holds the page."""
    view = View(_page_data(), title="t")
    frame = view._repr_html_()
    assert frame.startswith("<iframe srcdoc=")
    held = re.search(r'srcdoc="(.*?)" style', frame, re.S)[1]
    assert html.unescape(held) == view.to_html()


def test_the_page_draws_every_kind_of_group_in_each_view(tmp_path, run_view):
    """The solid model draws the ground (a square for each four corners with heights),
    the lines as wide as a path in metres, the route over everything in front of it,
    and the points in pixels, last; not what is switched off at the start. The
    see-through view draws the map first, a ground that hides nothing, and a line
    below ground paler. Heights can be drawn taller."""
    note = run_view(View(_page_data("solid")), [["layersAt", "solid", None, 2.5]], tmp_path)
    solid = _layers(note[0])
    assert [layer["id"] for layer in note[0]["layers"]] == [
        "ground-Ground", "lines-Stairs", "lines-Route", "points-Route ends",
    ]
    assert solid["ground-Ground"]["items"] == 3
    first = [[0, 0, 0], [10, 0, 0], [10, 10, 1], [0, 10, 0], [0, 0, 0]]
    assert solid["ground-Ground"]["getPolygon"][0] == first
    assert solid["lines-Stairs"]["widthUnits"] == "meters"
    assert solid["lines-Stairs"]["getColor"] == [68, 75, 85, 200]
    assert solid["lines-Route"]["parameters"] == {"depthTest": False}
    assert solid["points-Route ends"]["radiusUnits"] == "pixels"
    assert "modelMatrix" not in solid["lines-Stairs"]
    taller = note[1]["at"]
    assert len(taller) == 5 and all(layer["modelMatrix"][10] == 2.5 for layer in taller)

    through = run_view(View(_page_data("through")), tmp_path=tmp_path)[0]["layers"]
    assert [layer["id"] for layer in through] == [
        "ground-Ground", "lines-Stairs", "lines-Route", "points-Route ends",
    ]
    assert through[0]["parameters"] == {"depthMask": False}
    assert through[1]["getColor"] == [[68, 75, 85, 200], [68, 75, 85, 100]]


def test_a_tap_shows_what_an_item_is(tmp_path, run_view):
    """A tap on a line of the network shows its name, its element with its highway
    value and its levels; one on another item shows its text; a tap where there is
    nothing hides the panel. The tooltip has the same text."""
    steps = [
        ["click", "lines-Stairs", 1],
        ["click", "lines-Stairs", 0],
        ["click", "lines-Route", 0],
        ["miss"],
        ["tooltip", "lines-Stairs", 0],
    ]
    notes = run_view(View(_page_data()), steps, tmp_path=tmp_path)
    assert notes[0]["info"] is None and notes[0]["error"] is None
    assert notes[1]["info"] == "Main street\nnode 8 · footway\nlevel -1"
    assert notes[2]["info"] == "way 7 · steps\nlevels 0 → 1"
    assert notes[3]["info"] == "route"
    assert notes[4]["info"] is None
    assert notes[5]["tooltip"] == {"text": "way 7 · steps\nlevels 0 → 1"}
    assert notes[0]["deck"]["views"] == {"id": "main", "orbitAxis": "Z"}


def test_the_page_says_when_the_library_did_not_load(tmp_path, run_view):
    """Without deck.gl the page shows an error and draws nothing."""
    note = run_view(View(_page_data()), tmp_path=tmp_path, deck=False)[0]
    assert note["error"] == "This page hit an error: the deck.gl library did not load."
    assert note["layers"] == []


def _indoor_data(mode="indoor"):
    """The data of a page with indoor elements: the ground, floors on levels 0 and 1,
    the outlines of a level (for the indoor view alone) and of a building, walls, two
    kinds of line with their indoor look (the second line of stairs below ground, on
    level -1 and left out of the indoor view; the lift dashed, on levels 0 and 1),
    doors that are off at the start, and route ends without a level."""
    line = dict(LINE, metres=0.9)
    return dict(
        mode=mode,
        view=dict(target=[0, 0, 0], rotationX=40, rotationOrbit=20, zoom=1),
        indoor=dict(box=[-5, -5, 15, 15], levels=[[0, 0.0], [1, 4.0]], ground=0.0,
                    background="#ffffff", stretch=2.5),
        tables=dict(names=["Main street"], highways=["footway", "steps"]),
        groups=[
            dict(name="Ground", kind="ground", colour="#dde1e6", visible=True,
                 grid=dict(x=0, y=0, step=10, rows=2, columns=2, z=[0, 0, 0, 0])),
            dict(name="Floors", kind="floors", colour="#f2ede4", edge="#8a8f98",
                 alpha=235, throughAlpha=170, edgeAlpha=170, edgeWidth=0.7,
                 plotEdge=1.5, visible=True, colours={"room": "#f2ede4"},
                 items=[dict(r=SQUARE, k="room", t="room A", l=0.0),
                        dict(r=SQUARE, k="room", t="room B", l=1.0)]),
            dict(name="Level outlines", kind="outlines", only="indoor",
                 colour="#b9a99c", width=2.5, visible=True,
                 items=[dict(p=SQUARE[0], l=0.0)]),
            dict(name="Building outlines", kind="outlines", colour="#b9a99c",
                 width=2.0, visible=True, items=[dict(p=SQUARE[0], l=0.0)]),
            dict(name="Walls", kind="glass", colour="#9aa3ad", alpha=60,
                 visible=True, items=[dict(r=SQUARE, h=1.6, l=0.0)]),
            dict(name="Stairs", kind="lines", colour="#444b55",
                 plot=["#444b55", 5.0, None], **line,
                 items=[dict(p=[[0, 0, 0], [5, 0, 4]], w=7, h=1, a=0.0, c=1.0),
                        dict(p=[[0, 5, -6], [5, 5, -6]], w=8, h=0, a=-1.0, b=1,
                             o=1)]),
            dict(name="Lifts", kind="lines", colour="#8e44ad",
                 plot=["#8e44ad", 5.0, "dash"], **line,
                 items=[dict(p=[[2, 2, 0], [2, 2, 4]], w=9, h=0, a=0.0, c=1.0,
                             ls=[0.0, 1.0])]),
            dict(name="Doors", kind="points", colour="#31363b", width=3.0,
                 visible=False, items=[dict(c=[1, 1, 0.8], t="door", l=0.0)]),
            dict(name="Route ends", kind="points", colour="#e8002d", width=7.0,
                 visible=True, items=[dict(c=[0, 0, 0], t="route start")]),
        ],
    )


def test_the_indoor_view_draws_the_indoor_mapping_alone(tmp_path, run_view):
    """The indoor view draws no ground and nothing it leaves out (o); the floors are
    opaque with their outlines in the pixels of its look, the lines in the colours,
    pixel widths and dashes of its look, every kind of line on at the start, and the
    heights taller by its stretch, on its own background. In the see-through view the
    floors and their outlines hide nothing and the outlines of the indoor view alone
    are left out."""
    note = run_view(View(_indoor_data()), tmp_path=tmp_path)[0]
    indoor = _layers(note)
    assert [layer["id"] for layer in note["layers"]] == [
        "floors-Floors", "outlines-Floors", "frames-Level outlines",
        "frames-Building outlines", "glass-Walls", "lines-Stairs", "lines-Lifts",
        "points-Route ends",
    ]
    assert indoor["floors-Floors"]["getFillColor"] == [[242, 237, 228, 255]] * 2
    assert indoor["outlines-Floors"]["getWidth"] == 1.5
    assert indoor["lines-Stairs"]["items"] == 1
    assert indoor["lines-Stairs"]["widthUnits"] == "pixels"
    assert indoor["lines-Stairs"]["getWidth"] == 5.0
    assert indoor["lines-Stairs"]["getColor"] == [68, 75, 85, 255]
    assert indoor["lines-Lifts"]["extensions"] == ["PathStyleExtension"]
    assert indoor["lines-Lifts"]["getDashArray"] == [3, 2]
    assert all(layer["modelMatrix"][10] == 2.5 for layer in indoor.values())
    assert note["background"] == "#ffffff"

    through = run_view(View(_indoor_data("through")), tmp_path=tmp_path)[0]
    layers = _layers(through)
    assert "frames-Level outlines" not in layers
    assert layers["floors-Floors"]["getFillColor"][0][3] == 170
    assert layers["floors-Floors"]["parameters"] == {"depthMask": False}
    assert layers["outlines-Floors"]["parameters"] == {"depthMask": False}
    assert layers["glass-Walls"]["parameters"] == {"depthMask": False}
    assert "modelMatrix" not in layers["lines-Stairs"]


def test_the_indoor_view_draws_the_items_of_a_picked_level(tmp_path, run_view):
    """With a level picked, the indoor view draws the floors, outlines, walls and
    points on that level, a line on the levels listed for it (ls) or else on its first
    level (a), and no point without a level."""
    notes = run_view(
        View(_indoor_data()),
        [["layersAt", "indoor", 0.0, 1], ["layersAt", "indoor", 1.0, 1]],
        tmp_path=tmp_path,
    )
    counts = [{layer["id"]: layer["items"] for layer in note["at"]} for note in notes[1:]]
    assert counts[0] == {
        "floors-Floors": 1, "outlines-Floors": 1, "frames-Level outlines": 1,
        "frames-Building outlines": 1, "glass-Walls": 1, "lines-Stairs": 1,
        "lines-Lifts": 1, "points-Doors": 1, "points-Route ends": 0,
    }
    assert counts[1] == {
        "floors-Floors": 1, "outlines-Floors": 1, "frames-Level outlines": 0,
        "frames-Building outlines": 0, "glass-Walls": 0, "lines-Stairs": 0,
        "lines-Lifts": 1, "points-Doors": 0, "points-Route ends": 0,
    }
    assert notes[2]["at"][0]["getPolygon"][0] == SQUARE


def test_a_page_opens_in_a_city_view_without_indoor_data(tmp_path, run_view):
    """A page that asks for the indoor view but has no indoor data opens in the solid
    view."""
    data = _indoor_data()
    del data["indoor"]
    note = run_view(View(data), tmp_path=tmp_path)[0]
    assert "ground-Ground" in _layers(note)


def test_the_view_buttons_switch_between_the_views(tmp_path, run_view):
    """The buttons show the view that is on; the indoor one only with indoor data. A
    switch keeps the camera where it is. The indoor view shows the level picker, its
    own background and its own layers in the list (each of them on at the start when
    it has an indoor look); "Start view" there goes over the middle of its box at the
    height of the ground, seen from the south-east, from so far that the box fits the
    screen. Switching back draws the city view again."""
    steps = [
        ["press", "viewIndoor"], ["press", "home"], ["press", "viewThrough"],
        ["press", "viewSolid"],
    ]
    notes = run_view(View(_indoor_data("solid")), steps, tmp_path)
    controls = [note["controls"] for note in notes]
    assert [c["viewSolid"]["on"] for c in controls] == [True, False, False, False, True]
    assert [c["viewIndoor"]["pressed"] for c in controls] == [
        "false", "true", "true", "false", "false",
    ]
    assert not controls[0]["viewIndoor"]["hidden"]
    assert [c["levels"]["hidden"] for c in controls] == [True, False, False, True, True]
    assert [note["background"] for note in notes] == ["", "#ffffff", "#ffffff", "", ""]
    assert controls[0]["levelChoices"] == [
        ["", "All levels"], ["0", "Level 0"], ["1", "Level 1"],
    ]
    entries = {entry["name"]: entry for entry in controls[1]["layerList"]}
    assert entries["Ground (1)"]["hidden"] and entries["Stairs (2)"]["checked"]
    assert not {e["name"]: e for e in controls[0]["layerList"]}["Ground (1)"]["hidden"]
    assert "ground-Ground" not in _layers(notes[1])
    assert "ground-Ground" in _layers(notes[4])
    assert notes[1]["viewState"]["target"] == notes[0]["viewState"]["target"]
    start = notes[2]["viewState"]
    assert start["target"] == [5, 5, 0.0]
    assert (start["rotationX"], start["rotationOrbit"]) == (27, -43)
    assert start["zoom"] == pytest.approx(math.log2(min(800 / (1.45 * 20), 800 / 18)))
    without = _indoor_data("solid")
    del without["indoor"]
    assert run_view(View(without), tmp_path=tmp_path)[0]["controls"]["viewIndoor"][
        "hidden"
    ]


def test_true_heights_draw_each_view_to_scale_or_taller(tmp_path, run_view):
    """The views of the city start to scale and the indoor view taller, each with its
    own choice: off in the city, the heights are drawn taller by the data's stretch
    and the point the view turns around rises with them; the indoor view keeps its
    own choice. Without a stretch the switch is hidden."""
    data = _indoor_data("solid")
    data["stretch"] = 2.0
    data["view"]["target"] = [0, 0, 3.0]
    steps = [
        ["set", "trueHeights", False],
        ["press", "viewIndoor"],
        ["set", "trueHeights", True],
        ["press", "viewSolid"],
    ]
    notes = run_view(View(data), steps, tmp_path)
    assert [n["controls"]["trueHeights"]["checked"] for n in notes] == [
        True, False, False, True, False,
    ]
    assert "modelMatrix" not in _layers(notes[0])["lines-Stairs"]
    assert _layers(notes[1])["lines-Stairs"]["modelMatrix"][10] == 2.0
    assert notes[1]["viewState"]["target"] == [0, 0, 6.0]
    assert _layers(notes[2])["lines-Stairs"]["modelMatrix"][10] == 2.5
    assert "modelMatrix" not in _layers(notes[3])["lines-Stairs"]
    assert _layers(notes[4])["lines-Stairs"]["modelMatrix"][10] == 2.0
    assert notes[0]["controls"]["heights"]["hidden"] is False
    data = _page_data()
    assert run_view(View(data), tmp_path=tmp_path)[0]["controls"]["heights"]["hidden"]


def test_a_picked_level_draws_that_level_at_its_height(tmp_path, run_view):
    """Picking a level draws only what is on it and moves the view to the level's
    height, drawn taller as the view draws heights; "All levels" draws all again."""
    steps = [["set", "level", "1"], ["set", "level", ""]]
    notes = run_view(View(_indoor_data()), steps, tmp_path)
    assert notes[1]["controls"]["level"]["value"] == "1"
    assert _layers(notes[1])["glass-Walls"]["items"] == 0
    assert _layers(notes[1])["lines-Lifts"]["items"] == 1
    assert notes[1]["viewState"]["target"][2] == 4.0 * 2.5
    assert _layers(notes[2])["glass-Walls"]["items"] == 1


def test_the_sliders_buttons_and_layer_list_move_and_switch(tmp_path, run_view):
    """The sliders tilt and turn the view and follow it, also when the camera moves;
    the buttons look from above, from the side and north up, and go back to the start;
    a box in the list of layers switches its layer off and on. A start view with
    ``fit`` holds that much ground across and, foreshortened by the tilt, up the
    screen, also when it is turned."""
    data = _page_data()
    data["fit"] = [400, 300]
    steps = [
        ["set", "tilt", "60"],
        ["set", "turn", "-90"],
        ["press", "north"],
        ["press", "above"],
        ["press", "side"],
        ["press", "home"],
        ["toggle", "Stairs"],
        ["toggle", "Stairs"],
        ["camera", {"rotationX": 35, "rotationOrbit": 200}],
    ]
    notes = run_view(View(data), steps, tmp_path)
    views = [note["viewState"] for note in notes]
    lean = math.sin(math.radians(40))
    turn = math.radians(20)
    across = 400 * math.cos(turn) + 300 * math.sin(turn)
    up = (400 * math.sin(turn) + 300 * math.cos(turn)) * lean
    assert views[0]["zoom"] == pytest.approx(math.log2(min(800 / across, 800 / up)))
    assert views[1]["rotationX"] == 60 and views[2]["rotationOrbit"] == -90
    assert views[3]["rotationOrbit"] == 0 and views[3]["rotationX"] == 60
    assert (views[4]["rotationX"], views[4]["rotationOrbit"]) == (90, 0)
    assert views[5]["rotationX"] == 0
    assert views[6]["rotationX"] == 40 and views[6]["zoom"] == views[0]["zoom"]
    assert notes[1]["controls"]["tilt"]["value"] == "60"
    assert notes[2]["controls"]["turn"]["value"] == "-90"
    assert notes[3]["controls"]["turn"]["value"] == "0"
    assert "lines-Stairs" not in _layers(notes[7])
    assert "lines-Stairs" in _layers(notes[8])
    assert notes[9]["controls"]["tilt"]["value"] == "35"
    assert notes[9]["controls"]["turn"]["value"] == "-160"


def _walk_data():
    """The data of a page to walk on: a street at 10 m along y = 0, stairs from it at
    x = 50 down to 5 m at y = 20, a tunnel on from there, a bridge at 16 m across the
    tunnel at y = 30, a lift at x = 60 from 10 m to 30 m, a route, and terrain at 10 m
    with the drawn ground at 9.5 m."""

    def lines(name, *paths, **more):
        return dict(name=name, kind="lines", colour="#3987e5", metres=0.9,
                    items=[dict(p=path) for path in paths], **LINE, **more)

    return dict(
        mode="solid",
        view=dict(target=[30, 0, 10], rotationX=40, rotationOrbit=20, zoom=1,
                  minZoom=-3, maxZoom=4.3, minRotationX=-90, maxRotationX=90),
        tables=dict(names=[], highways=[]),
        groups=[
            dict(name="Ground", kind="ground", colour="#dde1e6", visible=True,
                 grid=dict(x=-200, y=-200, step=100, rows=5, columns=5,
                           z=[9.5] * 25, t=[10] * 25)),
            lines("Street", [[0, 0, 10], [100, 0, 10]]),
            lines("Stairs", [[50, 0, 10], [50, 20, 5]]),
            lines("Tunnel", [[50, 20, 5], [50, 100, 5]]),
            lines("Bridge", [[0, 30, 16], [100, 30, 16]]),
            lines("Lifts", [[60, 0, 10], [60, 0, 30]]),
            lines("Route", [[0, 50, 10], [100, 50, 10]], always=True),
            dict(name="Ends", kind="points", colour="#e8002d", width=7.0,
                 visible=True, items=[dict(c=[0, 0, 10])]),
        ],
    )


def test_a_walk_gives_the_tilt_slider_its_range_back(tmp_path, run_view):
    """Walking, the tilt slider spans the look up and down; afterwards the flying range,
    from below to above when the view gives no limits."""
    steps = [["set", "walk", True], ["set", "walk", False]]
    notes = run_view(View(_page_data()), steps, tmp_path)
    tilts = [note["controls"]["tilt"] for note in notes[1:]]
    assert [(tilt["min"], tilt["max"]) for tilt in tilts] == [("-60", "60"), ("-90", "90")]


@pytest.mark.parametrize("check", ["camera", "walk"])
def test_the_page_moves_with_the_real_library(check, tmp_path, deck_bundle):
    """With the deck.gl library itself, ``camera_check.js``: a drag keeps the grabbed
    point of the ground under the finger from above and from below, and moves the view
    in the plane of the screen from the side; zooming keeps the point the camera turns
    around, within the limits; a pinch ends without a glide, also when its last two
    events come at the same time; a twist of two fingers turns and three fingers tilt;
    with a mouse, a drag moves and a drag with Shift or the right button turns and
    tilts; the browser's menu stays off the view. ``walk_check.js``: "Walk" puts the
    camera on the ground or a walkway at the middle of the view, with a wide field of
    view, the moves and lift rows, and heights to scale; a drag looks around, a pinch,
    the wheel, the arrow keys and the Forward and Back steps walk; stairs take the
    walker down into a tunnel and back up; leaving the walk gives the flying view back
    over the walker, and "Start view" ends it."""
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("the page is checked with node, which is not installed")
        pytest.skip("node is not installed")
    data = _walk_data() if check == "walk" else _page_data()
    page = View(data).to_html(tmp_path / "view.html")
    script = Path(__file__).parent / (check + "_check.js")
    done = subprocess.run(
        [node, str(script), str(page), str(deck_bundle)],
        capture_output=True,
        encoding="utf-8",
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip() == check + ": all checks passed"
