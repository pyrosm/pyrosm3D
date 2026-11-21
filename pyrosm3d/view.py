"""The 3D views of pyrosm3d: web pages that draw their data with deck.gl.

The data of a view is a dict that the page script reads:

``groups``
    What is drawn, each group a list of ``items`` with a ``name`` (its entry in the
    page's list of layers, one name for each group), a ``kind``, a ``colour``
    (``"#rrggbb"``), whether it is ``visible`` at the start, and the style of its kind.
    The kinds: ``ground`` (a ``grid`` of heights, or ``items`` with rings ``r``),
    ``floors`` (rings ``r`` of a kind ``k`` among the group's ``colours``),
    ``outlines`` and ``lines`` (paths ``p``), ``glass`` (see-through blocks: rings
    ``r`` and a height ``h``) and ``points`` (a place ``c``). Points are ``[x, y, z]``
    in metres from the middle of the data, x east, y north, z up. An item may have a
    text ``t``, its level ``l`` (a line: its levels ``ls``, else its first level
    ``a``), and ``o`` when the indoor view leaves it out. A group with a style for the
    indoor view (``plot``: colour, width in pixels and dash) is on there at the start.
``tables``
    The texts that the items of the network refer to by number: ``names`` and
    ``highways``.
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
    (each a level and its height), the height of the ``ground``, its ``background``
    colour and how much taller than to scale it draws the heights (``stretch``).
"""

import html
import json
import re
import tempfile
import webbrowser
from importlib import resources
from pathlib import Path

# The deck.gl library that the pages load
DECK_GL = "https://cdn.jsdelivr.net/npm/deck.gl@8.9.35/dist.min.js"
# The scripts of a page, in the order they run
_SCRIPTS = ("view_layers.js", "view_walk.js", "view_camera.js", "view_page.js")
# Pixels that the frame of a view is high in a notebook
_FRAME_HEIGHT = 620


def package_text(name):
    """The text of a file that the package holds, such as ``"view.html"``."""
    return resources.files("pyrosm3d").joinpath(name).read_text(encoding="utf-8")


def _script_json(data):
    """``data`` as JSON that can stand in a script element of a page: the characters
    that could end the element or start markup are written as escapes."""
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


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
            "TITLE": html.escape(self.title),
            "ABOUT": html.escape(self.about),
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
        """The view as the output of a notebook cell: a frame that holds the page."""
        return (
            '<iframe srcdoc="%s" style="width: 100%%; height: %dpx; border: none" '
            'allow="fullscreen"></iframe>'
            % (html.escape(self.to_html(), quote=True), _FRAME_HEIGHT)
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
