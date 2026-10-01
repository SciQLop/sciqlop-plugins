"""Smoke + integration tests for the plugin entry point."""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import sciqlop_sismo


def test_version_is_set():
    assert sciqlop_sismo.__version__ == "0.1.0"


def test_entry_point_resolves():
    """Read the declaration, not installed metadata: in dev the plugin is loaded
    from its folder and never pip-installed."""
    import importlib
    import tomllib
    from pathlib import Path

    pyproject = tomllib.loads((Path(__file__).parents[2] / "pyproject.toml").read_text())
    target = pyproject["project"]["entry-points"]["sciqlop.plugins"]["sciqlop_sismo"]
    assert callable(importlib.import_module(target).load)


@contextmanager
def _patch_load_deps():
    """Patch every Qt/heavy dep imported inside load()."""
    with (
        patch("sciqlop_sismo._import_qtads", return_value=MagicMock()),
        patch.dict(
            "sys.modules",
            {
                "PySide6.QtGui": MagicMock(),
                "sciqlop_sismo.dock": MagicMock(),
                "sciqlop_sismo.provider": MagicMock(),
            },
        ),
    ):
        yield


def test_load_registers_dock_and_returns_handle():
    main_window = MagicMock()
    with _patch_load_deps():
        handle = sciqlop_sismo.load(main_window)
    assert handle is not None
    main_window.addWidgetIntoDock.assert_called_once()
    main_window.toolsMenu.addAction.assert_called_once()


def test_load_idempotent():
    sciqlop_sismo._LOADED_PANELS.clear()
    main_window = MagicMock()
    with _patch_load_deps():
        h1 = sciqlop_sismo.load(main_window)
        h2 = sciqlop_sismo.load(main_window)
    assert h1 is h2
    main_window.addWidgetIntoDock.assert_called_once()
