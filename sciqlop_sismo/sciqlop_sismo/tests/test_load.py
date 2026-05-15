"""Smoke + integration tests for the plugin entry point."""
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import sciqlop_sismo


def test_version_is_set():
    assert sciqlop_sismo.__version__ == "0.1.0"


def test_entry_point_resolves():
    from importlib.metadata import entry_points
    eps = entry_points(group="sciqlop.plugins")
    names = {ep.name for ep in eps}
    assert "sciqlop_sismo" in names


@contextmanager
def _patch_load_deps():
    """Patch every Qt/heavy dep imported inside load() and the on-demand dock factory."""
    with (
        patch("sciqlop_sismo._import_qtads", return_value=MagicMock()),
        patch.dict(
            "sys.modules",
            {
                "sciqlop_sismo.dock": MagicMock(),
                "sciqlop_sismo.provider": MagicMock(),
            },
        ),
    ):
        yield


def test_load_registers_menu_only():
    """load() must NOT create the dock — it only wires the tools-menu entry.
    Matches SciQLop's plot-panel pattern: docks are built on demand."""
    main_window = MagicMock()
    with _patch_load_deps():
        handle = sciqlop_sismo.load(main_window)
    assert handle is not None
    main_window.toolsMenu.addAction.assert_called_once()
    main_window.addWidgetIntoDock.assert_not_called()


def test_menu_action_creates_dock_lazily():
    """Triggering the menu action calls addWidgetIntoDock with
    delete_on_close=True so the dock tabs into welcome's area and is
    properly reaped when closed."""
    sciqlop_sismo._LOADED.clear()
    main_window = MagicMock()
    with _patch_load_deps():
        sciqlop_sismo.load(main_window)
        args, _ = main_window.toolsMenu.addAction.call_args
        action_callback = args[1]
        action_callback()
    main_window.addWidgetIntoDock.assert_called_once()
    _args, kwargs = main_window.addWidgetIntoDock.call_args
    assert kwargs.get("delete_on_close") is True


def test_load_idempotent():
    sciqlop_sismo._LOADED.clear()
    main_window = MagicMock()
    with _patch_load_deps():
        h1 = sciqlop_sismo.load(main_window)
        h2 = sciqlop_sismo.load(main_window)
    assert h1 is h2
    main_window.toolsMenu.addAction.assert_called_once()
