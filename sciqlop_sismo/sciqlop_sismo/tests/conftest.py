"""Local conftest: stub Qt-only imports + atexit segfault workaround.

The root conftest already stubs PySide6 modules for tests that don't
need a real Qt environment. We add the os._exit workaround per
`feedback_sciqlopplots_exit_segfault` so pytest doesn't segfault on
exit when SciQLopPlots has been imported.
"""
import atexit
import os


def _force_exit():
    os._exit(0)


# Registered last → runs first during interpreter teardown.
atexit.register(_force_exit)
