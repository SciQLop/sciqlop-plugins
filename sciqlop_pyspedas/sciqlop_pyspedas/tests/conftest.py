"""Isolate Speasy's disk cache per run and stub SciQLop so registration
never pulls Qt global state into the test process."""
import os
import sys
import tempfile
from unittest.mock import MagicMock

# Must precede any speasy import: the cache singleton reads SPEASY_CACHE_PATH at import time.
os.environ.setdefault("SPEASY_CACHE_PATH", tempfile.mkdtemp(prefix="sciqlop_pyspedas_cache_"))

import pytest

for _name in ("SciQLop", "SciQLop.user_api", "SciQLop.user_api.virtual_products",
              "SciQLop.components", "SciQLop.components.plotting",
              "SciQLop.components.plotting.backend",
              "SciQLop.components.plotting.backend.easy_provider",
              "SciQLop.core", "SciQLop.core.plot_hints"):
    sys.modules.setdefault(_name, MagicMock())


@pytest.fixture(autouse=True)
def _isolate_caches():
    import re

    from speasy.core.cache import drop_matching_entries

    from sciqlop_pyspedas import worker

    drop_matching_entries(re.compile(".*"))
    worker.compute_all.cache_clear()
    yield
