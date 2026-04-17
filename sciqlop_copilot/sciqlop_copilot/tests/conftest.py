"""Stub optional plugin deps so the plugin package can be imported in a test env.

Only stubs modules that fail to import on their own — we never clobber a real
install (e.g. PySide6), which would break pytest-qt.
"""
import importlib
import sys
from typing import ClassVar
from unittest.mock import MagicMock

from pydantic import BaseModel

_OPTIONAL = [
    "PySide6QtAds",
    "SciQLop",
    "SciQLop.components",
    "SciQLop.components.agents",
    "SciQLop.components.agents.backend",
    "SciQLop.components.agents.chat",
    "SciQLop.components.settings",
    "SciQLop.components.settings.backend",
    "SciQLop.components.theming",
    "SciQLop.components.theming.icons",
]
for name in _OPTIONAL:
    if name in sys.modules:
        continue
    try:
        importlib.import_module(name)
    except Exception:
        sys.modules[name] = MagicMock()

class _ConfigEntry(BaseModel):
    category: ClassVar[str]
    subcategory: ClassVar[str]

    def save(self):
        pass


_settings_backend = sys.modules["SciQLop.components.settings.backend"]
if isinstance(_settings_backend, MagicMock):
    _settings_backend.ConfigEntry = _ConfigEntry
    sys.modules["SciQLop.components.settings"].SettingsCategory = type(
        "SettingsCategory", (), {"PLUGINS": "plugins"}
    )
