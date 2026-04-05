import PySide6QtAds as QtAds
from PySide6.QtGui import QIcon
from .workbench import CdfWorkbenchPanel


def load(main_window):
    panel = CdfWorkbenchPanel(main_window=main_window)
    panel.setWindowTitle("CDF Workbench")

    main_window.addWidgetIntoDock(
        QtAds.DockWidgetArea.TopDockWidgetArea, panel
    )

    # The dock widget is created by addWidgetIntoDock — find it to hide initially
    dock_widget = main_window.dock_manager.findDockWidget("CDF Workbench")
    if dock_widget:
        dock_widget.toggleView(False)
        toggle_action = dock_widget.toggleViewAction()
        toggle_action.setIcon(QIcon.fromTheme("document-open"))
        main_window.toolBar.addAction(toggle_action)

    main_window.toolsMenu.addAction("CDF Workbench", panel.show)

    return panel
