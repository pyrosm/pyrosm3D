"""3D views of the OpenStreetMap elements that pyrosm reads with their levels."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pyrosm3d")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "unknown"
