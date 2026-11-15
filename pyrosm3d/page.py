"""A web page of the indoor elements of a place: the figure of plot_indoor with a
button for each level, a button for the legend and a panel for the OpenStreetMap tags
of a clicked element."""

import html
import json
from importlib import resources
from pathlib import Path
from string import Template

import plotly.io

from pyrosm3d.figure import level_views, plot_indoor
from pyrosm3d.network import EDGE_NAMES, _edge_kinds, end_levels_text
from pyrosm3d.styles import AREA_STYLES, DOOR_STYLE, POI_STYLE
from pyrosm3d.tags import element_keys, row_tags


def to_html(indoor, path, title="Indoor elements", include_plotlyjs=True):
    """Write a web page with the 3D view of indoor elements.

    The page shows the figure of :func:`pyrosm3d.plot_indoor`. Its buttons show all
    levels or one level (each level's button has the number of areas on it) and show
    or hide the legend, and a click on an area, a line of the network, a marker or a
    stairwell or lift column shows what the element is and its OpenStreetMap tags
    beside the figure. On a small screen, such as a phone's, the level buttons are
    one row that scrolls sideways, the legend is hidden at start and the tags lie
    over the figure. On a touch screen two fingers zoom and move the view.

    Parameters
    ----------
    indoor : IndoorElements
        The elements that :func:`pyrosm3d.read_indoor` returns.
    path : str or pathlib.Path
        The HTML file to write.
    title : str
        The title of the page.
    include_plotlyjs : bool or "cdn"
        With True (the default) the page holds plotly's JavaScript, so it works without
        a network connection and is about 5 MB larger. With ``"cdn"`` the page loads
        the library from plotly's content delivery network.

    Returns
    -------
    pathlib.Path
        The file written.
    """
    figure = plot_indoor(indoor)
    # The page keeps track of the legend entries that are switched off; a double click
    # would show one entry alone behind its back
    figure.update_layout(legend_itemdoubleclick=False)
    views = level_views(figure)
    scene = figure.layout.scene
    elements = _drawn_elements(indoor, figure)
    notes = _element_notes(indoor)
    floors = indoor.areas[indoor.areas["kind"].isin(list(AREA_STYLES))]
    data = {
        "levels": [float(level) for level in views],
        "counts": [sum(level in on for on in floors["levels"]) for level in views],
        "views": list(views.values()),
        "all": {
            "scene.zaxis.range": list(scene.zaxis.range),
            "scene.zaxis.tickvals": list(scene.zaxis.tickvals),
            "scene.zaxis.ticktext": list(scene.zaxis.ticktext),
            "scene.aspectratio": scene.aspectratio.to_plotly_json(),
        },
        "elements": elements,
        "about": {key: notes[key] for key in elements},
    }
    files = resources.files("pyrosm3d")
    plot = plotly.io.to_html(
        figure,
        full_html=False,
        include_plotlyjs=include_plotlyjs,
        div_id="plot",
        post_script=files.joinpath("page.js").read_text(encoding="utf-8"),
        config=dict(displaylogo=False, responsive=True),
    )
    page = Template(files.joinpath("page.html").read_text(encoding="utf-8"))
    # No "<" in the JSON, so that no tag value can end the script block that holds it
    data = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    path = Path(path)
    path.write_text(
        page.substitute(title=html.escape(title), plot=plot, data=data),
        encoding="utf-8",
    )
    return path


def _drawn_elements(indoor, figure):
    """``{key: tags}`` of the elements of ``indoor`` that ``figure`` draws, by the keys
    its traces carry (see :func:`pyrosm3d.tags.element_keys`)."""
    drawn = set()
    for trace in figure.data:
        drawn.update(key for key in trace.customdata or () if key)
    elements = dict(zip(element_keys(indoor.edges), row_tags(indoor.edges)))
    for layer in (indoor.areas, indoor.doors, indoor.pois):
        elements.update(zip(element_keys(layer), layer["tags"]))
    return {key: tags for key, tags in elements.items() if key in drawn}


def _element_notes(indoor):
    """``{key: note}`` of the elements of ``indoor``: what an element is and the
    levels it is on, such as ``"room · levels 1, 2"`` or ``"stairs · levels 0 → 1"``
    (the lowest and the highest level of the element's edges). An area's note stands
    also for the edges that carry its key."""
    notes, ends = {}, {}
    kinds = zip(element_keys(indoor.edges), _edge_kinds(indoor.edges))
    for key, (_, _, kind, level_u, level_v) in kinds:
        low, high = sorted((level_u, level_v))
        _, lowest, highest = ends.get(key, (kind, low, high))
        ends[key] = (kind, min(low, lowest), max(high, highest))
    for key, (kind, low, high) in ends.items():
        notes[key] = "%s · %s" % (EDGE_NAMES[kind], end_levels_text(low, high))
    areas = indoor.areas
    columns = (areas["kind"], areas["levels"])
    for key, kind, levels in zip(element_keys(areas), *columns):
        name = AREA_STYLES[kind][2] if kind in AREA_STYLES else kind
        notes[key] = "%s · %s" % (name, _levels_text(levels))
    for layer, style in ((indoor.doors, DOOR_STYLE), (indoor.pois, POI_STYLE)):
        for key, levels in zip(element_keys(layer), layer["levels"]):
            notes[key] = "%s · %s" % (style[3], _levels_text(levels))
    return notes


def _levels_text(levels):
    """``"level 1"``, ``"levels 1, 2"`` or ``"no level"`` for the ``levels`` of an
    element."""
    if not levels:
        return "no level"
    listed = ", ".join("%g" % level for level in levels)
    return ("level %s" if len(levels) == 1 else "levels %s") % listed
