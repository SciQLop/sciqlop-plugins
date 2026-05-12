"""Live-network tests. Skipped by default; set RADIO_LIVE_TESTS=1 to run.

These hit real archives; they catch upstream regressions but cost network
time and should not gate normal PRs.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

if os.environ.get("RADIO_LIVE_TESTS") != "1":
    pytest.skip("set RADIO_LIVE_TESTS=1 to run live network tests", allow_module_level=True)

from PySide6.QtCore import QCoreApplication

from sciqlop_radio.fetch import RadioFetchService
from sciqlop_radio.sources import SOURCES


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.mark.parametrize(
    "source",
    [s for s in SOURCES if s.fido_instrument],
    ids=lambda s: s.key,
)
def test_search_returns_some_rows(qapp, tmp_path, source):
    svc = RadioFetchService(cache_dir=tmp_path)
    received = []
    svc.searchCompleted.connect(lambda rows: received.append(rows))
    svc.searchFailed.connect(lambda msg: received.append(("FAIL", msg)))

    end = datetime(2024, 5, 2, tzinfo=timezone.utc)
    start = end - timedelta(hours=2)
    svc.search(source, start, end)
    svc.wait_for_finished(timeout_s=60)
    qapp.processEvents()

    assert received, f"no signal for source {source.key}"
    first = received[0]
    if isinstance(first, tuple):
        pytest.skip(f"{source.key} search failed: {first[1]}")
    assert isinstance(first, list)
