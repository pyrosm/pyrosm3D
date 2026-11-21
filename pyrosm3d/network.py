"""A 3D view of an indoor network, drawn with deck.gl (see :class:`pyrosm3d.View`).

The edges of :meth:`pyrosm.OSM.get_network` or :meth:`pyrosm.OSM.get_graph` with
``indoor_elements=True`` are drawn at their levels: walkways, stairs, escalators,
moving walkways, lifts, platforms and the lines across areas, each kind a layer that
the page switches on and off. A walkway tagged with several levels is drawn flat at
the lowest; an edge without a level at its layer when that is below street level (a
tunnel at least one below), else at street level. The view is true to scale: a level
is drawn 4 m from the next above the ground floor and 6 m below it
(:func:`pyrosm3d.styles.metres_of_levels`), over a flat ground at street level. An edge
of a simplified graph that joins several ways is drawn way by way (see
:func:`_edges_by_way`).

With a terrain model the edges are drawn at heights in metres instead, those of
:func:`pyrosm3d.heights.network_heights`.
"""

import itertools
import math
from collections import namedtuple

import numpy as np
import pandas as pd
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
from pyrosm3d.styles import HEIGHT_STRETCH, metres_of_levels
from pyrosm3d.view import View

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
# How the kinds of edge are drawn in the views of the city: metres wide on the ground,
# the least and the most pixels on the screen, and the opacity (0 to 255)
_CITY_WIDTHS = {
    "street": (0.5, 0.6, 2.2, 255),
    "crossing": (0.3, 0.4, 1.5, 150),
    "multi": (0.9, 1.2, 4.0, 170),
    "platform": (0.6, 0.8, 3.0, 255),
    "lift": (0.9, 2.0, 4.0, 255),
    "area": (0.3, 0.6, 2.0, 200),
}
_OTHER_WIDTH = (0.9, 1.3, 4.0, 255)
_ROUTE_WIDTH = (1.6, 3.0, 6.0, 255)
# The kinds that lie on the ground in the views of the city: drawn white on it, first
_ON_THE_GROUND = ("street", "crossing")
_STREET_COLOUR = "#ffffff"
# The lines across areas are connections for routing, no built things: off at start
_OFF_AT_START = ("crossing",)
# A line whose points lie this many metres under the ground on average is below ground,
# and keeps this share of its opacity in the see-through view
_BELOW_GROUND = -1.5
_BELOW_SHARE = 0.6
# The ground: a grey surface this far under street level, as far as the network and
# this many metres around it
_GROUND_COLOUR = "#dde1e6"
_GROUND_DROP = 0.4
_GROUND_MARGIN = 20.0


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
    along each split edge, ``{(u, v): [u, ..., v]}``, when it is the shortest of the
    edges between its two end nodes (see :func:`_shortest_between_nodes`): a route
    follows it.

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
    shortest = _shortest_between_nodes(edges)
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
        if shortest[row]:
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


def _shortest_between_nodes(edges):
    """For each of ``edges``, whether it is the shortest of the edges between its two
    end nodes, ``u`` and ``v`` either way round, ties included: by its ``length`` where
    the frame has one, else by the length of its line in metres."""
    lines = edges.geometry
    if edges.crs is not None and edges.crs.to_epsg() != 4326:
        lines = lines.to_crs(4326)
    lonlat, edge_of = shapely.get_coordinates(lines.to_numpy(), return_index=True)
    own = float_column(edges, "length")
    drawn = _along_lines(lonlat, edge_of, len(edges))[3]
    lengths = np.where(np.isnan(own), drawn, own).tolist()
    pairs = [frozenset(pair) for pair in zip(edges["u"], edges["v"])]
    least = {}
    for pair, length in zip(pairs, lengths):
        least[pair] = min(length, least.get(pair, length))
    return np.array([length <= least[pair] for pair, length in zip(pairs, lengths)])


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


