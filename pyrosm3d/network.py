"""A 3D view of an indoor network, drawn with plotly.

The edges of :meth:`pyrosm.OSM.get_network` or :meth:`pyrosm.OSM.get_graph` with
``indoor_elements=True`` are drawn at their levels: walkways, stairs, escalators,
moving walkways, lifts, platforms and the lines across areas, each kind a legend entry
that hides or shows it.
A walkway tagged with several levels is drawn flat at the lowest, dotted; an edge
without a level at its layer when that is below street level (a tunnel at least one
below), else at street level. The vertical axis counts OSM levels, not metres.
An edge of a simplified graph that joins several ways is drawn way by way (see
:func:`_edges_by_way`).

With a terrain model the edges are drawn at heights in metres instead, those of
:func:`pyrosm3d.heights.network_heights`.
"""

import itertools

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import shapely
from geopandas import GeoDataFrame

from pyrosm3d.dem import sample_dem
from pyrosm3d.tags import (
    crosses_area,
    float_column,
    is_missing,
    is_platform,
    layer_level,
    level_ranges,
    row_tags,
)

# (name in the legend, colour, line width, dash) of each kind of edge
_STYLES = {
    "street": ("Walkways at street level", "#c3c7ce", 1.5, "solid"),
    "levels": ("Walkways on other levels", "#3987e5", 3.5, "solid"),
    "multi": ("Walkways tagged with several levels", "#3987e5", 3.0, "dot"),
    "escalator": ("Escalators", "#c98500", 6.0, "solid"),
    "moving_walkway": ("Moving walkways", "#fa8cd7", 6.0, "dash"),
    "stairs": ("Stairs", "#444b55", 5.0, "solid"),
    "lift": ("Lifts", "#8e44ad", 5.0, "dash"),
    "platform": ("Platforms", "#199e70", 5.0, "solid"),
    "crossing": ("Lines across areas", "#b8bcc4", 1.5, "solid"),
    "area": ("Area outlines", "#8a8f98", 2.5, "dot"),
}
# What one edge of each kind is called
EDGE_NAMES = {
    "street": "walkway",
    "levels": "walkway",
    "multi": "walkway",
    "escalator": "escalator",
    "moving_walkway": "moving walkway",
    "stairs": "stairs",
    "lift": "lift",
    "platform": "platform",
    "crossing": "line across an area",
}
# Metres in a degree of latitude
_METRES_PER_DEGREE = 111_195.0
# The route: red, wide and solid, drawn over the edges; the escalators are amber so that
# they stay apart from it
_ROUTE_COLOUR = "#e8002d"
_ENTRANCES = ("subway_entrance", "train_station_entrance")


def _graph_frames(graph):
    """``(edges, nodes)`` frames of an igraph or networkx ``graph`` of get_graph, each
    edge once whatever its directions (parallel edges of other ways kept); a pandana or
    pandarm network (no line geometry) raises a ValueError."""
    module = type(graph).__module__.split(".")[0]
    if module == "networkx":
        edges = pd.DataFrame(
            [{**data, "u": u, "v": v} for u, v, data in graph.edges(data=True)]
        )
        if "id" not in edges.columns:
            edges = edges.rename(columns={"osmid": "id"})  # pyrosm's networkx name
        nodes = pd.DataFrame([{**data, "id": n} for n, data in graph.nodes(data=True)])
    elif module == "igraph":
        ids = graph.vs["id"] if "id" in graph.vs.attributes() else graph.vs["name"]
        edges = pd.DataFrame(
            [
                {**edge.attributes(), "u": ids[edge.source], "v": ids[edge.target]}
                for edge in graph.es
            ]
        )
        nodes = pd.DataFrame([vertex.attributes() for vertex in graph.vs])
        nodes["id"] = ids
    else:
        raise ValueError(
            "plot_network draws the frames of get_network and igraph or networkx "
            "graphs, not a %s object; pass the frames of get_network(..., nodes=True)."
            % type(graph).__name__
        )
    if edges.empty:
        return GeoDataFrame(geometry=[], crs=4326), None
    edges = GeoDataFrame(edges, geometry="geometry", crs=4326)
    # a directed graph has a two-way edge in both directions, with the same end nodes,
    # line and ids (a simplified edge's id list reversed): draw it once
    ends = np.sort(edges[["u", "v"]].to_numpy(), axis=1)
    shapes = shapely.to_wkb(shapely.normalize(edges.geometry.to_numpy()))
    ids = edges.get("id", pd.Series(None, index=edges.index))
    ids = ids.map(lambda i: str(sorted(i) if isinstance(i, list) else i))
    keys = pd.DataFrame(
        {"a": ends[:, 0], "b": ends[:, 1], "shape": shapes, "id": ids.to_numpy()}
    )
    edges = edges[~keys.duplicated().to_numpy()]
    for x, y in (("x", "y"), ("lon", "lat")):
        if x in nodes.columns and y in nodes.columns:
            points = shapely.points(nodes[x].astype(float), nodes[y].astype(float))
            return edges, GeoDataFrame(nodes, geometry=points, crs=4326)
    return edges, None


