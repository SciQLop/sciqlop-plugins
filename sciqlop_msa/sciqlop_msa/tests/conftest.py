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
# import time. A STABLE (not freshly-generated) path so the remote-provider
# inventory cache warms up once and is reused across runs — a fresh mkdtemp()
# here forces a ~5 minute cold `import speasy` every single test invocation
# (290s cold vs 7.8s warm, measured). Per-test isolation is handled instead by
# _isolate_speasy_cache below, scoped to just this plugin's own cache keys.
os.environ.setdefault(
    "SPEASY_CACHE_PATH", os.path.join(tempfile.gettempdir(), "sciqlop_msa_test_cache")
)

import pytest


@pytest.fixture(autouse=True, scope="session")
def _prevent_exit_segfault(request):
    """Upstream SciQLopPlots/pytest interaction segfaults on interpreter exit
    (see feedback_sciqlopplots_exit_segfault.md); os._exit sidesteps it. Exit
    code must still reflect whether the session actually failed, or `pytest -x`
    failures get silently reported as EXIT=0."""

    def _force_exit():
        os._exit(1 if request.session.testsfailed else 0)

    atexit.register(_force_exit)
    yield


for _name in ("SciQLop", "SciQLop.user_api", "SciQLop.user_api.virtual_products"):
    sys.modules.setdefault(_name, MagicMock())


@pytest.fixture(autouse=True)
def _isolate_speasy_cache():
    """Drop this plugin's own Speasy cache entries before each test so the
    day-bucketed fit cache can't leak hits from one test into another.

    Scoped to moments_compute's fit-day CacheCall entries (verified prefix:
    "__internal__/CacheCall/sciqlop_msa.moments_compute/..." — CacheCall's
    is_pure=True prefix is f"{function.__module__}/{function.__qualname__}")
    rather than a blanket ".*": SPEASY_CACHE_PATH is now a stable, reused
    directory (see above), so a blanket wipe would nuke unrelated cache
    entries — including a developer's real cache, if SPEASY_CACHE_PATH
    already pointed at one via setdefault.
    """
    import re

    from speasy.core.cache import drop_matching_entries

    drop_matching_entries(re.compile(r"^__internal__/CacheCall/sciqlop_msa\.moments_compute/"))
    yield
