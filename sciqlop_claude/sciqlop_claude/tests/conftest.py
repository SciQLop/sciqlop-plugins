"""Stub SciQLop GUI-dependent modules so backend/sessions import in a test env.

In a Qt-less CI env the root conftest has already stubbed PySide6 and the
SciQLop imports below fail → they get stubbed too. In a dev env with real
PySide6 (e.g. running from SciQLop's venv, where pytest-qt imports Qt before
any conftest runs), importing SciQLop's agents package needs a live
QApplication, so create one first.
"""
import importlib
import sys
from unittest.mock import MagicMock

try:
    from PySide6.QtWidgets import QApplication

    if isinstance(QApplication, type) and QApplication.instance() is None:
        QApplication([])
except Exception:
    pass

_OPTIONAL = [
    "PySide6QtAds",
    "SciQLop",
    "SciQLop.components",
    "SciQLop.components.agents",
    "SciQLop.components.agents.backend",
    "SciQLop.components.agents.chat",
]
for name in _OPTIONAL:
    if name in sys.modules:
        continue
    try:
        importlib.import_module(name)
    except Exception:
        sys.modules[name] = MagicMock()
