"""Heights in metres for the network of an indoor read, from a terrain model.

An indoor read counts floors: the ``u_level`` and ``v_level`` of an edge are
OpenStreetMap levels, which each building numbers from its own ground floor.
:func:`network_heights` gives the edges heights in metres from a terrain model.

A street follows the terrain model at every vertex: an edge without a level at its ends
that is not indoors, in a tunnel (a building passage stays a street), on a bridge, below
street level by its layer, a lift or a way tagged with several levels.

An end of another edge at a node of a street has the ground's height there. The other
ends are placed from those, all together. An edge on one level holds its two ends at one
height. Stairs, an escalator, a lift or another edge between two levels wants the
height between them: :data:`pyrosm3d.styles.FLOOR_HEIGHT` metres for each level above
the ground floor, level 0, and :data:`pyrosm3d.styles.UNDERGROUND_FLOOR_HEIGHT` metres
for each level below it (:func:`pyrosm3d.styles.metres_of_levels`). An edge
without a level that is no street (a tunnel, a bridge, an indoor way, a way tagged with
several levels) holds its ends together, so a bridge or a tunnel runs straight between
the streets at its ends. Each of these wishes counts in inverse proportion to the length
of its edge, those of the edges on one level three times, and the heights with the
smallest squared misses are taken. What nothing ties to a street is placed by its
levels alone, as far above or below the ground at its place as its level lies from
the ground floor.

Where the terrain model has no height, a street's end and what is placed there have
none (NaN).

OpenStreetMap holds no depths: a floor that meets no street, such as a metro platform,
is placed by its level from the floors that it is joined to, not at its real depth. A
terrain model shows the ground without what is built on it: a street on a deck or in a
courtyard above a slope follows the modelled ground under it.
"""

import math

import numpy as np
import shapely

from pyrosm3d.dem import sample_dem
from pyrosm3d.network import _along_lines, _edge_kinds
from pyrosm3d.styles import metres_of_levels
from pyrosm3d.tags import float_column

# The keys whose tags can take an edge without a level off the streets
_OFF_STREET_KEYS = ("level", "layer", "indoor", "tunnel", "bridge")
_INDOOR_VALUES = ("yes", "corridor", "room", "area")
# How strongly an edge on one level, one between two levels and one without a level
# hold their ends, per metre of their length (at least one metre)
_LEVEL_WEIGHT, _CLIMB_WEIGHT, _LOOSE_WEIGHT = 3.0, 1.0, 1.0
# The pull of each end towards its place by level, which settles the ends that nothing
# ties to a street and is too weak to move the others
_REST_WEIGHT = 1e-6


def network_heights(edges, dem):
    """The edges of an indoor read with heights in metres from a terrain model (see
    the module docstring for how the heights are found).

    Parameters
    ----------
    edges : GeoDataFrame
        The edges of ``get_network(..., nodes=True, indoor_elements=True)``.
    dem : str or pathlib.Path, a sequence of them, or a function
        The terrain model, as :func:`pyrosm3d.dem.sample_dem` takes it: a raster file of
        heights, several tiles of one, or a function ``(longitudes, latitudes) ->
        heights``.

    Returns
    -------
    GeoDataFrame
        ``edges`` with the columns ``u_height`` and ``v_height``, the height at each
        end of an edge, and with lines that have a height at every vertex. Where the
        terrain model has no height, the height of an end is NaN, and a line with such
        a vertex stays flat: a missing height in a line would turn its coordinates to
        NaN in ``to_crs``.
    """
    if "u" not in edges.columns or "v" not in edges.columns:
        raise ValueError(
            "network_heights needs the end nodes of the edges, the columns u and v "
            "of get_network(..., nodes=True)."
        )
    if edges.empty:
        return edges.assign(u_height=np.nan, v_height=np.nan)
    lines = edges.geometry
    if edges.crs is not None and edges.crs.to_epsg() != 4326:
        lines = lines.to_crs(4326)
    lonlat, edge_of = shapely.get_coordinates(lines.to_numpy(), return_index=True)
    ground = sample_dem(lonlat[:, 0], lonlat[:, 1], dem)
    first, last, along, lengths = _along_lines(lonlat, edge_of, len(edges))
    streets = _streets(edges)
    ends = np.column_stack([ground[first], ground[last]])
    others = np.flatnonzero(~streets)
    if len(others):
        ends[others] = _placed_ends(edges, others, ends, streets, lengths[others])
    straight = ends[edge_of, 0] + (ends[edge_of, 1] - ends[edge_of, 0]) * along
    heights = np.where(streets[edge_of], ground, straight)
    heights[first], heights[last] = ends[:, 0], ends[:, 1]
    whole = np.bincount(edge_of, np.isnan(heights), minlength=len(edges)) == 0
    of_whole = whole[edge_of]
    xyz = np.column_stack([shapely.get_coordinates(edges.geometry.to_numpy()), heights])
    lines = shapely.force_2d(edges.geometry.to_numpy())
    lines[whole] = shapely.linestrings(
        xyz[of_whole], indices=(np.cumsum(whole) - 1)[edge_of[of_whole]]
    )
    found = edges.assign(u_height=ends[:, 0], v_height=ends[:, 1])
    return found.set_geometry(lines, crs=edges.crs)


