"""Load-entrypoint smoke test against a stubbed main_window.

RadioSpectraDock is patched out so no real QApplication is needed —
the test verifies the wiring logic of load(), not the dock widget itself.
"""
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(autouse=True)
def _clear_loaded_panels():
    """Reset the idempotency cache between tests."""
    import sciqlop_radio
    sciqlop_radio._LOADED_PANELS.clear()
    yield
    sciqlop_radio._LOADED_PANELS.clear()


def test_load_registers_dock_and_action():
    from sciqlop_radio import load

    main = MagicMock()
    with patch("sciqlop_radio.dock.RadioSpectraDock") as MockDock:
        panel = load(main)
    assert panel is not None
    main.addWidgetIntoDock.assert_called_once()
    main.toolsMenu.addAction.assert_called_once()


def test_load_is_idempotent():
    """Calling load twice must not register two toolsMenu entries."""
    from sciqlop_radio import load

    main = MagicMock()
    with patch("sciqlop_radio.dock.RadioSpectraDock"):
        load(main)
        first_call_count = main.toolsMenu.addAction.call_count

        load(main)
        assert main.toolsMenu.addAction.call_count == first_call_count
