"""Albert (DINUM/Etalab) backend plugin for SciQLop's agent chat dock.

Registers `AlbertBackend` with the shared agent registry and makes sure the
shared chat dock exists. All chat UI (the docked panel, its toolbar button and
icon, the Tools-menu entry) is owned by SciQLop core — this plugin contributes
only a backend.
"""
from SciQLop.components.agents import ensure_agent_dock, register_agent_backend

from .backend import AlbertBackend, fetch_models


def load(main_window):
    # Populate model dropdown from the Albert API (sync, quick)
    models = fetch_models()
    if models:
        AlbertBackend.model_choices = models

    register_agent_backend(AlbertBackend)
    return ensure_agent_dock(main_window)
