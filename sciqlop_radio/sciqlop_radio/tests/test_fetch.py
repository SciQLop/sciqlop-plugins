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


def test_format_time_for_fido_strips_timezone():
    """astropy.time.Time's isot parser rejects '+00:00' suffix; the helper
    must hand it a naive-UTC ISO string."""
    from sciqlop_radio.fetch import _format_time_for_fido

    aware = datetime(2024, 5, 1, 12, 30, 45, tzinfo=timezone.utc)
    assert _format_time_for_fido(aware) == "2024-05-01T12:30:45"

    naive = datetime(2024, 5, 1, 12, 30, 45)
    assert _format_time_for_fido(naive) == "2024-05-01T12:30:45"


def test_format_time_for_fido_converts_non_utc_offset():
    """Aware datetimes in another timezone get converted to UTC before format."""
    from datetime import timezone as tz, timedelta
    from sciqlop_radio.fetch import _format_time_for_fido

    paris = datetime(2024, 5, 1, 14, 30, 0, tzinfo=tz(timedelta(hours=2)))
    assert _format_time_for_fido(paris) == "2024-05-01T12:30:00"


def test_format_time_for_fido_output_parses_with_astropy():
    """Regression guard for the actual bug: astropy.time.Time must accept the output."""
    pytest.importorskip("astropy")
    from astropy.time import Time

    from sciqlop_radio.fetch import _format_time_for_fido

    aware = datetime(2024, 5, 1, tzinfo=timezone.utc)
    Time(_format_time_for_fido(aware))  # must not raise


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