def _streets(edges):
    """Which of ``edges`` follow the terrain model (see the module docstring)."""
    streets = np.isnan(float_column(edges, "u_level"))
    streets &= np.isnan(float_column(edges, "v_level"))
    rows = np.flatnonzero(streets & _may_be_off_street(edges))
    for row, (_, tags, kind, z_u, z_v) in zip(rows, _edge_kinds(edges.iloc[rows])):
        streets[row] = _is_street(tags, kind, z_u, z_v)
    return streets


def _may_be_off_street(edges):
    """Which rows of ``edges`` have a tag that can take an edge without a level off the
    streets (:func:`_is_street` decides): a value in a column of one of the keys, the
    name of one in their other tags, a corridor or a lift."""
    found = np.zeros(len(edges), dtype=bool)
    for key in _OFF_STREET_KEYS:
        if key in edges.columns:
            found |= edges[key].notna().to_numpy()
    for column, value in (("highway", "corridor"), ("vertical", "lift")):
        if column in edges.columns:
            found |= (edges[column] == value).to_numpy(dtype=bool, na_value=False)
    if "tags" in edges.columns:
        texts = edges["tags"].astype("string").fillna("")
        names = "|".join(_OFF_STREET_KEYS + ("corridor",))
        found |= texts.str.contains(names).to_numpy(dtype=bool)
    return found


def _is_street(tags, kind, z_u, z_v):
    """Whether an edge without a level, with the OSM ``tags``, the ``kind`` and the
    levels it is drawn at (see :func:`pyrosm3d.network._edge_kind`), follows the
    terrain model."""
    off_street = (
        tags.get("indoor") in _INDOOR_VALUES
        or tags.get("highway") == "corridor"
        or tags.get("tunnel") == "yes"
        or tags.get("bridge") not in (None, "no")
    )
    return kind not in ("multi", "lift") and z_u == 0 and z_v == 0 and not off_street


def _placed_ends(edges, rows, ground, streets, lengths):
    """The heights at the two ends of the edges at the positions ``rows``, those that
    are no streets and have the ``lengths`` in metres: ``ground`` holds the terrain's
    height at the two ends of every edge, and ``streets`` marks the streets (see the
    module docstring)."""
    nodes = np.column_stack([edges["u"].to_numpy(), edges["v"].to_numpy()])
    part = edges.iloc[rows]
    levels = np.column_stack(
        [float_column(part, "u_level"), float_column(part, "v_level")]
    )
    drawn = np.array(
        [(z_u, z_v) for _, _, _, z_u, z_v in _edge_kinds(part)], dtype=float
    )
    number, known, rest = _end_numbers(
        nodes[rows],
        levels,
        drawn,
        ground[rows],
        _ground_at_street_nodes(nodes, ground, streets, nodes[rows]),
    )
    on_levels = ~np.isnan(levels).any(axis=1)
    metres = metres_of_levels(levels)
    climbs = np.where(on_levels, metres[:, 1] - metres[:, 0], 0.0)
    hold = np.where(climbs != 0, _CLIMB_WEIGHT, _LEVEL_WEIGHT)
    weights = np.where(on_levels, hold, _LOOSE_WEIGHT) / np.maximum(lengths, 1.0)
    placed = _least_squares_heights(number, known, climbs, weights, rest)
    free = number >= 0
    known[free] = placed[number[free]]
    return known


