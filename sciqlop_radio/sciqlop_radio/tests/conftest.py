"""Test fixtures for sciqlop_radio.

- Stubs optional SciQLop / Qt modules so unit tests can import the package
  without a full SciQLop install (mirrors the sciqlop_albert pattern).
- Registers atexit os._exit(0) to dodge the SciQLopPlots interpreter-shutdown
  segfault (see feedback_sciqlopplots_exit_segfault memory).
"""
import atexit
import importlib
import os
import sys
from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel


_OPTIONAL = [
    "PySide6QtAds",
    "SciQLop",
    "SciQLop.components",
    "SciQLop.components.settings",
    "SciQLop.components.settings.backend",
    "SciQLop.components.theming",
    "SciQLop.components.plotting",
    "SciQLop.components.plotting.backend",
    "SciQLop.components.plotting.backend.easy_provider",
    "SciQLop.core",
    "SciQLop.core.plot_hints",
    "SciQLop.core.istp_hints",
    "SciQLop.core.speasy_hints",
    "SciQLop.core.enums",
    "SciQLopPlots",
]
# Pre-stub modules that require QCoreApplication and cause SIGABRT before
# Python can catch the exception. easy_provider in particular initializes global
# Qt state (ProductsModel static) that needs a QCoreApplication.
_REQUIRES_QAPP = {
    "SciQLop.components.plotting.backend.easy_provider",
}
for name in _REQUIRES_QAPP:
    if name not in sys.modules:
        sys.modules[name] = MagicMock()

for name in _OPTIONAL:
    if name in _REQUIRES_QAPP:
        continue
    if name in sys.modules:
        continue
    try:
        importlib.import_module(name)
    except Exception:
        sys.modules[name] = MagicMock()


class _ConfigEntry(BaseModel):
    """Real-pydantic stub so field_validator and bounds checks actually run."""
    category: ClassVar[str] = ""
    subcategory: ClassVar[str] = ""

    def save(self):
        pass


_settings_backend = sys.modules["SciQLop.components.settings.backend"]
if isinstance(_settings_backend, MagicMock):
    _settings_backend.ConfigEntry = _ConfigEntry
    _settings = sys.modules["SciQLop.components.settings"]
    if isinstance(_settings, MagicMock):
        _settings.SettingsCategory = type(
            "SettingsCategory", (), {"PLUGINS": "plugins"}
        )


def _force_exit():
    os._exit(0)


@pytest.fixture(autouse=True, scope="session")
def _prevent_exit_segfault():
    atexit.register(_force_exit)
    yield
