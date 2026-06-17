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
    with patch("sciqlop_sismo.provider.fetch_stream", return_value=fake_stream) as fs:
        v1 = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
        v2 = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    assert isinstance(v1, SpeasyVariable) and isinstance(v2, SpeasyVariable)
    assert fs.call_count == 1, f"second call must hit cache; fetched {fs.call_count}x"


def test_three_kinds_of_one_channel_share_one_fetch(provider, fake_stream):
    with patch("sciqlop_sismo.provider.fetch_stream", return_value=fake_stream) as fs:
        provider.get_data("G/SSB/00.HHZ/raw", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
        provider.get_data("G/SSB/00.HHZ/waveform", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
        provider.get_data("G/SSB/00.HHZ/spectrogram", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    assert fs.call_count == 1, (
        f"raw/waveform/spectrogram must share one cached fetch; fetched {fs.call_count}x"
    )


def test_no_data_window_returns_none_without_raising(provider):
    from obspy.clients.fdsn.header import FDSNNoDataException

    uid = "G/SSB/00.HHZ/waveform"
    with patch("sciqlop_sismo.provider.fetch_stream",
               side_effect=FDSNNoDataException("no data")):
        var = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    assert var is None


def test_cache_still_returns_correct_units_and_shape(provider, fake_stream):
    with patch("sciqlop_sismo.provider.fetch_stream", return_value=fake_stream):
        raw = provider.get_data("G/SSB/00.HHZ/raw", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
        wf = provider.get_data("G/SSB/00.HHZ/waveform", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
        spec = provider.get_data("G/SSB/00.HHZ/spectrogram", _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    assert raw.unit == "counts" and raw.values.shape[0] == 1000
    assert wf.unit == "m/s" and wf.values.shape[0] == 1000
    assert spec.values.ndim == 2
