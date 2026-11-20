"""The plotly figure that the views of pyrosm3d return: shown as HTML, it has the
controls for touch screens."""

import inspect

import plotly.graph_objects as go
import plotly.io

from pyrosm3d.view import package_text


class TouchFigure(go.Figure):
    """A plotly Figure of a 3D view of pyrosm3d.

    Shown or written as HTML (``show`` with an HTML renderer, the output of a notebook
    cell, ``to_html``, ``write_html``), the figure has controls for touch screens: two
    fingers zoom and move the view, touches on the view do not scroll or zoom the page,
    and the view stays as it was turned when a tool of plotly's toolbar is picked. On a
    small screen, such as a phone's, the legend is hidden at start, and a button in the
    figure shows it over the view; a figure that has ``updatemenus`` keeps its legend
    as it is. The scripts run after those given as ``post_script``."""

    def to_html(self, *args, **kwargs):
        """The figure as HTML, as plotly's ``to_html`` gives it, with the scripts of
        the touch controls."""
        return _html_with_touch(plotly.io.to_html, self, args, kwargs)

    def write_html(self, *args, **kwargs):
        """Write the figure as HTML, as plotly's ``write_html`` does, with the scripts
        of the touch controls."""
        return _html_with_touch(plotly.io.write_html, self, args, kwargs)

    def show(self, *args, **kwargs):
        """Show the figure, as plotly's ``show`` does; a renderer that writes HTML
        gets the scripts of the touch controls."""
        scripts = _post_scripts(kwargs.get("post_script"))
        return plotly.io.show(self, *args, **{**kwargs, "post_script": scripts})

    def _repr_mimebundle_(self, include=None, exclude=None, validate=True, **kwargs):
        """The figure in the formats of plotly's default renderer, its HTML with the
        scripts of the touch controls."""
        options = {**kwargs, "post_script": _post_scripts(kwargs.get("post_script"))}
        return super()._repr_mimebundle_(include, exclude, validate, **options)

    def _ipython_display_(self):
        """Show the figure as the output of a notebook cell, with :meth:`show`; print
        it where plotly shows no figures on display."""
        renderers = plotly.io.renderers
        if renderers.render_on_display and renderers.default:
            self.show()
        else:
            print(repr(self))


def _post_scripts(given):
    """The scripts that run after a figure is drawn as HTML: those ``given`` (a string,
    a list of strings or None), then the touch controls and the legend of a small
    screen."""
    given = [given] if isinstance(given, str) else list(given or [])
    return [*given, package_text("touch.js"), package_text("figure.js")]


def _html_with_touch(write, figure, args, kwargs):
    """Call plotly's ``write`` (``to_html`` or ``write_html``) for ``figure`` with the
    caller's arguments and the scripts of :func:`_post_scripts`."""
    call = inspect.signature(write).bind(figure, *args, **kwargs)
    call.arguments["post_script"] = _post_scripts(call.arguments.get("post_script"))
    return write(*call.args, **call.kwargs)
