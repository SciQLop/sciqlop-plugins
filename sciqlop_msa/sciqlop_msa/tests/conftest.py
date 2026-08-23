"""Test fixtures for sciqlop_msa's moments-fit tests.

Stubs SciQLop.user_api.virtual_products so moments_vp.register_moments_vps() can
be unit-tested without a real SciQLop/Qt install (mirrors the sciqlop_sismo /
sciqlop_radio pattern) and isolates Speasy's disk cache per test run.
"""
import atexit
import os
import sys
import tempfile
from unittest.mock import MagicMock

# Must precede any speasy import: the cache singleton reads SPEASY_CACHE_PATH at
# import time. A fresh tempdir keeps the fragment cache from leaking across runs.
os.environ.setdefault(
    "SPEASY_CACHE_PATH", tempfile.mkdtemp(prefix="sciqlop_msa_cache_")
)

import pytest


def _force_exit():
    os._exit(0)


atexit.register(_force_exit)

for _name in ("SciQLop", "SciQLop.user_api", "SciQLop.user_api.virtual_products"):
    sys.modules.setdefault(_name, MagicMock())


@pytest.fixture(autouse=True)
def _isolate_speasy_cache():
    """Drop all Speasy cache entries before each test so the day-bucketed fit
    cache can't leak hits from one test into another."""
    import re

    from speasy.core.cache import drop_matching_entries

    drop_matching_entries(re.compile(".*"))
    yield