def _edges_by_way(edges):
    """``(edges, chains)``: the ``edges`` of a graph (see :func:`_graph_frames`) with
    each edge that joins several ways split into parts that have the values of one way.

    A simplified graph of get_graph holds a list in a cell of such an edge where its
    ways differ, with a value for each segment of the edge's line from ``u`` to ``v``.
    A part is a run of segments with the same values: it has those values, the line of
    its segments, its share of the ``length`` and, where it meets the next part, a new
    node id below zero and below every id of the edges. ``chains`` holds the nodes
    along each split edge, ``{(u, v): [u, ..., v]}``.

    An edge that climbs from one level to another is kept whole. A list of another
    length and a list of booleans (networkx's ``oneway`` and ``reversed`` hold the
    different values of the ways, not one for each segment) do not split an edge.
    :func:`pyrosm3d.tags.row_tags` joins the values of the lists that are left."""
    geometry = edges.geometry.name
    listed = np.zeros(len(edges), dtype=bool)
    for column in edges.columns.drop(geometry):
        if edges[column].dtype == object:
            listed |= edges[column].map(type).eq(list).to_numpy()
    u_level, v_level = (float_column(edges, col) for col in ("u_level", "v_level"))
    climbs = np.isfinite(u_level) & np.isfinite(v_level) & (u_level != v_level)
    lowest = pd.to_numeric(edges[["u", "v"]].stack(), errors="coerce").min()
    spare = itertools.count(int(min(0, lowest)) - 1, -1)
    parts, chains, split = [], {}, []
    for row in np.flatnonzero(listed & ~climbs).tolist():
        edge = edges.iloc[row].to_dict()
        points = shapely.get_coordinates(edge[geometry])
        count = len(points) - 1
        lists = {
            column: cell
            for column, cell in edge.items()
            if isinstance(cell, list)
            and len(cell) == count
            and not all(isinstance(value, (bool, np.bool_)) for value in cell)
        }
        if not lists:
            continue
        starts = [0] + [
            i
            for i in range(1, count)
            if any(_differ(cell[i - 1], cell[i]) for cell in lists.values())
        ]
        nodes = [edge["u"], *itertools.islice(spare, len(starts) - 1), edge["v"]]
        along = _along_lines(points, np.zeros(len(points), dtype=int), 1)[2]
        for part, (start, stop) in enumerate(zip(starts, starts[1:] + [count])):
            values = {column: cell[start] for column, cell in lists.items()}
            line = shapely.LineString(points[start : stop + 1])
            ends = {"u": nodes[part], "v": nodes[part + 1], geometry: line}
            if "length" in edge:
                ends["length"] = edge["length"] * (along[stop] - along[start])
            parts.append({**edge, **values, **ends})
        chains[(edge["u"], edge["v"])] = nodes
        split.append(row)
    if not split:
        return edges, chains
    parts = GeoDataFrame(parts, geometry=geometry, crs=edges.crs)
    whole = edges.drop(index=edges.index[split])
    return pd.concat([whole, parts], ignore_index=True), chains


def _along_lines(lonlat, edge_of, count):
    """``(first, last, along, lengths)`` of ``count`` lines with the vertices ``lonlat``
    (``edge_of`` names each vertex's line): the positions of each line's first and last
    vertex, for each vertex how far along its line it lies (0 at the first vertex, 1 at
    the last; by position in a line without length, such as a lift), and each line's
    length in metres."""
    counts = np.bincount(edge_of, minlength=count)
    last = np.cumsum(counts) - 1
    first = last - counts + 1
    # East along the shorter way round, also across the 180th meridian
    east = (np.diff(lonlat[:, 0]) + 180.0) % 360.0 - 180.0
    east *= _METRES_PER_DEGREE * np.cos(np.radians(lonlat[1:, 1]))
    steps = np.hypot(east, np.diff(lonlat[:, 1]) * _METRES_PER_DEGREE)
    steps = np.r_[0.0, steps]
    steps[first] = 0.0
    run = np.cumsum(steps)
    run -= run[first][edge_of]
    lengths = run[last]
    total = lengths[edge_of]
    place = (np.arange(len(lonlat)) - first[edge_of]) / (counts[edge_of] - 1)
    along = np.where(total > 0, run / np.where(total > 0, total, 1.0), place)
    return first, last, along, lengths


