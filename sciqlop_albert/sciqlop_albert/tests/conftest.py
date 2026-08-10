"""Stub optional plugin deps so settings.py can be imported in a test env.

ConfigEntry is stubbed as a real `pydantic.BaseModel` subclass so that
field validators and range checks actually run — otherwise AlbertSettings
inherits from a MagicMock and pydantic machinery is skipped entirely.
"""
import os
import pathlib
import tempfile

# Settings must not read or write the developer's ~/.config/sciqlop: with real
# SciQLop importable, ConfigEntry resolves its YAML path at import time, so the
# redirect has to happen before any SciQLop import (same trick as SciQLop's own
# tests/conftest.py). Without it these tests assert against machine state.
_config_dir = tempfile.mkdtemp(prefix="sciqlop-plugin-tests-config-")
os.environ["XDG_CONFIG_HOME"] = _config_dir
os.environ["APPDATA"] = _config_dir

import importlib
import sys
from unittest.mock import MagicMock

from typing import ClassVar

from pydantic import BaseModel

from enum import StrEnum

# Importing SciQLop's agents package reaches core/models.py, whose Qt global
# static aborts the interpreter without a live QApplication. pytest-qt imports
# real Qt before any conftest runs, so create one here rather than stubbing.
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
    "SciQLop.components.agents.settings",
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


class AgentWriteMode(StrEnum):
    NONE = "none"
    CONFIRM = "confirm"
    YOLO = "yolo"


_agents_settings = sys.modules["SciQLop.components.agents.settings"]
if isinstance(_agents_settings, MagicMock):
    _agents_settings.AgentWriteMode = AgentWriteMode


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


import pytest


@pytest.fixture(autouse=True)
def _fresh_settings_files():
    """Give every test an empty config dir.

    The real `ConfigEntry.__init__` replaces its kwargs with the persisted YAML
    as soon as that file exists (`settings/backend/entry.py`), and it saves on
    first construction — so without this the first test writes the file and
    every later one silently asserts against it instead of its own arguments.
    """
    for stale in pathlib.Path(_config_dir).rglob("*.yaml"):
        stale.unlink(missing_ok=True)
    yield