def _ground_at_street_nodes(nodes, ground, streets, wanted):
    """``{node: height}`` of the nodes among ``wanted`` that a street ends at, where
    the terrain has a height: ``nodes`` and ``ground`` hold the two end nodes of every
    edge and the terrain's height there, and ``streets`` marks the streets."""
    found = {}
    wanted = np.unique(wanted)
    for side in (0, 1):
        hit = streets & np.isfinite(ground[:, side]) & np.isin(nodes[:, side], wanted)
        found.update(zip(nodes[hit, side].tolist(), ground[hit, side].tolist()))
    return found


def _end_numbers(nodes, levels, drawn, ground, street_ground):
    """``(number, known, rest)`` of the ends of edges, arrays with a row for each edge
    and a column for each of its two ends, and ``rest`` with a value for each number.

    An end at a node of ``street_ground`` (``{node: height}``) has that height in
    ``known`` and the number -1. The other ends are numbered from 0, and ends share a
    number when they are one place: the same node (``nodes``) on the same level
    (``levels``, NaN without one). An end without a level is the place of its node on
    the level closest to the one its edge is drawn at (``drawn``), the lower of two as
    close, when the node has ends with a level. ``rest`` is the height of each place by
    its level alone (the drawn one without a level): as far from the ``ground`` there
    as :func:`pyrosm3d.styles.metres_of_levels` gives for it.
    """
    levels_at = {}
    for node, level in zip(nodes.ravel().tolist(), levels.ravel().tolist()):
        if not math.isnan(level):
            levels_at.setdefault(node, set()).add(level)
    numbers, rest = {}, []
    number = np.full(nodes.size, -1)
    known = np.full(nodes.size, np.nan)
    ends = zip(
        nodes.ravel().tolist(),
        levels.ravel().tolist(),
        drawn.ravel().tolist(),
        ground.ravel().tolist(),
    )
    for end, (node, level, drawn_level, here) in enumerate(ends):
        if node in street_ground:
            known[end] = street_ground[node]
            continue
        if math.isnan(level) and node in levels_at:
            level = min(
                sorted(levels_at[node]), key=lambda found: abs(found - drawn_level)
            )
        place = (node, None if math.isnan(level) else level)
        if place not in numbers:
            numbers[place] = len(numbers)
            floor = drawn_level if math.isnan(level) else level
            rest.append(here + float(metres_of_levels(floor)))
        number[end] = numbers[place]
    shape = nodes.shape
    return number.reshape(shape), known.reshape(shape), np.array(rest, dtype=float)


def _least_squares_heights(number, known, climbs, weights, rest):
    """The heights of the numbered ends of edges (see :func:`_end_numbers`) that miss
    the edges' wishes least: each edge wants its second end ``climbs`` metres above its
    first, and its miss, squared, counts by ``weights``; an end that has the number -1
    stays at its ``known`` height. Each height is also held weakly at its ``rest``
    value; one without a ``rest`` value (NaN) is not held, and comes out NaN."""
    if not len(rest):
        return rest
    lost = np.isnan(rest)
    hold = np.where(lost, 0.0, _REST_WEIGHT)
    rest = np.where(lost, 0.0, rest)
    free = number >= 0
    # What an edge asks of each of its ends: the height of its other end, when that is
    # known, less the climb for the first end and plus the climb for the second
    asked = np.where(free[:, ::-1], 0.0, known[:, ::-1]) + np.outer(climbs, [-1.0, 1.0])
    pull = np.repeat(weights[:, None], 2, axis=1)
    count = len(rest)
    diagonal = hold + np.bincount(number[free], pull[free], minlength=count)
    target = hold * rest
    target += np.bincount(number[free], (pull * asked)[free], minlength=count)
    both = free.all(axis=1)
    one, other, tie = number[both, 0], number[both, 1], weights[both]

    def left_side(heights):
        """The left side of the equations of the least squares for ``heights``."""
        found = diagonal * heights
        found -= np.bincount(one, tie * heights[other], minlength=count)
        found -= np.bincount(other, tie * heights[one], minlength=count)
        return found

    # Conjugate gradients, each equation scaled by its diagonal
    heights = rest.copy()
    missing = target - left_side(heights)
    scaled = missing / diagonal
    step = scaled.copy()
    size = missing @ scaled
    rounds = 0
    while np.abs(missing).max() > 1e-3 * _REST_WEIGHT and rounds < 20 * count + 100:
        rounds += 1
        moved = left_side(step)
        pace = size / (step @ moved)
        heights += pace * step
        missing -= pace * moved
        scaled = missing / diagonal
        size, before = missing @ scaled, size
        step = scaled + (size / before) * step
    heights[lost] = np.nan
    return heights