def _differ(value, other):
    """Whether two values of a cell differ; two missing values do not."""
    if is_missing(value) or is_missing(other):
        return not (is_missing(value) and is_missing(other))
    return value != other


def _along_parts(route, chains):
    """The ``route`` (node ids) with the nodes between the parts of each split edge
    that it runs along, either way (``chains`` of :func:`_edges_by_way`)."""
    nodes = list(route[:1])
    for a, b in zip(route[:-1], route[1:]):
        between = chains.get((a, b)) or chains.get((b, a), [])[::-1]
        nodes += [*between[1:-1], b]
    return nodes


def _edge_kind(tags, vertical, u_level, v_level, crossing):
    """``(kind, z at u, z at v)`` of an edge with the OSM ``tags``, ``vertical`` value
    and end levels."""
    verticals = ("escalator", "moving_walkway", "stairs", "lift")
    if isinstance(vertical, str) and vertical in verticals:
        kind = vertical
    elif crossing:
        kind = "crossing"
    elif is_platform(tags):
        kind = "platform"
    else:
        kind = None
    if np.isnan(u_level) and np.isnan(v_level):
        ranges = level_ranges(tags.get("level"))
        if ranges and (len(ranges) > 1 or ranges[0][0] != ranges[0][1]):
            low = min(r[0] for r in ranges)
            return kind or "multi", low, low
        z = ranges[0][0] if ranges else layer_level(tags)
        return kind or ("street" if z == 0 else "levels"), z, z
    u_level = v_level if np.isnan(u_level) else u_level
    v_level = u_level if np.isnan(v_level) else v_level
    flat = u_level == v_level == 0
    return kind or ("street" if flat else "levels"), u_level, v_level


def _edge_kinds(edges):
    """``(row, tags, kind, z at u, z at v)`` of each of ``edges`` (see
    :func:`_edge_kind`), the row a named tuple of the frame."""
    tags = row_tags(edges)
    u_levels, v_levels = (float_column(edges, col) for col in ("u_level", "v_level"))
    verticals = edges.get("vertical", pd.Series(None, index=edges.index)).to_numpy()
    crossings = crosses_area(edges)
    for i, (edge_tags, row) in enumerate(zip(tags, edges.itertuples())):
        kind, z_u, z_v = _edge_kind(
            edge_tags, verticals[i], u_levels[i], v_levels[i], crossings[i]
        )
        yield row, edge_tags, kind, z_u, z_v


def _edge_text(row, tags, kind, level_u, level_v):
    """The hover text of an edge: its name (else the legend's name of its ``kind``),
    its element with its ``highway`` value (else its ``kind``), and the levels that
    it is drawn at."""
    element, ids = getattr(row, "osm_type", "way"), getattr(row, "id", "")
    if isinstance(ids, list):  # an edge that joins several ways and is kept whole
        element, ids = element + "s", ", ".join(dict.fromkeys(map(str, ids)))
    return "%s<br>%s %s · %s<br>%s" % (
        tags.get("name") or _STYLES[kind][0],
        element,
        ids,
        tags.get("highway", kind),
        end_levels_text(level_u, level_v),
    )


def end_levels_text(level_u, level_v):
    """``"level 0"`` for a line on one level, ``"levels 0 → 1"`` for one that runs
    from one level to another."""
    if level_u == level_v:
        return "level %g" % level_u
    return "levels %g → %g" % (level_u, level_v)


def _line_points(line, z_u, z_v, origin, vertical=False):
    """x, y (metres from ``origin``) and z of the points of ``line``, z running from
    ``z_u`` to ``z_v`` along it; a vertical line at its first point when ``vertical``
    or when it has no length, as a lift."""
    xy = shapely.get_coordinates(line)
    steps = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
    if vertical or steps[-1] == 0:
        xy, z = xy[:1].repeat(2, axis=0), np.array([z_u, z_v])
    else:
        z = z_u + (z_v - z_u) * steps / steps[-1]
    return xy[:, 0] - origin[0], xy[:, 1] - origin[1], z


