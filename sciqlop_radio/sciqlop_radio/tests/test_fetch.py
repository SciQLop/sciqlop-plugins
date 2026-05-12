"""RadioFetchService unit tests — Fido is fully mocked."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def test_search_emits_search_completed(qapp, tmp_path):
    from sciqlop_radio.fetch import RadioFetchService
    from sciqlop_radio.sources import SOURCES

    svc = RadioFetchService(cache_dir=tmp_path)
    received = []

    svc.searchCompleted.connect(lambda rows: received.append(rows))
    svc.searchFailed.connect(lambda msg: received.append(("FAIL", msg)))

    fake_rows = [MagicMock(name=f"row{i}", url=f"https://archive/example_{i}.cdf") for i in range(3)]

    with patch("sciqlop_radio.fetch._do_search", return_value=fake_rows):
        svc.search(
            source=SOURCES[0],
            t_start=datetime(2024, 5, 1, tzinfo=timezone.utc),
            t_end=datetime(2024, 5, 2, tzinfo=timezone.utc),
        )
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()

    assert received, "no signal received"
    assert isinstance(received[0], list)
    assert len(received[0]) == 3


def test_search_failure_emits_search_failed(qapp, tmp_path):
    from sciqlop_radio.fetch import RadioFetchService
    from sciqlop_radio.sources import SOURCES

    svc = RadioFetchService(cache_dir=tmp_path)
    received = []
    svc.searchCompleted.connect(lambda rows: received.append(("OK", rows)))
    svc.searchFailed.connect(lambda msg: received.append(("FAIL", msg)))

    with patch("sciqlop_radio.fetch._do_search", side_effect=RuntimeError("boom")):
        svc.search(
            source=SOURCES[0],
            t_start=datetime(2024, 5, 1, tzinfo=timezone.utc),
            t_end=datetime(2024, 5, 2, tzinfo=timezone.utc),
        )
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()

    assert received and received[0][0] == "FAIL"
    assert "boom" in received[0][1]


def test_fetch_uses_cache_hit(qapp, tmp_path):
    from sciqlop_radio.fetch import RadioFetchService

    cached = tmp_path / "example_0.cdf"
    cached.write_bytes(b"\x00" * 16)

    svc = RadioFetchService(cache_dir=tmp_path)

    received = []
    svc.fetchCompleted.connect(lambda ok, failed: received.append((list(ok), list(failed))))

    row = MagicMock()
    row.url = "https://archive/example_0.cdf"

    with patch("sciqlop_radio.fetch._do_fetch") as fido_fetch:
        svc.fetch([row])
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()
        fido_fetch.assert_not_called()

    assert received
    ok, failed = received[0]
    assert cached in ok
    assert not failed
