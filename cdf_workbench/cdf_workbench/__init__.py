import PySide6QtAds as QtAds
from PySide6.QtGui import QIcon
from .workbench import CdfWorkbenchPanel


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
    panel = CdfWorkbenchPanel(main_window=main_window)
    panel.setWindowTitle("CDF Workbench")

    main_window.addWidgetIntoDock(
        QtAds.DockWidgetArea.TopDockWidgetArea, panel,
        area=_find_central_area(main_window),
    )

    # The dock widget is created by addWidgetIntoDock — find it to hide initially
    dock_widget = main_window.dock_manager.findDockWidget("CDF Workbench")
    if dock_widget:
        dock_widget.toggleView(False)
        toggle_action = dock_widget.toggleViewAction()
        toggle_action.setIcon(QIcon.fromTheme("document-open"))
        # Same QtAds-managed action for both toolbar and tools menu so the
        # dock toggles back to its tabbed-with-welcome state (calling
        # `panel.show()` on the inner widget bypasses QtAds and the dock
        # pops in a new area on top).
        main_window.toolBar.addAction(toggle_action)
        main_window.toolsMenu.addAction(toggle_action)
    else:
        main_window.toolsMenu.addAction("CDF Workbench", panel.show)

    return panel