def _edge_text(row, tags, kind, level_u, level_v, newline="<br>"):
    """The text of an edge: its name (else the name of its ``kind``), its element with
    its ``highway`` value (else its ``kind``), and the levels that it is drawn at, on
    lines joined by ``newline``."""
    element, ids = getattr(row, "osm_type", "way"), getattr(row, "id", "")
    if isinstance(ids, list):  # an edge that joins several ways and is kept whole
        element, ids = element + "s", ", ".join(dict.fromkeys(map(str, ids)))
    parts = (
        tags.get("name") or _STYLES[kind][0],
        "%s %s · %s" % (element, ids, tags.get("highway", kind)),
        end_levels_text(level_u, level_v),
    )
    return newline.join(parts)


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


def _edge_points(line, kind, level_u, level_v, origin, in_metres):
    """x, y (metres from ``origin``) and z of the points of the ``line`` of an edge of
    the ``kind``, a lift a vertical line: its own heights when ``in_metres`` (see
    :func:`_line_heights`), else from the height of ``level_u`` to that of ``level_v``
    (see :func:`pyrosm3d.styles.metres_of_levels` and :func:`_line_points`)."""
    if in_metres:
        return _line_heights(line, origin, vertical=kind == "lift")
    z_u, z_v = metres_of_levels([level_u, level_v]).tolist()
    return _line_points(line, z_u, z_v, origin, vertical=kind == "lift")


_Frames = namedtuple(
    "_Frames", ["edges", "nodes", "route", "metric", "crs", "middle", "on_route"]
)


def _network_frames(edges, nodes, center, radius, route, areas, dem):
    """What the views of a network draw from their arguments (see
    :func:`plot_network`): the ``edges`` as frames, split way by way for a graph, with
    heights from the terrain model ``dem`` (those without heights left out); the
    ``nodes``, from a graph when not given; the ``route`` along the parts of split
    edges; the edges in metres (``metric``, in the UTM zone ``crs``) within ``radius``
    of the ``middle`` of the view; and the edges in metres that the route follows.
    Raises a ValueError for what cannot be drawn."""
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
    followed = np.zeros(len(edges), dtype=bool)
    if route is not None and "u" in edges.columns and "v" in edges.columns:
        steps = set(zip(route[:-1], route[1:]))
        steps |= {(b, a) for a, b in steps}
        on_step = [pair in steps for pair in zip(edges["u"], edges["v"])]
        followed = np.array(on_step, dtype=bool) & _shortest_between_nodes(edges)
    if in_metres:
        from pyrosm3d.heights import network_heights  # it imports this module

        edges = network_heights(edges, dem)
        drawn = shapely.has_z(edges.geometry.to_numpy())
        edges, followed = edges[drawn], followed[drawn]
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
    on_route = metric[followed]
    if radius is not None:
        metric = metric[(metric.distance(middle) <= radius).to_numpy()]
    return _Frames(edges, nodes, route, metric, crs, middle, on_route)


def _near(geometry, middle, radius):
    """Whether ``geometry`` reaches within ``radius`` metres of the point ``middle``
    (always without a radius)."""
    return radius is None or geometry.distance(middle) <= radius


def _area_lines(areas, middle, radius):
    """The outlines of the polygons and the lines among ``areas`` (in metres) that
    reach within ``radius`` of ``middle``, at the lowest level of their ``level`` tag:
    for each, its x, y (metres from ``middle``) and z, and that level; points are left
    out."""
    for geometry, tags in zip(areas.geometry, row_tags(areas)):
        if geometry is None or not _near(geometry, middle, radius):
            continue
        ranges = level_ranges(tags.get("level"))
        level = min(r[0] for r in ranges) if ranges else 0.0
        z = float(metres_of_levels(level))
        for part in shapely.get_parts(geometry):
            if part.geom_type == "Polygon":
                lines = shapely.get_rings(part)
            elif part.geom_type == "LineString":
                lines = [part]
            else:
                continue
            for line in lines:
                yield _line_points(line, z, z, (middle.x, middle.y)), level


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


