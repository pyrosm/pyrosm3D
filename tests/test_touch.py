import plotly.io
import pytest

from pyrosm3d import plot_network
from pyrosm3d.figure import layers_figure
from pyrosm3d.touch import TouchFigure
from pyrosm3d.view import package_text


@pytest.fixture(scope="module")
def network_figure(helsinki_indoor):
    """The walking network 100 m around the railway station of the bundled Helsinki
    file."""
    _, nodes, edges = helsinki_indoor
    return plot_network(edges, nodes, center=(24.9415, 60.1712), radius=100)


def test_figures_have_touch_controls_as_html(
    network_figure, maunula, tmp_path, monkeypatch, capsys
):
    """The figures of plot_network and plot_indoor carry the scripts of the touch
    controls and of the legend of a small screen wherever they become HTML, after the
    scripts that the caller gives, also when those are given by position: in
    ``to_html``, ``write_html``, ``show``, the HTML of a notebook renderer and the
    display of a notebook cell (without a renderer the figure is printed)."""
    scripts = [package_text("touch.js"), package_text("figure.js")]
    assert isinstance(layers_figure(maunula), TouchFigure)
    assert isinstance(network_figure, TouchFigure)

    def controls(page):
        """Where the two scripts start in ``page``, each found once."""
        starts = [script.splitlines()[0] for script in scripts]
        assert [page.count(start) for start in starts] == [1, 1]
        return [page.index(start) for start in starts]

    html = network_figure.to_html(full_html=False, include_plotlyjs=False)
    assert controls(html) == sorted(controls(html))
    own = "window.own = 1;"
    by_name = network_figure.to_html(include_plotlyjs=False, post_script=own)
    by_position = network_figure.to_html(None, True, False, False, [own])
    for page in (by_name, by_position):
        assert page.index(own) < controls(page)[0]
    network_figure.write_html(tmp_path / "figure.html", include_plotlyjs=False)
    controls((tmp_path / "figure.html").read_text(encoding="utf-8"))

    monkeypatch.setattr(plotly.io.renderers, "default", "colab")
    controls(network_figure._repr_mimebundle_()["text/html"])
    monkeypatch.setattr(plotly.io.renderers, "default", "json")
    assert list(network_figure._repr_mimebundle_()) == ["application/json"]

    shown = []
    monkeypatch.setattr(plotly.io, "show", lambda *args, **kwargs: shown.append(kwargs))
    network_figure.show(renderer="browser", post_script=own)
    network_figure._ipython_display_()
    assert shown == [
        {"renderer": "browser", "post_script": [own, *scripts]},
        {"post_script": scripts},
    ]
    monkeypatch.setattr(plotly.io.renderers, "render_on_display", False)
    network_figure._ipython_display_()
    assert len(shown) == 2 and capsys.readouterr().out.startswith("TouchFigure(")


def test_a_figure_outside_a_page_on_a_touch_screen(
    network_figure, tmp_path, run_scripts
):
    """Touches on the view are left to the figure, and two fingers that spread from
    100 px to 200 px apart halve the camera's distance, from 4 to 2. On a small page
    the legend is hidden at start, laid over the view, and the figure has a button
    that shows and hides it; a wide page and a figure with buttons of its own keep
    the legend as it is."""
    path = tmp_path / "figure.html"
    options = dict(full_html=False, include_plotlyjs=False, div_id="plot")
    path.write_text(network_figure.to_html(**options), encoding="utf-8")
    wide = run_scripts(path)
    assert wide["touchAction"] == "none" and wide["layout"] == {}
    assert wide["touches"]["distances"][:2] == [4, 2]
    small = run_scripts(path, size="small")["layout"]
    (menu,) = small.pop("updatemenus")
    assert small == {
        "showlegend": False,
        "legend.x": 0,
        "legend.xanchor": "left",
        "legend.bgcolor": "rgba(255, 255, 255, 0.9)",
    }
    assert menu["buttons"] == [
        {
            "label": "Legend",
            "method": "relayout",
            "args": ["showlegend", True],
            "args2": ["showlegend", False],
        }
    ]
    own = TouchFigure(network_figure)
    own.update_layout(updatemenus=[dict(type="buttons", buttons=[dict(label="x")])])
    path.write_text(own.to_html(**options), encoding="utf-8")
    assert run_scripts(path, size="small")["layout"] == {}
