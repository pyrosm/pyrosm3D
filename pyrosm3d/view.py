"""The 3D views of pyrosm3d: web pages that draw their data with deck.gl.

The data of a view is a dict that the page script reads:

``groups``
    What is drawn, each group a list of ``items`` with a ``name`` (its entry in the
    page's list of layers, one name for each group), a ``kind``, a ``colour``
    (``"#rrggbb"``), whether it is ``visible`` at the start, and the style of its kind.
    The kinds: ``ground`` (a ``grid`` of heights, or ``items`` with rings ``r``),
    ``buildings`` (blocks: rings ``r`` at the bottom, a height ``h``, the height of
    the ground ``g`` for the footprint, ``part`` for the part of a building),
    ``floors`` (rings ``r`` of a kind ``k`` among the group's ``colours``),
    ``outlines`` and ``lines`` (paths ``p``), ``glass`` (see-through blocks: rings
    ``r`` and a height ``h``) and ``points`` (a place ``c``). Points are ``[x, y, z]``
    in metres from the middle of the data, x east, y north, z up. An item may have a
    text ``t``, its level ``l`` (a line: its levels ``ls``, else its first level
    ``a``), and ``o`` when the indoor view leaves it out. A group with a style for the
    indoor view (``plot``: colour, width in pixels and dash) is on there at the start.
``tables``
    The texts that the items of the network refer to by number: ``names`` and
    ``highways``; and the ``elements`` that items refer to by number (``q``), each
    ``[key, note, tags]``: a key such as ``"way 123"``, what the element is and its
    OpenStreetMap tags without contact details, which a tap on an item shows with a
    link to the element.
``view``
    Where the camera starts: deck.gl's view state of an orbit view (``target``,
    ``rotationX``, ``rotationOrbit``, ``zoom``) and its limits (``minZoom``,
    ``maxZoom``, ``minRotationX``, ``maxRotationX``).
``fit`` (optional)
    The metres of ground from west to east and from south to north that the start
    view holds; the page then picks the zoom from the size of the screen.
``stretch`` (optional)
    How much taller than to scale the views of the city draw the heights when "True
    heights" is off; without it they are always to scale.
``mode``
    The view that the page opens in: ``"solid"`` (the ground hides what is below it),
    ``"through"`` (a map, the network over and under it) or ``"indoor"`` (without the
    ground; the floors are plates, and the heights are drawn taller).
``indoor``
    On a page with indoor elements: the ``box`` of the indoor view, its ``levels``
    (each a level, its height and the number of areas on it), the height of the
    ``ground``, its ``background``
    colour, how much taller than to scale it draws the heights (``stretch``) and,
    optionally, the ``level`` that it opens on.
"""

import html
import json
import re
import tempfile
import webbrowser
from importlib import resources
from pathlib import Path

import numpy as np
import shapely

# The deck.gl library that the pages load
DECK_GL = "https://cdn.jsdelivr.net/npm/deck.gl@8.9.35/dist.min.js"
# The scripts of a page, in the order they run
_SCRIPTS = ("view_layers.js", "view_walk.js", "view_camera.js", "view_page.js")
# Pixels that the frame of a view is high in a notebook
_FRAME_HEIGHT = 620
# The frame runs the page's scripts and opens its links in a window of their own, but
# shares nothing with the notebook
_FRAME_SANDBOX = "allow-scripts allow-popups allow-popups-to-escape-sandbox"
# The characters at which a notebook splits a line of an output, but U+0085, which a
# character reference cannot write (HTML reads &#133; as an ellipsis): the page's data
# writes it as a JSON escape, and its title and about text as a line break
_LINE_BREAKS = re.compile("[\n\r\x0b\x0c\x1c\x1d\x1e\u2028\u2029]")


def package_text(name):
    """The text of a file that the package holds, such as ``"view.html"``."""
    return resources.files("pyrosm3d").joinpath(name).read_text(encoding="utf-8")


def _script_json(data):
    """``data`` as JSON that can stand in a script element of a page: the characters
    that could end the element or start markup, and those that break a line, are
    written as escapes."""
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    for character in "<>&\x85\u2028\u2029":
        text = text.replace(character, "\\u%04x" % ord(character))
    return text


