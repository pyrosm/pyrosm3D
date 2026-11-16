"""Heights from a terrain model that the user supplies.

A terrain model (a digital elevation model, DEM) is a raster of ground heights.
pyrosm3d reads one from a GeoTIFF or another raster file that rasterio opens, or from
several tiles of one, and bundles and downloads none. A function that returns the
heights of coordinates can stand in for a file.
"""

import os

import numpy as np


def sample_dem(longitudes, latitudes, dem):
    """The heights of the terrain model ``dem`` at coordinates.

    Parameters
    ----------
    longitudes, latitudes : array-like
        The coordinates, in EPSG:4326.
    dem : str or pathlib.Path, a sequence of them, or a function
        A raster file of heights, such as a GeoTIFF, or several tiles of one, where a
        coordinate takes the height of the first tile that has one; or a function
        ``(longitudes, latitudes) -> heights``.

    Returns
    -------
    numpy.ndarray
        One height for each coordinate, in the unit of the terrain model: between the
        four pixel centres around the coordinate, in proportion to the distances; NaN
        outside the raster and where one of the pixels it is taken from has no data.
    """
    longitudes = np.asarray(longitudes, dtype=float)
    latitudes = np.asarray(latitudes, dtype=float)
    if callable(dem):
        heights = np.array(dem(longitudes, latitudes), dtype=float)
        if heights.shape != longitudes.shape:
            raise ValueError(
                "The dem function returned %s heights for %s coordinates."
                % (heights.shape, longitudes.shape)
            )
        return heights
    paths = [dem] if isinstance(dem, (str, os.PathLike)) else list(dem)
    if not paths:
        raise ValueError("dem names no raster file.")
    rasterio = _rasterio()
    heights = np.full(longitudes.shape, np.nan)
    for path in paths:
        missing = np.isnan(heights)
        if not missing.any():
            break
        heights[missing] = _raster_heights(
            rasterio, os.fspath(path), longitudes[missing], latitudes[missing]
        )
    return heights


def _rasterio():
    """The rasterio module, with a note on how to get it when it is not installed."""
    try:
        import rasterio
        import rasterio.warp
        import rasterio.windows
    except ImportError as error:
        raise ImportError(
            "Reading a terrain model file needs rasterio: install it with "
            'pip install "pyrosm3d[dem]", or give a function as dem.'
        ) from error
    return rasterio


def _raster_heights(rasterio, path, longitudes, latitudes):
    """The heights of the raster file at ``path`` at the coordinates (EPSG:4326), from
    its first band with its scale and offset; NaN outside it (see
    :func:`sample_dem`)."""
    with rasterio.open(path) as raster:
        xs, ys = rasterio.warp.transform("EPSG:4326", raster.crs, longitudes, latitudes)
        # Positions counted in pixels from the centre of the first pixel
        cols, rows = ~raster.transform * (np.asarray(xs), np.asarray(ys))
        cols, rows = cols - 0.5, rows - 0.5
        inside = (
            (cols >= -0.5)
            & (cols <= raster.width - 0.5)
            & (rows >= -0.5)
            & (rows <= raster.height - 0.5)
        )
        heights = np.full(len(cols), np.nan)
        if not inside.any():
            return heights
        # Within half a pixel of the raster's edge the nearest pixel centre counts
        col = np.clip(cols[inside], 0, raster.width - 1)
        row = np.clip(rows[inside], 0, raster.height - 1)
        left, top = np.floor(col).astype(int), np.floor(row).astype(int)
        right = np.minimum(left + 1, raster.width - 1)
        bottom = np.minimum(top + 1, raster.height - 1)
        window = rasterio.windows.Window(
            left.min(),
            top.min(),
            right.max() - left.min() + 1,
            bottom.max() - top.min() + 1,
        )
        band = raster.read(1, window=window, masked=True)
        scale, offset = raster.scales[0], raster.offsets[0]

    def pixels(rows, cols):
        values = band[rows - top.min(), cols - left.min()]
        return np.ma.filled(values.astype(float), np.nan) * scale + offset

    across, down = col - left, row - top
    upper = _between(pixels(top, left), pixels(top, right), across)
    lower = _between(pixels(bottom, left), pixels(bottom, right), across)
    heights[inside] = _between(upper, lower, down)
    return heights


def _between(first, second, share):
    """The values at ``share`` (0 to 1) of the way from ``first`` to ``second``;
    ``first`` itself at 0, also where ``second`` is NaN."""
    return np.where(share == 0, first, first + (second - first) * share)
