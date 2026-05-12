"""Tests for sciqlop_sismo.local_files.

We synthesize a tiny miniSEED via ObsPy then read it back through our
helper — no fixtures committed to git.
"""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from obspy import Trace, UTCDateTime

from sciqlop_sismo.local_files import ChannelInfo, import_file


def _write_synthetic_mseed(path: Path, channel: str = "HHZ"):
    tr = Trace(
        data=np.linspace(0, 1, 1000, dtype=np.float32),
        header={
            "network": "XX",
            "station": "TEST",
            "location": "00",
            "channel": channel,
            "sampling_rate": 100.0,
            "starttime": UTCDateTime("2026-01-01T00:00:00"),
        },
    )
    tr.write(str(path), format="MSEED")


def test_import_file_returns_one_channel_info_per_channel(tmp_path):
    p = tmp_path / "single.mseed"
    _write_synthetic_mseed(p)
    infos = import_file(p)
    assert len(infos) == 1
    info = infos[0]
    assert isinstance(info, ChannelInfo)
    assert (info.network, info.station, info.location, info.channel) == (
        "XX", "TEST", "00", "HHZ",
    )
    assert info.sampling_rate_hz == 100.0
    assert info.start_date == datetime(2026, 1, 1, tzinfo=timezone.utc)
    duration = (info.stop_date - info.start_date).total_seconds()
    assert 9.95 < duration < 10.05
    assert info.routing.startswith("local:")
    assert info.path == p


def test_import_file_yields_multiple_channels(tmp_path):
    p = tmp_path / "multi.mseed"
    traces = []
    for chan in ("HHZ", "HHN", "HHE"):
        traces.append(Trace(
            data=np.zeros(500, dtype=np.float32),
            header={
                "network": "XX", "station": "TEST", "location": "00",
                "channel": chan, "sampling_rate": 100.0,
                "starttime": UTCDateTime("2026-01-01T00:00:00"),
            },
        ))
    from obspy import Stream
    Stream(traces).write(str(p), format="MSEED")
    infos = import_file(p)
    channels = {i.channel for i in infos}
    assert channels == {"HHZ", "HHN", "HHE"}


def test_import_file_rejects_missing_path(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        import_file(tmp_path / "no-such-file.mseed")


def test_routing_includes_sha1_of_path(tmp_path):
    p = tmp_path / "x.mseed"
    _write_synthetic_mseed(p)
    info = import_file(p)[0]
    assert info.routing.startswith("local:")
    suffix = info.routing.removeprefix("local:")
    assert len(suffix) == 40
    int(suffix, 16)  # raises if not hex
