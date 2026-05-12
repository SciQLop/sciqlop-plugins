"""Tests for sciqlop_sismo.process.

Synthetic Streams only — no network, no real seismic data.
"""
import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime

from sciqlop_sismo.process import bandpass, default_pipeline, detrend
from sciqlop_sismo.settings import SismoSettings


def _synthetic_trace(data: np.ndarray, sampling_rate: float = 100.0) -> Trace:
    return Trace(
        data=np.asarray(data, dtype=np.float64),
        header={
            "network": "XX",
            "station": "TEST",
            "location": "00",
            "channel": "HHZ",
            "sampling_rate": sampling_rate,
            "starttime": UTCDateTime("2026-01-01T00:00:00"),
        },
    )


def test_detrend_removes_constant_offset():
    n = 1000
    tr = _synthetic_trace(np.ones(n) * 42.0)
    out = detrend(Stream([tr]))
    assert out is not Stream([tr])
    assert np.mean(out[0].data) == pytest.approx(0.0, abs=1e-9)


def test_detrend_preserves_oscillation():
    n = 1000
    t = np.arange(n) / 100.0
    signal = np.sin(2 * np.pi * 1.0 * t)
    tr = _synthetic_trace(signal + 5.0)
    out = detrend(Stream([tr]))
    assert out[0].data.max() == pytest.approx(1.0, abs=0.05)
    assert out[0].data.min() == pytest.approx(-1.0, abs=0.05)


def test_bandpass_attenuates_out_of_band():
    n = 4096
    sr = 100.0
    t = np.arange(n) / sr
    low = np.sin(2 * np.pi * 0.05 * t)
    mid = np.sin(2 * np.pi * 2.0 * t)
    high = np.sin(2 * np.pi * 40.0 * t)
    tr = _synthetic_trace(low + mid + high)
    out = bandpass(Stream([tr]), fmin=1.0, fmax=10.0)
    assert np.max(np.abs(out[0].data)) > 0.7
    spec = np.abs(np.fft.rfft(out[0].data))
    freqs = np.fft.rfftfreq(n, d=1 / sr)
    mid_idx = np.argmin(np.abs(freqs - 2.0))
    high_idx = np.argmin(np.abs(freqs - 40.0))
    assert spec[high_idx] < 0.05 * spec[mid_idx]


def test_default_pipeline_detrends_and_bandpasses():
    n = 4096
    sr = 100.0
    t = np.arange(n) / sr
    sig = np.sin(2 * np.pi * 2.0 * t) + 5.0
    tr = _synthetic_trace(sig)
    s = SismoSettings(bandpass_min_hz=1.0, bandpass_max_hz=10.0)
    out = default_pipeline(Stream([tr]), s)
    assert np.mean(out[0].data) == pytest.approx(0.0, abs=0.01)


def test_pure_functions_do_not_mutate_input():
    tr = _synthetic_trace(np.ones(1000) * 42.0)
    original = tr.data.copy()
    stream = Stream([tr])
    _ = detrend(stream)
    np.testing.assert_array_equal(tr.data, original)
