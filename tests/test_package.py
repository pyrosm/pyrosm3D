import importlib
import importlib.metadata

import pyrosm3d


def test_version(monkeypatch):
    """``pyrosm3d.__version__`` is the version of the installed distribution, and
    "unknown" in a source tree that is not installed."""
    assert pyrosm3d.__version__ == importlib.metadata.version("pyrosm3d")

    def not_installed(name):
        raise importlib.metadata.PackageNotFoundError(name)

    with monkeypatch.context() as patched:
        patched.setattr(importlib.metadata, "version", not_installed)
        assert importlib.reload(pyrosm3d).__version__ == "unknown"
    importlib.reload(pyrosm3d)