def plot_network(
    edges, nodes=None, center=None, radius=None, route=None, areas=None, dem=None
):
    """A 3D view of an indoor network (see the module docstring).

    Parameters
    ----------
    edges : GeoDataFrame, igraph.Graph or networkx.MultiDiGraph
        The edges of ``get_network(..., nodes=True, indoor_elements=True)``, or a graph
        of ``get_graph(indoor_elements=True)`` (igraph or networkx). An edge of a
        simplified graph that joins several ways is drawn way by way, each part with
        the tags of its way.
    nodes : GeoDataFrame (optional)
        The nodes of the same read: their station entrances (``railway`` tagged
        ``subway_entrance`` or ``train_station_entrance``) are points that are off
        until they are switched on in the list of layers, and the ``route`` is drawn
        through them. Taken from the graph when ``edges`` is one.
    center : (lon, lat) or shapely Point (optional)
        The middle of the view; by default the middle of the edges.
    radius : float (optional)
        Draw only the edges and areas that reach within this many metres (at least 0)
        of ``center``, and the entrances within it; the ``route`` is drawn in full.
    route : list of node ids (optional)
        A path through the network, such as a shortest path of a networkx graph, drawn
        as a wide red line along the edges between its nodes (``u`` and ``v``), also
        beyond ``radius``, over what is in front of it, with points at its two ends.
        Where several edges join two nodes, the route is drawn along the shortest (by
        ``length`` where the edges have it, else by their lines); with ``dem``, a step
        whose shortest edge has no heights is left out. The view starts over the
        route.
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
        an edge drawn on its level at its node, else on the ground. A tapped edge
        shows its heights, and an edge with a vertex where the terrain model has no
        height is left out. The edges need the columns ``u`` and ``v``.

    Returns
    -------
    pyrosm3d.View
        In a notebook the view is the output of the cell; ``view.to_html(path)`` writes
        it as a page and ``view.show()`` shows it. It opens in the solid model, also
        seen through as a map; "True heights" off draws the heights taller.
    """
    frames = _network_frames(edges, nodes, center, radius, route, areas, dem)
    edges, nodes, route, in_metres = (
        frames.edges,
        frames.nodes,
        frames.route,
        dem is not None,
    )
    metric, crs, middle, on_route = (
        frames.metric,
        frames.crs,
        frames.middle,
        frames.on_route,
    )
    origin = (middle.x, middle.y)
    lines = _NetworkLines(in_metres)
    ground = _ground_under(metric, dem)
    for at, (row, edge_tags, kind, z_u, z_v) in enumerate(_edge_kinds(metric)):
        points = _edge_points(row.geometry, kind, z_u, z_v, origin, in_metres)
        lines.add(kind, row, edge_tags, z_u, z_v, np.column_stack(points), ground[at])
    groups = lines.groups()
    if areas is not None:
        groups += _area_groups(areas.to_crs(crs), middle, radius)
    ends = {
        frozenset((row.u, row.v)): (
            row.u,
            _edge_points(row.geometry, kind, z_u, z_v, origin, in_metres),
        )
        for row, _, kind, z_u, z_v in _edge_kinds(on_route)
    }
    route_groups = [] if route is None else _route_groups(route, ends)
    groups += route_groups
    if nodes is not None:
        entrances, levels = _entrances(nodes)
        if in_metres:
            heights = _entrance_heights(entrances, levels, edges, dem)
        else:
            heights = metres_of_levels(levels).tolist()
        groups += _entrance_groups(
            entrances.to_crs(crs), heights, middle, radius, in_metres
        )
    paths = [
        item["p"]
        for group in groups
        if group["kind"] == "lines"
        for item in group["items"]
    ]
    paths += [
        [item["c"]]
        for group in groups
        if group["kind"] == "points"
        for item in group["items"]
    ]
    if not paths:  # nothing within the radius: an empty view at the center
        paths = [[[0.0, 0.0, 0.0]]]
    if not in_metres:
        groups.insert(0, _flat_ground(paths))
    shown = [item["p"] for item in route_groups[0]["items"]] if route_groups else paths
    ground_at = _ground_at_middle(crs, origin, dem)
    view, fit = _start_view(shown, ground_at, turned=bool(route_groups), radius=radius)
    data = dict(
        mode="solid",
        view=view,
        fit=fit,
        stretch=HEIGHT_STRETCH,
        tables=lines.tables(),
        groups=groups,
    )
    heights = "at heights in metres" if in_metres else "at its levels"
    about = (
        "The network with its indoor elements %s: walkways, stairs, escalators, lifts "
        "and platforms each have a colour of their own." % heights
    )
    return View(data, title="Network in 3D", about=about)


