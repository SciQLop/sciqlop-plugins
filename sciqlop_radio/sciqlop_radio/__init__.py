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
        # Tools-menu action MUST act on the CDockWidget (toggleView), not on
        # the inner QWidget — `panel.show()` on the inner widget makes QtAds
        # re-dock it in a fresh area on top of welcome instead of restoring
        # the original tabbed location.
        main_window.toolsMenu.addAction(
            "Radio Spectra", lambda: dock_widget.toggleView(True)
        )
    else:
        main_window.toolsMenu.addAction("Radio Spectra", panel.show)

    _LOADED_PANELS[key] = panel
    return panel
