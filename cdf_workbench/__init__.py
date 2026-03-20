import PySide6QtAds as QtAds
from .workbench import CdfWorkbenchPanel


def load(main_window):
    panel = CdfWorkbenchPanel(main_window=main_window)
    # Register as a dock widget in SciQLop's central area
    main_window.addWidgetIntoDock(
        QtAds.DockWidgetArea.TopDockWidgetArea, panel
    )
    main_window.toolsMenu.addAction("CDF Workbench", panel.show)
    return panel
