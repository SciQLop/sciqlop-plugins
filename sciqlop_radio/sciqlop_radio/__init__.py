"""sciqlop_radio — heliospheric radio dynamic-spectra browser for SciQLop."""
from __future__ import annotations

__version__ = "0.1.0"

_LOADED_PANELS: dict[int, object] = {}


def _find_central_area(main_window):
    """Return the CDockAreaWidget our dock should tab into.

    `addWidgetIntoDock(area=None)` defers to `main_window._find_biggest_area()`,
    which gates on `area.isVisible()`. At plugin load time welcome's area has
    been added but not yet laid out, so the visibility check returns False
    and the new dock lands in a fresh area above welcome. Resolve the target
    ourselves and pass it explicitly to side-step that timing.
    """
    biggest = getattr(main_window, "_find_biggest_area", lambda: None)()
    if biggest is not None:
        return biggest
    dm = getattr(main_window, "dock_manager", None)
    if dm is not None:
        welcome = dm.findDockWidget("Welcome")
        if welcome is not None:
            return welcome.dockAreaWidget()
    return None


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
        QtAds.DockWidgetArea.TopDockWidgetArea, panel,
        area=_find_central_area(main_window),
    )

    dock_widget = main_window.dock_manager.findDockWidget("Radio Spectra")
    if dock_widget is not None:
        dock_widget.toggleView(False)
        toggle_action = dock_widget.toggleViewAction()
        toggle_action.setIcon(QIcon.fromTheme("network-wireless"))
        # Same QtAds-managed action for both toolbar and tools menu so the
        # dock toggles back to its tabbed-with-welcome state (calling
        # `panel.show()` on the inner widget OR `toggleView()` ourselves
        # bypasses QtAds and the dock pops in a new area on top).
        main_window.toolBar.addAction(toggle_action)
        main_window.toolsMenu.addAction(toggle_action)
    else:
        main_window.toolsMenu.addAction("Radio Spectra", panel.show)

    _LOADED_PANELS[key] = panel
    return panel
