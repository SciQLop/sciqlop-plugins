"""Opencode backend plugin for SciQLop's generic agent chat dock.

Registers `OpencodeBackend` with the shared agent registry and makes
sure the chat dock exists. The dock itself lives in SciQLop core and
is shared with any other agent backend plugins that get installed.
"""

def load(main_window):
    # Wired up in Task 9. Keeps the package importable for now.
    return None
