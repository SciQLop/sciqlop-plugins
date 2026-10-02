"""Tests for sciqlop_sismo.stream_to_variable."""
import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime
from speasy.products.variable import SpeasyVariable

from sciqlop_sismo.stream_to_variable import (
    spectrogram_from_stream,
    stream_to_speasy_variable,
)


def _synthetic_trace(npts: int = 1000, sampling_rate: float = 100.0, channel: str = "HHZ") -> Trace:
    return Trace(
        data=np.linspace(0, 1, npts, dtype=np.float64),
        header={
            "network": "G",
            "station": "SSB",
            "location": "00",
            "channel": channel,
            "sampling_rate": sampling_rate,
            "starttime": UTCDateTime("2026-01-01T00:00:00"),
        },
    )


def test_waveform_variable_basic_shape():
    tr = _synthetic_trace(npts=500)
    var = stream_to_speasy_variable(Stream([tr]), channel="HHZ", units="counts")
    assert isinstance(var, SpeasyVariable)
    assert var.values.shape[0] == 500
    assert var.unit == "counts"


def test_waveform_variable_time_axis_monotonic_and_utc():
    tr = _synthetic_trace(npts=200, sampling_rate=50.0)
    var = stream_to_speasy_variable(Stream([tr]), channel="HHZ", units="m/s")
    t = var.time
    assert len(t) == 200
    diffs = np.diff(t.astype("datetime64[ns]").astype("int64")) / 1e9
    assert np.all(diffs > 0)
    assert diffs.mean() == pytest.approx(0.02, rel=1e-3)


def test_stream_to_variable_picks_requested_channel():
    z = _synthetic_trace(channel="HHZ")
    n = _synthetic_trace(channel="HHN")
    var = stream_to_speasy_variable(Stream([z, n]), channel="HHN", units="m/s")
    assert var.name.endswith("HHN")


def test_stream_to_variable_raises_when_channel_absent():
    tr = _synthetic_trace(channel="HHZ")
    with pytest.raises(KeyError, match="HHE"):
        stream_to_speasy_variable(Stream([tr]), channel="HHE", units="m/s")


def test_spectrogram_variable_is_2d_with_frequency_axis():
    tr = _synthetic_trace(npts=4096, sampling_rate=100.0)
    var = spectrogram_from_stream(
        Stream([tr]), channel="HHZ", nperseg=256, noverlap=128
    )
    assert isinstance(var, SpeasyVariable)
    assert var.values.ndim == 2
    assert var.values.shape[1] == 256 // 2 + 1
    freq_axis = var.axes[1].values
    assert freq_axis[0] == pytest.approx(0.0)
    assert np.all(np.diff(freq_axis) > 0)


def test_spectrogram_variable_no_nan():
    tr = _synthetic_trace(npts=4096)
    var = spectrogram_from_stream(Stream([tr]), channel="HHZ")
    assert not np.any(np.isnan(var.values))


def _gapped_stream():
    """Three 100 Hz pieces of one channel with gaps, like a real FDSN fetch of IU.ADK."""
    from obspy import Stream, Trace, UTCDateTime
    t0 = UTCDateTime("2026-10-02T00:00:00")
    pieces = [(0, 1000), (30, 500), (100, 2000)]  # (start offset s, samples)
    return Stream([Trace(data=np.arange(n, dtype=np.float64) + 10 * i,
                         header={"network": "IU", "station": "ADK", "location": "00", "channel": "HHZ",
                                 "sampling_rate": 100.0, "starttime": t0 + off})
                   for i, (off, n) in enumerate(pieces)]), t0, pieces


def test_every_trace_of_a_gapped_stream_reaches_the_variable():
    """Only the first trace was kept: the speasy fragment cache then trimmed it away and
    the waveform plot stayed empty."""
    from sciqlop_sismo.stream_to_variable import stream_to_speasy_variable
    stream, t0, pieces = _gapped_stream()

    v = stream_to_speasy_variable(stream, channel="HHZ", units="counts")

    values = v.values.reshape(-1)
    assert np.isfinite(values).sum() == sum(n for _, n in pieces)
    assert np.isnan(values).any()  # the gaps
    last_off, last_n = pieces[-1]
    expected_last = np.datetime64(str((t0 + last_off + (last_n - 1) / 100.0).datetime), "ns")
    assert abs(v.time[-1] - expected_last) < np.timedelta64(1, "ms")


def test_a_gapped_variable_turns_back_into_one_trace_per_piece_at_the_right_times():
    from sciqlop_sismo.stream_to_variable import stream_to_speasy_variable, variable_to_stream
    stream, t0, pieces = _gapped_stream()
    v = stream_to_speasy_variable(stream, channel="HHZ", units="counts")

    back = variable_to_stream(v, ("IU", "ADK", "00", "HHZ"), 100.0)

    assert [tr.stats.npts for tr in back] == [n for _, n in pieces]
    assert [round(tr.stats.starttime - t0, 3) for tr in back] == [float(off) for off, _ in pieces]


def test_an_empty_variable_gives_an_empty_stream():
    from sciqlop_sismo.stream_to_variable import stream_to_speasy_variable, variable_to_stream
    stream, _, _ = _gapped_stream()
    empty = stream_to_speasy_variable(stream, channel="HHZ", units="counts")[0:0]

    assert len(variable_to_stream(empty, ("IU", "ADK", "00", "HHZ"), 100.0)) == 0
