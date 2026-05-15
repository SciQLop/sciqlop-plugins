"""sciqlop_sismo — FDSN/ObsPy seismology browser for SciQLop."""
from __future__ import annotations

from typing import Any

__version__ = "0.1.0"

_LOADED: dict[int, Any] = {}


def _import_qtads():
    """Indirection so tests can patch the QtAds import."""
    import PySide6QtAds as QtAds
    return QtAds


def load(main_window):
    """SciQLop entry point.

    Follows SciQLop's plot-panel pattern (`new_native_plot_panel`): the
    dock is NOT created at load time. `load()` only constructs the
    long-lived data layer (the Speasy provider, which auto-registers
    virtual products as channels are added) and registers a tools-menu
    action that builds a fresh dock on demand. Each dock is added via
    `addWidgetIntoDock(..., delete_on_close=True)` so it tabs into
    welcome's area and is fully reaped when the user closes it.
    """
    key = id(main_window)
    if key in _LOADED:
        return _LOADED[key]

    from .provider import SismoProvider

    provider = SismoProvider()
    state: dict[str, Any] = {"dock": None}

    def _open_dock():
        existing = state["dock"]
        if existing is not None:
            dm = getattr(main_window, "dock_manager", None)
            if dm is not None:
                for cdw in dm.dockWidgets():
                    try:
                        if cdw.widget() is existing:
                            cdw.toggleView(True)
                            cdw.raise_()
                            return
                    except RuntimeError:
                        continue
            state["dock"] = None  # stale ref

        from .dock import SismoBrowserDock
        QtAds = _import_qtads()
        dock = SismoBrowserDock(provider=provider)
        dock.setWindowTitle("Sismo")
        main_window.addWidgetIntoDock(
            QtAds.DockWidgetArea.TopDockWidgetArea,
            dock,
            delete_on_close=True,
        )
        state["dock"] = dock
        dock.destroyed.connect(lambda *_: state.update(dock=None))

    main_window.toolsMenu.addAction("Sismo", _open_dock)

    handle = (provider, state)
    _LOADED[key] = handle
    return handle
