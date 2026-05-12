"""Tests for sciqlop_sismo.provider — Speasy DataProvider integration."""
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime
from speasy.products.variable import SpeasyVariable

from sciqlop_sismo.provider import SismoProvider
from sciqlop_sismo.local_files import ChannelInfo


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIQLOP_SISMO_INVENTORY_DIR", str(tmp_path))
    p = SismoProvider()
    yield p


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


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def test_provider_registers_under_sismo_name(provider):
    assert provider.provider_name == "sismo"


def test_initial_inventory_has_no_channels(provider):
    tree = provider.flat_inventory
    assert len(tree.parameters) == 0


def test_add_channel_creates_dataset_and_three_parameters(provider):
    provider.add_channel(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    flat = provider.flat_inventory
    chan_params = [
        uid for uid in flat.parameters
        if uid.startswith("sismo/G/SSB/00.HHZ/")
    ]
    assert set(p.rsplit("/", 1)[-1] for p in chan_params) == {
        "waveform", "raw", "spectrogram",
    }
    assert "sismo/G/SSB/00.HHZ" in flat.datasets


def test_add_channel_idempotent(provider):
    kw = dict(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    provider.add_channel(**kw)
    provider.add_channel(**kw)
    flat = provider.flat_inventory
    waveforms = [uid for uid in flat.parameters if uid.endswith("/waveform")]
    assert len(waveforms) == 1


def test_remove_channel_deletes_dataset(provider):
    provider.add_channel(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    provider.remove_channel("G", "SSB", "00", "HHZ")
    flat = provider.flat_inventory
    assert "sismo/G/SSB/00.HHZ" not in flat.datasets


def test_get_data_waveform_dispatches_through_fetch_and_pipeline(provider, fake_stream):
    provider.add_channel(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    uid = "sismo/G/SSB/00.HHZ/waveform"
    with patch("sciqlop_sismo.provider.fetch_stream", return_value=fake_stream) as fs:
        var = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    fs.assert_called_once()
    assert isinstance(var, SpeasyVariable)
    assert var.unit == "m/s"
    assert var.values.shape[0] == 1000


def test_get_data_raw_skips_pipeline(provider, fake_stream):
    provider.add_channel(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    uid = "sismo/G/SSB/00.HHZ/raw"
    with patch("sciqlop_sismo.provider.fetch_stream", return_value=fake_stream):
        var = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    assert var.unit == "counts"


def test_get_data_spectrogram_returns_2d_variable(provider, fake_stream):
    provider.add_channel(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    uid = "sismo/G/SSB/00.HHZ/spectrogram"
    with patch("sciqlop_sismo.provider.fetch_stream", return_value=fake_stream):
        var = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    assert var.values.ndim == 2


def test_get_data_for_local_file_reads_file_instead_of_fdsn(provider, tmp_path):
    from obspy import Trace, Stream as ObsPyStream, UTCDateTime
    fp = tmp_path / "local.mseed"
    Trace(
        data=np.linspace(0, 1, 500, dtype=np.float32),
        header={
            "network": "XX", "station": "LOC", "location": "00",
            "channel": "HHZ", "sampling_rate": 100.0,
            "starttime": UTCDateTime("2026-01-01T00:00:00"),
        },
    ).write(str(fp), format="MSEED")

    from sciqlop_sismo.local_files import import_file
    info = import_file(fp)[0]
    provider.add_channel_from_local(info)

    uid = "sismo/XX/LOC/00.HHZ/waveform"
    with patch("sciqlop_sismo.provider.fetch_stream") as fs:
        var = provider.get_data(uid, _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1))
    fs.assert_not_called()
    assert var.values.shape[0] == 500


def test_inventory_persisted_to_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIQLOP_SISMO_INVENTORY_DIR", str(tmp_path))
    p1 = SismoProvider()
    p1.add_channel(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    p2 = SismoProvider()
    assert "sismo/G/SSB/00.HHZ" in p2.flat_inventory.datasets


def test_get_data_accepts_numpy_datetime64_and_float(provider, fake_stream):
    import numpy as np
    provider.add_channel(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    uid = "sismo/G/SSB/00.HHZ/waveform"
    t0_np = np.datetime64("2026-01-01T00:00:00")
    t1_float = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc).timestamp()
    with patch("sciqlop_sismo.provider.fetch_stream", return_value=fake_stream):
        var = provider.get_data(uid, t0_np, t1_float)
    assert isinstance(var, SpeasyVariable)
