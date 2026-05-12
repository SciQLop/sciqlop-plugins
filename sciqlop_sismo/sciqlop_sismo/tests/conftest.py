"""Local conftest: undo root-conftest PySide6 stubbing if a real install exists.

Also adds the os._exit workaround for SciQLopPlots' exit segfault.
"""
import atexit
import importlib
import os
import sys


def _force_exit():
    os._exit(0)


atexit.register(_force_exit)


def _restore_real_pyside():
    try:
        for mod_name in list(sys.modules.keys()):
            if mod_name.startswith("PySide6"):
                sys.modules.pop(mod_name, None)
        importlib.import_module("PySide6.QtWidgets")
    except ImportError:
        # No real PySide6 — leave stubs in place; Qt tests will skip on use.
        pass


_restore_real_pyside()