def _line_heights(line, origin, vertical=False):
    """x, y (metres from ``origin``) and z of the points of ``line``, a line with a
    height in metres at every vertex (see :func:`pyrosm3d.heights.network_heights`); a
    vertical line at its first point when ``vertical`` or when it has no length, as a
    lift."""
    points = shapely.get_coordinates(line, include_z=True)
    if vertical or shapely.length(line) == 0:
        points = points[[0, -1]]
        points[1, :2] = points[0, :2]
    return points[:, 0] - origin[0], points[:, 1] - origin[1], points[:, 2]


def _edge_points(line, kind, z_u, z_v, origin, in_metres):
    """x, y (metres from ``origin``) and z of the points of the ``line`` of an edge of
    the ``kind``, a lift a vertical line: its own heights when ``in_metres`` (see
    :func:`_line_heights`), else its levels from ``z_u`` to ``z_v`` (see
    :func:`_line_points`)."""
    if in_metres:
        return _line_heights(line, origin, vertical=kind == "lift")
    return _line_points(line, z_u, z_v, origin, vertical=kind == "lift")


class _Trace:
    """The points of one legend entry, lines separated by gaps."""

    def __init__(self):
        self.x, self.y, self.z, self.text = [], [], [], []

    def add(self, x, y, z, text, in_metres=False):
        """Add one line through the points ``x``, ``y``, ``z`` (rounded to hundredths),
        labelled ``text``, and with the height of each point when ``z`` is
        ``in_metres``."""
        self.x += np.round(x, 2).tolist() + [None]
        self.y += np.round(y, 2).tolist() + [None]
        self.z += np.round(z, 2).tolist() + [None]
        if in_metres:
            self.text += ["%s<br>%.1f m" % (text, height) for height in z] + [None]
        else:
            self.text += [text] * len(x) + [None]