class _NetworkLines:
    """The edges of a network as the items of the view's groups of lines, a group for
    each kind of edge, with the tables of names and highway values that the items
    refer to by number (see :meth:`add`)."""

    def __init__(self, in_metres):
        self.in_metres = in_metres
        self.items = {kind: [] for kind in _STYLES}
        self.names, self.highways = {}, {}

    def add(self, kind, row, tags, level_u, level_v, points, ground, levels=None):
        """Add the edge ``row`` of the ``kind``, drawn through ``points`` (x, y and z
        in metres) from ``level_u`` to ``level_v``, over the ground at the height
        ``ground``: below ground when its points lie under it by more than
        ``_BELOW_GROUND`` on average. An edge that goes on where the last one of its
        kind ends, of the same element (one with an id) and as far below ground,
        makes one line with it. An edge that joins several ways, kept whole, or has
        no id has a text of its own instead of numbers into the tables. The indoor
        view shows the line on ``levels`` (``ls``) where they are given and other
        than its first level."""
        points = np.round(points, 1)
        below = int(np.nanmean(points[:, 2]) - ground < _BELOW_GROUND)
        heights = [float(points[:, 2].min()), float(points[:, 2].max())]
        element, ids = getattr(row, "osm_type", "way"), getattr(row, "id", "")
        items = self.items[kind]
        name = tags.get("name") or _STYLES[kind][0]
        highway = str(tags.get("highway", kind))
        if isinstance(ids, list) or is_missing(ids) or ids == "":
            # an edge that joins several ways (kept whole) or has no id: its own text
            if isinstance(ids, list):
                text = _edge_text(row, tags, kind, level_u, level_v, newline="\n")
            else:
                text = "\n".join((name, highway, end_levels_text(level_u, level_v)))
            item = {"p": points.tolist(), "t": text}
            if levels is not None:
                item["ls"] = list(levels)
            if below:
                item["b"] = 1
            if self.in_metres:
                item["m"] = heights
            items.append(item)
            return
        last = items[-1] if items else None
        path = points.tolist()
        code = {"relation": 1, "node": 2}.get(element, 0)
        if (
            last is not None
            and last.get("w") == ids
            and last.get("e", 0) == code
            and last.get("b", 0) == below
            and last["p"][-1] == path[0]
        ):
            last["p"] += path[1:]
            last["c"] = float(level_v)
            if levels is not None:
                shown = sorted(set(last.get("ls", [last["a"]])) | set(levels))
                if shown != [last["a"]]:
                    last["ls"] = shown
            if self.in_metres:
                last["m"] = [
                    min(last["m"][0], heights[0]),
                    max(last["m"][1], heights[1]),
                ]
            return
        item = {
            "p": path,
            "w": ids.item() if hasattr(ids, "item") else ids,
            "n": self.names.setdefault(name, len(self.names)),
            "h": self.highways.setdefault(highway, len(self.highways)),
            "a": float(level_u),
            "c": float(level_v),
        }
        if code:
            item["e"] = code
        if levels is not None and list(levels) != [item["a"]]:
            item["ls"] = list(levels)
        if below:
            item["b"] = 1
        if self.in_metres:
            item["m"] = heights
        items.append(item)

    def groups(self):
        """The groups of lines, a group for each kind that has edges: the kinds on the
        ground first, white; the lines across areas off at the start."""
        found = []
        for kind in sorted(self.items, key=lambda kind: kind not in _ON_THE_GROUND):
            items = self.items[kind]
            for item in items:
                if item.get("c") == item.get("a"):
                    item.pop("c", None)
            if items:
                found.append(
                    _lines_group(kind, items, visible=kind not in _OFF_AT_START)
                )
        return found

    def tables(self):
        """The names and highway values that the items refer to by number."""
        return dict(names=list(self.names), highways=list(self.highways))


