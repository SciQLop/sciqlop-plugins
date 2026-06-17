"""Local conftest: undo root-conftest PySide6 stubbing if a real install exists,
stub SciQLop's user_api so VP registration never imports the real (Qt-global,
QApplication-requiring) backend, and isolate Speasy's disk cache per test run.

Without the SciQLop stub, `provider.add_channel` -> `_register_virtual_products`
imports `SciQLop.user_api.virtual_products`, which on a machine with a real
SciQLop install pulls in Qt global state with no QApplication and SIGABRTs
before the `except ImportError` guard can help.
"""
import atexit
import importlib
import os
import sys
import tempfile
from unittest.mock import MagicMock

# Must precede any speasy import: the cache singleton reads SPEASY_CACHE_PATH at
# import time. A fresh tempdir keeps the fragment cache from leaking across runs.
os.environ.setdefault(
    "SPEASY_CACHE_PATH", tempfile.mkdtemp(prefix="sciqlop_sismo_cache_")
)

import pytest


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


# Stub the SciQLop modules the provider imports lazily. MagicMock auto-provides
# `create_virtual_product` / `VirtualProductType`, so registration is a no-op.
for _name in ("SciQLop", "SciQLop.user_api", "SciQLop.user_api.virtual_products"):
    sys.modules.setdefault(_name, MagicMock())


@pytest.fixture(autouse=True)
def _isolate_speasy_cache():
    """Drop all Speasy cache entries before each test so range-aware fragment
    caching can't leak fetch counts from one test into another."""
    import re

    from speasy.core.cache import drop_matching_entries

    drop_matching_entries(re.compile(".*"))
    yield
