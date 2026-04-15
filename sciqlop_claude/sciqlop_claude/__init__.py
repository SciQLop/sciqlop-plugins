"""Claude backend plugin for SciQLop's generic agent chat dock.

Registers `ClaudeBackend` with the shared agent registry and makes sure
the chat dock exists. The dock itself lives in SciQLop core and is
shared with any other agent backend plugins that get installed.
"""
from pathlib import Path

import PySide6QtAds as QtAds
from PySide6.QtGui import QIcon

from SciQLop.components.agents import ensure_agent_dock, register_agent_backend
from SciQLop.components.theming.icons import register_icon, theme_adapted_icon

from .backend import ClaudeBackend

_ICON_NAME = "sciqlop_claude_chat"
_ICON_PATH = str(Path(__file__).parent / "resources" / "chat.svg")
_DOCK_TITLE = "Agents"


def load(main_window):
    register_icon(_ICON_NAME, lambda: QIcon(_ICON_PATH))
    icon = theme_adapted_icon(_ICON_NAME)

    register_agent_backend(ClaudeBackend)
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
