"""3D views of the OpenStreetMap elements that pyrosm reads with their levels."""

from importlib.metadata import PackageNotFoundError, version

from pyrosm3d.figure import plot_indoor
from pyrosm3d.indoor import IndoorElements, read_indoor
from pyrosm3d.network import plot_network

try:
    __version__ = version("pyrosm3d")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "unknown"

__all__ = ["IndoorElements", "plot_indoor", "plot_network", "read_indoor"]