def plot_network(
    edges, nodes=None, center=None, radius=None, route=None, areas=None, dem=None
):
    """A plotly Figure of an indoor network in 3D (see the module docstring).

    Parameters
    ----------
    edges : GeoDataFrame, igraph.Graph or networkx.MultiDiGraph
        The edges of ``get_network(..., nodes=True, indoor_elements=True)``, or a graph
        of ``get_graph(indoor_elements=True)`` (igraph or networkx). An edge of a
        simplified graph that joins several ways is drawn way by way, each part with
        the tags of its way.
    nodes : GeoDataFrame (optional)
        The nodes of the same read: their station entrances (``railway`` tagged
        ``subway_entrance`` or ``train_station_entrance``) are drawn as markers, and the
        ``route`` is drawn through them. Taken from the graph when ``edges`` is one.
    center : (lon, lat) or shapely Point (optional)
        The middle of the view; by default the middle of the edges.
    radius : float (optional)
        Draw only the edges and areas that reach within this many metres (at least 0)
        of ``center``, and the entrances within it; the ``route`` is drawn in full.
    route : list of node ids (optional)
        A path through the network, such as a shortest path of a networkx graph, drawn
        as a wide red line along the edges between its nodes (``u`` and ``v``), also
        beyond ``radius``, with markers at its two ends; a click on "Route" in the
        legend hides it.
    areas : GeoDataFrame (optional)
        Polygons, such as platform areas or squares, drawn as outlines at their
        ``level`` (street level without one); lines are drawn as they are. Areas have
        no heights in metres, so they cannot be given with ``dem``.
    dem : str or pathlib.Path, a sequence of them, or a function (optional)
        A terrain model: a raster file of heights such as a GeoTIFF (reading one needs
        ``pip install "pyrosm3d[dem]"``), several tiles of one, or a function
        ``(longitudes, latitudes) -> heights``. The network is then drawn at heights in
        metres (see :func:`pyrosm3d.heights.network_heights`): streets on the terrain,
        floors placed from the streets that they meet, an entrance at the height of
        an edge drawn on its level at its node, else on the ground. The hover texts
        give the height
        of each point, and an edge with a vertex where the terrain model has no
        height is left out. The edges need the columns ``u`` and ``v``.

    Returns
    -------
    plotly.graph_objects.Figure
        Show it in a notebook with ``fig.show()``, in a browser window with
        ``fig.show(renderer="browser")``, or save it with ``fig.write_html(path)``.
    """
    if radius is not None and not radius >= 0:
        raise ValueError("radius must be at least 0 metres, not %r." % (radius,))
    in_metres = dem is not None
    if in_metres and areas is not None:
        raise ValueError(
            "plot_network draws areas at their levels, not at heights in metres: "
            "give areas or dem, not both."
        )
    is_graph = not isinstance(edges, GeoDataFrame)
    if is_graph:
        edges, graph_nodes = _graph_frames(edges)
        nodes = graph_nodes if nodes is None else nodes
    if edges.empty:
        raise ValueError("plot_network got no edges to draw.")
    if is_graph:
        edges, chains = _edges_by_way(edges)
        route = route if route is None else _along_parts(route, chains)
    if in_metres:
        from pyrosm3d.heights import network_heights  # it imports this module

        edges = network_heights(edges, dem)
        edges = edges[shapely.has_z(edges.geometry.to_numpy())]
        if edges.empty:
            raise ValueError(
                "plot_network found no heights for the edges in the terrain model."
            )
    crs = edges.estimate_utm_crs()
    metric = edges.to_crs(crs)
    if center is None:
        middle = shapely.box(*metric.total_bounds).centroid
    else:
        point = center if hasattr(center, "x") else shapely.Point(*center)
        middle = GeoDataFrame(geometry=[point], crs=4326).to_crs(crs).geometry[0]
    origin = (middle.x, middle.y)
    on_route = metric.iloc[:0]
    if route is not None and "u" in metric.columns and "v" in metric.columns:
        steps = set(zip(route[:-1], route[1:]))
        steps |= {(b, a) for a, b in steps}
        on_route = metric[[pair in steps for pair in zip(metric["u"], metric["v"])]]
    if radius is not None:
        metric = metric[metric.distance(middle) <= radius]
    traces = {kind: _Trace() for kind in _STYLES}
    for row, edge_tags, kind, z_u, z_v in _edge_kinds(metric):
        points = _edge_points(row.geometry, kind, z_u, z_v, origin, in_metres)
        text = _edge_text(row, edge_tags, kind, z_u, z_v)
        traces[kind].add(*points, text, in_metres)
    ends = {
        (row.u, row.v): _edge_points(row.geometry, kind, z_u, z_v, origin, in_metres)
        for row, _, kind, z_u, z_v in _edge_kinds(on_route)
    }
    figure = go.Figure()
    if areas is not None:
        _add_area_outlines(traces["area"], areas.to_crs(crs), middle, radius)
    for kind, (name, colour, width, dash) in _STYLES.items():
        if traces[kind].x:
            figure.add_trace(_lines(traces[kind], name, colour, width, dash))
    if route is not None:
        _add_route(figure, route, ends, in_metres)
    if nodes is not None:
        entrances, heights = _entrances(nodes)
        if in_metres:
            heights = _entrance_heights(entrances, heights, edges, dem)
        _add_entrances(
            figure, entrances.to_crs(crs), heights, middle, radius, in_metres
        )
    figure.update_layout(
        scene=dict(
            xaxis_title="east (m)",
            yaxis_title="north (m)",
            zaxis_title="height (m)" if in_metres else "level",
            aspectmode="manual",
            # heights in metres are drawn flatter: streets slope
            aspectratio=dict(x=1, y=1, z=0.25 if in_metres else 0.5),
        ),
        legend=dict(itemclick="toggle"),
        margin=dict(l=0, r=0, t=30, b=0),
    )
    return figure


def _add_route(figure, route, ends, in_metres):
    """Add the ``route`` (node ids) as a line along the edges between consecutive nodes,
    either way (``ends``: ``{(u, v): (x, y, z)}``, the points of each edge as drawn,
    z ``in_metres`` or in levels), with markers at its first and last point; steps
    without an edge are left out."""
    line_trace = _Trace()
    for a, b in zip(route[:-1], route[1:]):
        if (a, b) in ends:
            points = ends[(a, b)]
        elif (b, a) in ends:
            points = [values[::-1] for values in ends[(b, a)]]
        else:
            continue
        line_trace.add(*points, "route", in_metres)
    if not line_trace.x:
        return
    figure.add_trace(_lines(line_trace, "Route", _ROUTE_COLOUR, 10.0, "solid"))
    points = [i for i, x in enumerate(line_trace.x) if x is not None]
    first, last = points[0], points[-1]
    figure.add_trace(
        go.Scatter3d(
            x=[line_trace.x[first], line_trace.x[last]],
            y=[line_trace.y[first], line_trace.y[last]],
            z=[line_trace.z[first], line_trace.z[last]],
            text=["route start", "route end"],
            mode="markers",
            name="Route ends",
            legendgroup="Route",
            showlegend=False,
            marker=dict(size=7, symbol="circle", color=_ROUTE_COLOUR),
            hovertemplate="%{text}<extra></extra>",
        )
    )


