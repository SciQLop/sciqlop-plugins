"""Root conftest for the sciqlop_kimi plugin.

Stubs Qt and SciQLop modules in ``sys.modules`` before pytest imports
the ``sciqlop_kimi`` package, so module-level imports in
``__init__.py`` (which match the convention of the other agent plugins)
don't break collection in an environment where those modules aren't
installed.
"""
import importlib
import sys
from unittest.mock import MagicMock

# In a dev env with real PySide6 (running from SciQLop's venv, where pytest-qt
# imports Qt before any conftest runs), importing SciQLop's agents package
# needs a live QApplication — without one the interpreter aborts on import.
try:
    from PySide6.QtWidgets import QApplication

    if isinstance(QApplication, type) and QApplication.instance() is None:
        QApplication([])
except Exception:
    pass

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
