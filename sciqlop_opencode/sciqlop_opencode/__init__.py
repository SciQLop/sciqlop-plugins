"""Opencode backend plugin for SciQLop's generic agent chat dock.

Registers `OpencodeBackend` with the shared agent registry and makes
sure the chat dock exists. The dock itself lives in SciQLop core and
is shared with any other agent backend plugins that get installed.
"""
from pathlib import Path

import PySide6QtAds as QtAds
from PySide6.QtGui import QIcon

from SciQLop.components.agents import ensure_agent_dock, register_agent_backend
from SciQLop.components.theming.icons import register_icon, theme_adapted_icon

from .backend import OpencodeBackend, fetch_models

_ICON_NAME = "sciqlop_opencode_chat"
_ICON_PATH = str(Path(__file__).parent / "resources" / "chat.svg")
_DOCK_TITLE = "Agents"


def load(main_window):
    register_icon(_ICON_NAME, lambda: QIcon(_ICON_PATH))
    icon = theme_adapted_icon(_ICON_NAME)

    models = fetch_models()
    if models:
        OpencodeBackend.model_choices = models

    register_agent_backend(OpencodeBackend)
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

    # The "Agent Chat" entry in the Tools menu is added by
    # SciQLop.components.agents.ensure_agent_dock (idempotent) so multiple
    # backend plugins don't produce duplicate entries.

    return dock