def _lines(trace, name, colour, width, dash):
    """A plotly line trace of the points of ``trace``, its own group in the legend."""
    return go.Scatter3d(
        x=trace.x,
        y=trace.y,
        z=trace.z,
        text=trace.text,
        mode="lines",
        name=name,
        legendgroup=name,
        line=dict(color=colour, width=width, dash=dash),
        hovertemplate="%{text}<extra></extra>",
    )


def _near(geometry, middle, radius):
    """Whether ``geometry`` reaches within ``radius`` metres of the point ``middle``
    (always without a radius)."""
    return radius is None or geometry.distance(middle) <= radius


def _add_area_outlines(trace, areas, middle, radius):
    """Add the outlines of the polygons and the lines among ``areas`` (in metres) that
    reach within ``radius`` of ``middle``, at the lowest level of their ``level`` tag;
    points are left out."""
    for geometry, tags in zip(areas.geometry, row_tags(areas)):
        if geometry is None or not _near(geometry, middle, radius):
            continue
        ranges = level_ranges(tags.get("level"))
        z = min(r[0] for r in ranges) if ranges else 0.0
        for part in shapely.get_parts(geometry):
            if part.geom_type == "Polygon":
                lines = shapely.get_rings(part)
            elif part.geom_type == "LineString":
                lines = [part]
            else:
                continue
            for line in lines:
                points = _line_points(line, z, z, (middle.x, middle.y))
                trace.add(*points, "area, level %g" % z)


def _entrances(nodes):
    """``(entrances, levels)``: the station entrances among ``nodes`` (``railway``
    tagged ``subway_entrance`` or ``train_station_entrance``), and for each the lowest
    level of its ``level`` tag (street level, 0, without one)."""
    rows, levels = [], []
    for row, tags in enumerate(row_tags(nodes)):
        if tags.get("railway") in _ENTRANCES:
            ranges = level_ranges(tags.get("level"))
            rows.append(row)
            levels.append(min(r[0] for r in ranges) if ranges else 0.0)
    return nodes.iloc[rows], levels


def _entrance_heights(entrances, levels, edges, dem):
    """The heights in metres of the station ``entrances`` on their ``levels``: that
    of an end of ``edges`` (with the heights of
    :func:`pyrosm3d.heights.network_heights`) at the node, of an edge drawn on that
    level there (see :func:`_edge_kind`), else the ground's height at the node in the
    terrain model ``dem``."""
    points = entrances.geometry.to_crs(4326)
    ground = sample_dem(points.x.to_numpy(), points.y.to_numpy(), dem)
    ids = entrances["id"]
    on_level = {}
    for row, _, _, z_u, z_v in _edge_kinds(
        edges[edges["u"].isin(ids) | edges["v"].isin(ids)]
    ):
        on_level[(row.u, z_u)] = row.u_height
        on_level[(row.v, z_v)] = row.v_height
    places = zip(ids.tolist(), levels)
    return [on_level.get(place, here) for place, here in zip(places, ground.tolist())]


def _add_entrances(figure, entrances, heights, middle, radius, in_metres=False):
    """Add the station ``entrances`` (in metres) within ``radius`` of ``middle`` as
    markers at their ``heights``, levels or metres (``in_metres``: the hover text
    gives them, and an entrance without a height is left out)."""
    x, y, z, text = [], [], [], []
    for row, height in zip(entrances.itertuples(), heights):
        point = row.geometry
        if not _near(point, middle, radius) or np.isnan(height):
            continue
        x.append(point.x - middle.x)
        y.append(point.y - middle.y)
        z.append(height)
        metres = "<br>%.1f m" % height if in_metres else ""
        text.append("entrance %s%s" % (row.id, metres))
    if x:
        figure.add_trace(
            go.Scatter3d(
                x=x,
                y=y,
                z=z,
                text=text,
                mode="markers",
                name="Station entrances",
                marker=dict(size=3.5, symbol="diamond", color="#1f2329"),
                hovertemplate="%{text}<extra></extra>",
            )
        )
