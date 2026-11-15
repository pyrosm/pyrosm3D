"""3D views of the OpenStreetMap elements that pyrosm reads with their levels."""

from importlib.metadata import PackageNotFoundError, version

from pyrosm3d.accessor import In3D
from pyrosm3d.figure import plot_indoor
from pyrosm3d.indoor import IndoorElements, indoor_layers
from pyrosm3d.network import plot_network
from pyrosm3d.page import to_html

try:
    __version__ = version("pyrosm3d")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "unknown"

__all__ = [
    "In3D",
    "IndoorElements",
    "indoor_layers",
    "plot_indoor",
    "plot_network",
    "to_html",
]
