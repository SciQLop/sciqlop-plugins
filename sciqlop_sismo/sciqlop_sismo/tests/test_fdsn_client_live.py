"""Live FDSN tests — disabled by default, run with `pytest -m live`."""
from datetime import datetime, timedelta, timezone

import pytest

from sciqlop_sismo.fdsn_client import fetch_stream, search_stations

pytestmark = pytest.mark.live


def test_live_fetch_iris_anmo():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=30)
    stream = fetch_stream(("IU", "ANMO", "00", "BHZ"), t0, t1, routing="IRIS")
    assert len(stream) >= 1
    assert stream[0].stats.sampling_rate > 0


def test_live_search_stations_iris():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(days=1)
    inv = search_stations(
        network="IU", station="ANMO", location="00", channel="BHZ",
        start_time=t0, end_time=t1, routing="IRIS",
    )
    assert len(inv.networks) >= 1
