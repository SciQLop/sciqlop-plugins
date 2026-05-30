"""Opencode backend plugin for SciQLop's generic agent chat dock.

Registers `OpencodeBackend` with the shared agent registry and makes sure the
shared chat dock exists. All chat UI (the docked panel, its toolbar button and
icon, the Tools-menu entry) is owned by SciQLop core — this plugin contributes
only a backend.
"""
from SciQLop.components.agents import ensure_agent_dock, register_agent_backend

from .backend import OpencodeBackend, fetch_models


def load(main_window):
    models = fetch_models()
    if models:
        OpencodeBackend.model_choices = models

    register_agent_backend(OpencodeBackend)
    return ensure_agent_dock(main_window)
