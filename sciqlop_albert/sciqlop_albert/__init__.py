"""Albert (DINUM/Etalab) backend plugin for SciQLop's agent chat dock."""
from pathlib import Path

import PySide6QtAds as QtAds
from PySide6.QtGui import QIcon

from SciQLop.components.agents import ensure_agent_dock, register_agent_backend
from SciQLop.components.theming.icons import register_icon, theme_adapted_icon

from .backend import AlbertBackend, fetch_models

_ICON_NAME = "sciqlop_albert_chat"
_ICON_PATH = str(Path(__file__).parent / "resources" / "chat.svg")
_DOCK_TITLE = "Agents"


def load(main_window):
    register_icon(_ICON_NAME, lambda: QIcon(_ICON_PATH))
    icon = theme_adapted_icon(_ICON_NAME)

    # Populate model dropdown from the Albert API (sync, quick)
    models = fetch_models()
    if models:
        AlbertBackend.model_choices = models

    register_agent_backend(AlbertBackend)
    dock = ensure_agent_dock(main_window)
    dock.setWindowTitle(_DOCK_TITLE)
    dock.setWindowIcon(icon)

    dock_widget = main_window.dock_manager.findDockWidget(_DOCK_TITLE)
    if dock_widget is None:
        main_window.addWidgetIntoDock(QtAds.DockWidgetArea.RightDockWidgetArea, dock)
        dock_widget = main_window.dock_manager.findDockWidget(_DOCK_TITLE)
        if dock_widget:
            dock_widget.setIcon(icon)
            dock_widget.toggleView(False)
            toggle_action = dock_widget.toggleViewAction()
            toggle_action.setIcon(icon)
            main_window.toolBar.addAction(toggle_action)

    main_window.toolsMenu.addAction(icon, "Agent Chat", dock.show)

    return dock