def polygon_parts(shape):
    """The polygons of ``shape``, a geometry or a list of them, also inside
    collections, as a MultiPolygon: empty where there are none (no shape, a point, a
    line, or a polygon that has collapsed)."""
    parts = shapely.get_parts(shape)
    while np.isin(shapely.get_type_id(parts), [4, 5, 6, 7]).any():  # multi, collection
        parts = shapely.get_parts(parts)
    return shapely.MultiPolygon(
        [part for part in parts if part.geom_type == "Polygon" and part.area > 0]
    )


def polygon_rings(shape, z, origin, decimals=2):
    """The rings of each polygon of ``shape`` (in metres) as items of a view take
    them: for each polygon a list of rings, each a list of ``[x, y, z]`` points in
    metres from ``origin``, rounded to ``decimals``. ``z`` is a height, or a function
    ``(x, y) -> heights`` at points in the metres of ``shape``."""
    found = []
    for polygon in shapely.get_parts(shape):
        rings = []
        for ring in (polygon.exterior, *polygon.interiors):
            xy = shapely.get_coordinates(ring)
            heights = z(xy[:, 0], xy[:, 1]) if callable(z) else np.full(len(xy), z)
            points = np.column_stack([xy - origin, heights])
            rings.append(points.round(decimals).tolist())
        found.append(rings)
    return found


def _check_names(data):
    """Raise a ValueError when groups of ``data`` share a name: the page lists and
    switches the groups by name."""
    names = [group["name"] for group in data["groups"]]
    if len(set(names)) < len(names):
        raise ValueError("A view needs a name of its own for each group: %s." % names)


class View:
    """A 3D view: a web page that draws its data with deck.gl.

    In a notebook the view is the output of a cell, in a frame of its own;
    :meth:`to_html` writes it as a page of its own, and :meth:`show` shows it.

    Parameters
    ----------
    data : dict
        What the page draws (see :mod:`pyrosm3d.view`).
    title : str
        The title of the page.
    about : str
        A sentence on what the view shows, in the page's notes.
    """

    def __init__(self, data, title="3D view", about=""):
        _check_names(data)
        self.data = data
        self.title = title
        self.about = about

    def to_html(self, path=None, deck_gl=DECK_GL):
        """The view as a web page.

        Parameters
        ----------
        path : str or pathlib.Path (optional)
            The file to write the page to.
        deck_gl : str
            Where the page loads the deck.gl library from: by default version 8.9.35
            from the jsDelivr network, so the page needs a network connection; the
            address of another copy, such as a file beside the page, works without one.

        Returns
        -------
        str or pathlib.Path
            The page, or the file written when ``path`` is given.
        """
        _check_names(self.data)
        values = {
            "TITLE": html.escape(self.title.replace("\x85", "\n")),
            "ABOUT": html.escape(self.about.replace("\x85", "\n")),
            "DECK_GL": html.escape(deck_gl),
            "DATA": _script_json(self.data),
            "SCRIPT": "\n".join(package_text(name) for name in _SCRIPTS),
        }
        page = re.sub(
            r"@@(TITLE|ABOUT|DECK_GL|DATA|SCRIPT)@@",
            lambda found: values[found[1]],
            package_text("view.html"),
        )
        if path is None:
            return page
        path = Path(path)
        path.write_text(page, encoding="utf-8")
        return path

    def _repr_html_(self):
        """The view as the output of a notebook cell: a sandboxed frame that holds the
        page (see ``_FRAME_SANDBOX``) and sends no referrer, on one line: the
        characters that break a line are written as character references."""
        page = _LINE_BREAKS.sub(
            lambda found: "&#%d;" % ord(found[0]),
            html.escape(self.to_html(), quote=True),
        )
        return (
            '<iframe srcdoc="%s" sandbox="%s" referrerpolicy="no-referrer" '
            'style="width: 100%%; height: %dpx; border: none" allow="fullscreen">'
            "</iframe>" % (page, _FRAME_SANDBOX, _FRAME_HEIGHT)
        )

    def show(self):
        """Show the view: as the output of the cell in a notebook, else as a page in
        the web browser, written to a temporary file.

        Returns
        -------
        pathlib.Path or None
            The file written, outside a notebook.
        """
        try:
            from IPython import get_ipython
            from IPython.display import display
        except ImportError:
            shell = None
        else:
            shell = get_ipython()
        if getattr(shell, "kernel", None) is not None:
            display(self)
            return None
        handle, name = tempfile.mkstemp(prefix="pyrosm3d-", suffix=".html")
        with open(handle, "w", encoding="utf-8") as page:
            page.write(self.to_html())
        path = Path(name)
        webbrowser.open(path.as_uri())
        return path