def _lines_group(kind, items, visible=True):
    """A group of lines of the ``kind`` of edge (see ``_STYLES``) with the ``items``: in
    the views of the city as wide as ``_CITY_WIDTHS`` says, in the indoor view with the
    colour, the width in pixels and the dash of ``_STYLES``."""
    name, colour, width, dash = _STYLES[kind]
    metres, least, most, alpha = _CITY_WIDTHS.get(kind, _OTHER_WIDTH)
    return dict(
        name=name,
        kind="lines",
        colour=_STREET_COLOUR if kind in _ON_THE_GROUND else colour,
        metres=metres,
        minPixels=least,
        maxPixels=most,
        alpha=alpha,
        belowShare=_BELOW_SHARE,
        plot=[colour, width, None if dash == "solid" else dash],
        visible=visible,
        items=items,
    )


def _ground_under(metric, dem):
    """For each edge of ``metric`` (in metres), the height of the ground under it: the
    mean of the terrain model ``dem`` at its points (NaN where it has none), or street
    level, 0, without one."""
    if dem is None or metric.empty:
        return np.zeros(len(metric))
    lonlat, row = shapely.get_coordinates(
        metric.geometry.to_crs(4326).to_numpy(), return_index=True
    )
    heights = sample_dem(lonlat[:, 0], lonlat[:, 1], dem)
    known = np.isfinite(heights)
    total = np.bincount(row[known], weights=heights[known], minlength=len(metric))
    count = np.bincount(row[known], minlength=len(metric))
    with np.errstate(invalid="ignore", divide="ignore"):
        return total / count


def _ground_at_middle(crs, origin, dem):
    """The height of the ground at a point ``x``, ``y`` metres from ``origin`` in
    ``crs``: from the terrain model ``dem``, 0 without one or where it has none, as a
    function ``(x, y) -> height``."""
    if dem is None:
        return lambda x, y: 0.0

    def ground(x, y):
        point = GeoDataFrame(
            geometry=[shapely.Point(origin[0] + x, origin[1] + y)], crs=crs
        ).to_crs(4326)
        height = sample_dem(
            point.geometry.x.to_numpy(), point.geometry.y.to_numpy(), dem
        )
        return float(height[0]) if np.isfinite(height[0]) else 0.0

    return ground


def _flat_ground(paths):
    """The ground of a view without a terrain model: one square at ``_GROUND_DROP``
    under street level around the points of ``paths``, ``_GROUND_MARGIN`` beyond them;
    the walker stands on street level (``t``)."""
    xy = np.array([point[:2] for path in paths for point in path])
    low = xy.min(axis=0) - _GROUND_MARGIN
    side = float((xy.max(axis=0) + _GROUND_MARGIN - low).max())
    grid = dict(
        x=round(float(low[0]), 1),
        y=round(float(low[1]), 1),
        step=round(side, 1),
        rows=2,
        columns=2,
        z=[-_GROUND_DROP] * 4,
        t=[0.0] * 4,
    )
    return dict(
        name="Ground", kind="ground", colour=_GROUND_COLOUR, visible=True, grid=grid
    )


