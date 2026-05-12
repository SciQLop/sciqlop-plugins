"""Smoke test: the plugin entry point resolves and load() is callable."""
from unittest.mock import MagicMock

import sciqlop_sismo


def test_version_is_set():
    assert sciqlop_sismo.__version__ == "0.1.0"


def test_load_callable_with_mock_main_window():
    main_window = MagicMock()
    result = sciqlop_sismo.load(main_window)
    assert result is None  # Will be a panel after Task 13.


def test_entry_point_resolves():
    from importlib.metadata import entry_points
    eps = entry_points(group="sciqlop.plugins")
    names = {ep.name for ep in eps}
    assert "sciqlop_sismo" in names
