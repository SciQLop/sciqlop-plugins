"""Root conftest for the sciqlop_opencode plugin.

Stubs Qt and SciQLop modules in ``sys.modules`` before pytest imports
the ``sciqlop_opencode`` package, so module-level imports in
``__init__.py`` (which match the convention of the other agent plugins)
don't break collection in an environment where those modules aren't
installed.
"""
import importlib
import sys
from unittest.mock import MagicMock

_OPTIONAL = [
    "PySide6QtAds",
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtGui",
    "PySide6.QtWidgets",
    "SciQLop",
    "SciQLop.components",
    "SciQLop.components.agents",
    "SciQLop.components.agents.backend",
    "SciQLop.components.agents.chat",
    "SciQLop.components.theming",
    "SciQLop.components.theming.icons",
    "SciQLop.components.workspaces",
]
for name in _OPTIONAL:
    if name in sys.modules:
        continue
    try:
        importlib.import_module(name)
    except Exception:
        sys.modules[name] = MagicMock()
