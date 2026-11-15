"""Sphinx configuration of the pyrosm3d documentation."""

from datetime import datetime
from importlib.metadata import version as installed_version

project = "pyrosm3d"
author = "Henrikki Tenkanen + pyrosm3d contributors"
copyright = f"{datetime.now().year}, {author}"
version = release = installed_version("pyrosm3d")

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "myst_nb",
]
autosummary_generate = True
myst_heading_anchors = 3
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "**.ipynb_checkpoints"]

html_theme = "sphinx_book_theme"
html_title = "pyrosm3d"
html_theme_options = {
    "repository_url": "https://github.com/pyrosm/pyrosm3D",
    "repository_branch": "main",
    "path_to_docs": "docs/",
    "use_repository_button": True,
}

# The notebooks are shown with the outputs stored in them
nb_execution_mode = "off"
