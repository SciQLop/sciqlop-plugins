"""sciqlop_radio — heliospheric radio dynamic-spectra browser for SciQLop."""
from __future__ import annotations

__version__ = "0.1.0"

_LOADED_PANELS: dict[int, object] = {}


def load(main_window):
    """SciQLop entry point. Registers the dock + toolbar action (idempotent)."""
    key = id(main_window)
    if key in _LOADED_PANELS:
        return _LOADED_PANELS[key]

    import PySide6QtAds as QtAds  # local import; available only inside SciQLop
    from PySide6.QtGui import QIcon

    from .dock import RadioSpectraDock

    panel = RadioSpectraDock(main_window=main_window)
    panel.setWindowTitle("Radio Spectra")

    main_window.addWidgetIntoDock(
        QtAds.DockWidgetArea.TopDockWidgetArea, panel
    )

    dock_widget = main_window.dock_manager.findDockWidget("Radio Spectra")
    if dock_widget is not None:
        dock_widget.toggleView(False)
        toggle_action = dock_widget.toggleViewAction()
        toggle_action.setIcon(QIcon.fromTheme("network-wireless"))
        main_window.toolBar.addAction(toggle_action)

    def _reveal():
        # Mirrors SciQLop's own `_reveal_agent_dock` pattern: find the
        # wrapping CDockWidget by inner-widget identity, toggle it
        # visible, then raise_() so it comes to the front of the tab
        # stack (otherwise welcome's tab stays in front and the panel
        # appears to "open above" instead of being tabbed).
        dm = getattr(main_window, "dock_manager", None)
        if dm is not None:
            for cdw in dm.dockWidgets():
                try:
                    if cdw.widget() is panel:
                        cdw.toggleView(True)
                        cdw.raise_()
                        return
                except RuntimeError:
                    continue
        panel.show()

    main_window.toolsMenu.addAction("Radio Spectra", _reveal)

    _LOADED_PANELS[key] = panel
    return panel
