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
from pyrosm3d.tags import element_keys, row_tags


def to_html(indoor, path, title="Indoor elements", include_plotlyjs=True):
    """Write a web page with the 3D view of indoor elements.

    The page shows the figure of :func:`pyrosm3d.plot_indoor`. Its buttons show all
    levels or one level and show or hide the legend, and a click on an area, a line of
    the network or a marker shows the element's OpenStreetMap tags beside the figure.
    On a small screen, such as a phone's, the legend is hidden at start and the tags
    lie over the figure. On a touch screen two fingers zoom and move the view.

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
    data = {
        "levels": [float(level) for level in views],
        "views": list(views.values()),
        "all": {
            "scene.zaxis.range": list(scene.zaxis.range),
            "scene.zaxis.tickvals": list(scene.zaxis.tickvals),
            "scene.zaxis.ticktext": list(scene.zaxis.ticktext),
            "scene.aspectratio": scene.aspectratio.to_plotly_json(),
        },
        "elements": _drawn_elements(indoor, figure),
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
