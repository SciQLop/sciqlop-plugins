"""Stub optional plugin deps so backend/sessions modules can be imported in a test env."""
import importlib
import sys
from unittest.mock import MagicMock

_OPTIONAL = [
    "PySide6QtAds",
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
