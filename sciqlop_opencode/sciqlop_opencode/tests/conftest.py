"""Stub Qt and SciQLop modules so the package can be imported in a test env.

`sciqlop_opencode/__init__.py` does module-level `import PySide6QtAds` and
`from SciQLop.components... import ...` to match the convention used by the
other plugin packages. Those modules aren't installed in CI, so we slot
MagicMocks into ``sys.modules`` here, before pytest collects any test that
imports the package.
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
