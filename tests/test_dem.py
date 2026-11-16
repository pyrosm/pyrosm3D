import re
import sys

import numpy as np
import pytest
from pyproj import Transformer

from pyrosm3d.dem import sample_dem

# The centre of the pixel in row 2789 and column 3086 of the Helsinki terrain model
# (EPSG:3067, 10 m pixels), on the slope west of Forum. This pixel and its neighbours
# to the east, south and south-east hold 14, 12, 17 and 16 m.
X, Y = 385565.0, 6672005.0


def _lonlat(points):
    """The longitudes and latitudes of ``points`` (x and y in EPSG:3067)."""
    to_lonlat = Transformer.from_crs(3067, 4326, always_xy=True)
    lons, lats = to_lonlat.transform(*zip(*points))
    return np.array(lons), np.array(lats)


def test_sample_dem_takes_heights_between_the_four_pixel_centres(helsinki_dem):
    """At a pixel centre the height is the pixel's, halfway to the next centre the mean
    of the two, in the middle of four centres their mean, and a quarter of the way to
    the east and to the south 14.3125 m; a place outside the raster has none."""
    points = [(X, Y), (X + 5, Y), (X + 5, Y - 5), (X + 2.5, Y - 2.5), (X + 10, Y - 10)]
    heights = sample_dem(*_lonlat(points), helsinki_dem)
    assert heights == pytest.approx([14.0, 13.0, 14.75, 14.3125, 16.0], abs=1e-4)
    assert np.isnan(sample_dem([18.07], [59.33], helsinki_dem)).all()


def test_sample_dem_reads_tiles_and_takes_a_function(helsinki_dem, tmp_path):
    """Two tiles cut from the terrain model give, on either side of their seam, the
    heights of the whole file, each point from the tile that holds it; a path as text
    gives the same, and so does the file followed by a tile, which is then not read.
    The heights of a function come back as they are."""
    import rasterio
    from rasterio.windows import Window

    lons, lats = _lonlat([(X - 12, Y - 3), (X + 27, Y - 8)])
    whole = sample_dem(lons, lats, helsinki_dem)
    tiles = []
    with rasterio.open(helsinki_dem) as raster:
        for name, column in (("west", 3082), ("east", 3087)):
            window = Window(column, 2786, 5, 8)
            tiles.append(tmp_path / (name + ".tif"))
            with rasterio.open(
                tiles[-1],
                "w",
                driver="GTiff",
                dtype=raster.dtypes[0],
                count=1,
                crs=raster.crs,
                width=5,
                height=8,
                transform=raster.window_transform(window),
            ) as tile:
                tile.write(raster.read(1, window=window), 1)
    assert not np.isnan(whole).any()
    assert np.isnan(sample_dem(lons, lats, tiles[0])).tolist() == [False, True]
    for dem in (tiles, str(helsinki_dem), [helsinki_dem, tiles[0]]):
        assert sample_dem(lons, lats, dem) == pytest.approx(whole)
    assert sample_dem(lons, lats, lambda lons, lats: lats * 0 + 7.5).tolist() == [7.5] * 2


@pytest.mark.parametrize(
    "dem, without_rasterio, error, message",
    [
        ([], False, ValueError, "dem names no raster file."),
        (
            lambda lons, lats: [1.0],
            False,
            ValueError,
            "The dem function returned (1,) heights for (2,) coordinates.",
        ),
        ("heights.tif", True, ImportError, 'pip install "pyrosm3d[dem]"'),
    ],
)
def test_sample_dem_refuses_what_gives_no_heights(
    monkeypatch, dem, without_rasterio, error, message
):
    """A list without files and a function that returns another number of heights than
    it got coordinates are refused, and a file without rasterio installed names the
    install extra."""
    if without_rasterio:
        monkeypatch.setitem(sys.modules, "rasterio", None)
    with pytest.raises(error, match=re.escape(message)):
        sample_dem([24.9, 24.95], [60.17, 60.17], dem)
