"""Range-aware caching of the raw FDSN fetch via Speasy's @Cacheable.

The expensive operation is the network waveform fetch. It is cached once per
channel (NSLC), keyed on the dataset uid — kind-independent — so the three
derived products (raw / waveform / spectrogram) of one channel share a single
fetch, and re-visiting a time window never re-hits the network.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime
from speasy.products.variable import SpeasyVariable

from sciqlop_sismo.provider import SismoProvider


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIQLOP_SISMO_INVENTORY_DIR", str(tmp_path))
    p = SismoProvider()
    p.add_channel(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    return p


@pytest.fixture
def fake_stream():
    tr = Trace(
        data=np.linspace(0, 1, 1000, dtype=np.float64),
        header={
            "network": "G", "station": "SSB", "location": "00",
            "channel": "HHZ", "sampling_rate": 100.0,
            "starttime": UTCDateTime("2026-01-01T00:00:00"),
        },
    )
    return Stream([tr])


def test_second_call_same_window_hits_cache(provider, fake_stream):
    uid = "G/SSB/00.HHZ/waveform"
    with patch("sciqlop_sismo.worker.fetch_stream", return_value=fake_stream) as fs:
        v1 = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
        v2 = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    assert isinstance(v1, SpeasyVariable) and isinstance(v2, SpeasyVariable)
    assert fs.call_count == 1, f"second call must hit cache; fetched {fs.call_count}x"


def test_three_kinds_of_one_channel_share_one_fetch(provider, fake_stream):
    with patch("sciqlop_sismo.worker.fetch_stream", return_value=fake_stream) as fs:
        provider.get_data("G/SSB/00.HHZ/raw", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
        provider.get_data("G/SSB/00.HHZ/waveform", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
        provider.get_data("G/SSB/00.HHZ/spectrogram", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    assert fs.call_count == 1, (
        f"raw/waveform/spectrogram must share one cached fetch; fetched {fs.call_count}x"
    )


def test_no_data_window_returns_none_without_raising(provider):
    from obspy.clients.fdsn.header import FDSNNoDataException

    uid = "G/SSB/00.HHZ/waveform"
    with patch("sciqlop_sismo.worker.fetch_stream",
               side_effect=FDSNNoDataException("no data")):
        var = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    assert var is None


def test_cache_still_returns_correct_units_and_shape(provider, fake_stream):
    with patch("sciqlop_sismo.worker.fetch_stream", return_value=fake_stream):
        raw = provider.get_data("G/SSB/00.HHZ/raw", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
        wf = provider.get_data("G/SSB/00.HHZ/waveform", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
        spec = provider.get_data("G/SSB/00.HHZ/spectrogram", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    assert raw.unit == "counts" and raw.values.shape[0] == 1000
    assert wf.unit == "m/s" and wf.values.shape[0] == 1000
    assert spec.values.ndim == 2


def test_raw_cache_key_folds_routing_in_but_not_kind():
    """The shared cache key separates routings but unites the three kinds."""
    from sciqlop_sismo.worker import raw_cache_key

    uid = "G/SSB/00.HHZ"
    assert raw_cache_key(uid, "iris-federator") == raw_cache_key(uid, "iris-federator")
    assert raw_cache_key(uid, "iris-federator") != raw_cache_key(uid, "eida-routing")


def test_routing_change_refetches_instead_of_serving_old_route(provider):
    """Same routing shares one fetch; a changed routing refetches fresh data."""
    from obspy import Trace
    from obspy import UTCDateTime as _UTC

    def stream_with(value):
        return Stream(
            [
                Trace(
                    data=np.full(1000, value, dtype=np.float64),
                    header={
                        "network": "G",
                        "station": "SSB",
                        "location": "00",
                        "channel": "HHZ",
                        "sampling_rate": 100.0,
                        "starttime": _UTC("2026-01-01T00:00:00"),
                    },
                )
            ]
        )

    seen_routings = []

    def fake_fetch(nslc, start, stop, routing="iris-federator", **kwargs):
        seen_routings.append(routing)
        return stream_with(1.0 if routing == "iris-federator" else 2.0)

    t0, t1 = _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1)
    with patch("sciqlop_sismo.worker.fetch_stream", side_effect=fake_fetch):
        raw = provider.get_data("G/SSB/00.HHZ/raw", t0, t1)
        wf = provider.get_data("G/SSB/00.HHZ/waveform", t0, t1)
        assert seen_routings == ["iris-federator"], seen_routings
        assert float(np.asarray(raw.values).mean()) == 1.0

        provider.add_channel(
            network="G",
            station="SSB",
            location="00",
            channel="HHZ",
            start_date=_utc(2020, 1, 1),
            stop_date=_utc(2030, 1, 1),
            sampling_rate_hz=100.0,
            routing="eida-routing",
        )
        raw2 = provider.get_data("G/SSB/00.HHZ/raw", t0, t1)
        assert seen_routings == ["iris-federator", "eida-routing"], seen_routings
        assert float(np.asarray(raw2.values).mean()) == 2.0
        wf_units = wf.unit
    assert wf_units == "m/s"


def _get_in_other_thread(provider, uid, t0, t1, timeout_s=5.0):
    import threading

    result = {}
    worker = threading.Thread(
        target=lambda: result.setdefault("var", provider.get_data(uid, t0, t1)), daemon=True
    )
    worker.start()
    worker.join(timeout_s)
    assert not worker.is_alive(), "request on a known-empty window hung on a stale fragment lock"
    return result["var"]


def test_no_data_window_is_cached_as_empty_and_never_blocks_other_threads(provider):
    from obspy.clients.fdsn.header import FDSNNoDataException

    uid = "G/SSB/00.HHZ/waveform"
    t0, t1 = _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 30)
    with patch("sciqlop_sismo.worker.fetch_stream",
               side_effect=FDSNNoDataException("no data")) as fs:
        assert provider.get_data(uid, t0, t1) is None
        assert _get_in_other_thread(provider, uid, t0, t1) is None
    assert fs.call_count == 1, f"a known gap must be cached; fetched {fs.call_count}x"


def test_recent_window_is_not_frozen_in_cache(provider, fake_stream):
    """Archives lag real time: a window near now may still be filling in, so it
    must be refetched rather than cached forever (incl. not-yet-existing hours)."""
    from datetime import timedelta

    uid = "G/SSB/00.HHZ/raw"
    t1 = datetime.now(tz=timezone.utc) - timedelta(minutes=10)
    t0 = t1 - timedelta(minutes=5)
    with patch("sciqlop_sismo.worker.fetch_stream", return_value=fake_stream) as fs:
        provider.get_data(uid, t0, t1)
        provider.get_data(uid, t0, t1)
    assert fs.call_count == 2, f"recent window must not be cached; fetched {fs.call_count}x"


def test_window_spanning_data_and_cached_gap_merges(provider, fake_stream):
    from obspy.clients.fdsn.header import FDSNNoDataException

    uid = "G/SSB/00.HHZ/raw"
    with patch("sciqlop_sismo.worker.fetch_stream", return_value=fake_stream):
        provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    with patch("sciqlop_sismo.worker.fetch_stream",
               side_effect=FDSNNoDataException("no data")):
        provider.get_data(uid, _utc(2026, 1, 1, 3), _utc(2026, 1, 1, 4))
    with patch("sciqlop_sismo.worker.fetch_stream",
               side_effect=FDSNNoDataException("no data")):
        var = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 4))
    assert var.values.shape[0] == 1000


def test_is_settled_accounts_for_speasy_padding():
    from datetime import timedelta

    from sciqlop_sismo.worker import is_settled

    now = _utc(2026, 1, 10, 12)
    assert is_settled(now - timedelta(days=2), now - timedelta(days=1), now)
    assert not is_settled(now - timedelta(hours=1), now - timedelta(minutes=30), now)
    # a day-long window ending 3h ago: Speasy's margin pads it into the future
    assert not is_settled(now - timedelta(hours=27), now - timedelta(hours=3), now)
