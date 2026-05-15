"""sciqlop_sismo — FDSN/ObsPy seismology browser for SciQLop."""
from __future__ import annotations

from typing import Any

__version__ = "0.1.0"

_LOADED_PANELS: dict[int, Any] = {}


def _import_qtads():
    """Indirection so tests can patch the QtAds import."""
    import PySide6QtAds as QtAds
    return QtAds


def load(main_window):
    """SciQLop entry point. Registers the dock + toolbar action (idempotent)."""
    key = id(main_window)
    if key in _LOADED_PANELS:
        return _LOADED_PANELS[key]

    from PySide6.QtGui import QIcon

    from .dock import SismoBrowserDock
    from .provider import SismoProvider

    QtAds = _import_qtads()

    provider = SismoProvider()
    dock = SismoBrowserDock(provider=provider)
    dock.setWindowTitle("Sismo")

    main_window.addWidgetIntoDock(QtAds.DockWidgetArea.TopDockWidgetArea, dock)

    dock_widget = main_window.dock_manager.findDockWidget("Sismo")
    if dock_widget is not None:
        dock_widget.toggleView(False)
        toggle_action = dock_widget.toggleViewAction()
        toggle_action.setIcon(QIcon.fromTheme("applications-science"))
        main_window.toolBar.addAction(toggle_action)

    def _reveal():
        # Mirrors SciQLop's own `_reveal_agent_dock` pattern: find the
        # wrapping CDockWidget by inner-widget identity (more robust than
        # by title), toggle it visible, then raise_() so it actually
        # comes to the front of the tab stack (otherwise the welcome tab
        # stays in front and the dock appears to "open above" it).
        dm = getattr(main_window, "dock_manager", None)
        if dm is not None:
            for cdw in dm.dockWidgets():
                try:
                    if cdw.widget() is dock:
                        cdw.toggleView(True)
                        cdw.raise_()
                        return
                except RuntimeError:
                    continue
        dock.show()

    main_window.toolsMenu.addAction("Sismo", _reveal)

    handle = (provider, dock)
    _LOADED_PANELS[key] = handle
    return handle