def _start_view(paths, ground_at, turned, radius):
    """``(view, fit)``: where a view starts, over the middle of the points of
    ``paths`` (over the center when a ``radius`` is given and the view is not of a
    route) at the height that ``ground_at`` gives there, 40 degrees above the horizon,
    and how much ground it holds (metres from west to east and from south to north):
    the points with some to spare, or the circle of the radius. A view of a route is
    ``turned`` 20 degrees from north, as the route's prototype page was; else it looks
    north."""
    xy = np.array([point[:2] for path in paths for point in path])
    if radius is not None and math.isfinite(radius) and not turned:
        middle, fit = np.zeros(2), np.full(2, 2.1 * max(radius, 25.0))
    else:
        low, high = xy.min(axis=0), xy.max(axis=0)
        middle, fit = (low + high) / 2, np.maximum((high - low) * 1.1, 50.0)
    widest = float(fit.max())
    view = dict(
        target=[
            round(float(middle[0]), 1),
            round(float(middle[1]), 1),
            round(ground_at(float(middle[0]), float(middle[1])), 1),
        ],
        rotationX=40,
        rotationOrbit=20 if turned else 0,
        zoom=1.15,
        minZoom=min(-3.0, math.floor(math.log2(320 / (4 * widest)) * 10) / 10),
        maxZoom=4.3,
        minRotationX=-90,
        maxRotationX=90,
    )
    return view, [round(float(value), 1) for value in fit]


def _route_groups(route, ends):
    """The groups of the ``route`` (node ids): a line along the edges between
    consecutive nodes, either way (``ends``: ``{frozenset((u, v)): (u, (x, y, z))}``,
    the node an edge starts at and its points as drawn), made of runs where one step
    ends where the next begins, and its first and last points; none when no step is
    an edge."""
    paths = []
    for a, b in zip(route[:-1], route[1:]):
        if frozenset((a, b)) not in ends:
            continue
        start, points = ends[frozenset((a, b))]
        path = np.round(np.column_stack(points), 1).tolist()
        if start != a:
            path = path[::-1]
        if paths and paths[-1][-1] == path[0]:
            paths[-1] += path[1:]
        else:
            paths.append(path)
    if not paths:
        return []
    metres, least, most, alpha = _ROUTE_WIDTH
    line = dict(
        name="Route",
        kind="lines",
        colour=_ROUTE_COLOUR,
        metres=metres,
        minPixels=least,
        maxPixels=most,
        alpha=alpha,
        belowShare=1.0,
        plot=[_ROUTE_COLOUR, 10.0, None],
        visible=True,
        rounded=True,
        always=True,
        items=[{"p": path, "t": "route"} for path in paths],
    )
    ends_group = dict(
        name="Route start and end",
        kind="points",
        colour=_ROUTE_COLOUR,
        width=7.0,
        visible=True,
        items=[
            {"c": paths[0][0], "t": "route start"},
            {"c": paths[-1][-1], "t": "route end"},
        ],
    )
    return [line, ends_group]


def _area_groups(areas, middle, radius):
    """The outlines of ``areas`` that reach within ``radius`` of ``middle`` (see
    :func:`_area_lines`) as a group of lines; no group without such areas."""
    items = [
        {
            "p": np.round(np.column_stack(points), 1).tolist(),
            "t": "area, level %g" % level,
        }
        for points, level in _area_lines(areas, middle, radius)
    ]
    return [_lines_group("area", items)] if items else []


def _entrance_groups(entrances, heights, middle, radius, in_metres=False):
    """The station ``entrances`` (in metres) within ``radius`` of ``middle`` as a group
    of points at their ``heights``: those of their levels, or heights ``in_metres``,
    which their text then gives (an entrance without a height is left out). The group
    is off at the start; no group without entrances."""
    items = []
    for row, height in zip(entrances.itertuples(), heights):
        point = row.geometry
        if not _near(point, middle, radius) or np.isnan(height):
            continue
        text = "entrance %s" % row.id + ("\n%.1f m" % height if in_metres else "")
        place = [point.x - middle.x, point.y - middle.y, float(height)]
        items.append({"c": [round(value, 1) for value in place], "t": text})
    if not items:
        return []
    return [
        dict(
            name="Station entrances",
            kind="points",
            colour="#1f2329",
            width=3.5,
            visible=False,
            items=items,
        )
    ]
