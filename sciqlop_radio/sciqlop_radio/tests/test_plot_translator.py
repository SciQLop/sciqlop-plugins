"""Translator tests — synthetic radiospectra-shaped spectrograms only.

We don't import real radiospectra here; we hand-roll a duck-typed
SimpleSpectrogram object so these tests run without sunpy in the env.
"""
from __future__ import annotations

import types
from datetime import datetime, timezone

import numpy as np
import pytest


@pytest.fixture
def fake_radiospectra(monkeypatch):
    """Provide a Spectrogram class the translator can isinstance-check."""
    fake = types.SimpleNamespace()

    class Spectrogram: ...
    class SpectrogramSequence:
        def __init__(self, spectrograms):
            self.spectrograms = list(spectrograms)

    fake.Spectrogram = Spectrogram
    fake.SpectrogramSequence = SpectrogramSequence
    import sys
    monkeypatch.setitem(sys.modules, "radiospectra", fake)
    monkeypatch.setitem(sys.modules, "radiospectra.spectrogram", types.SimpleNamespace(
        Spectrogram=Spectrogram, SpectrogramSequence=SpectrogramSequence
    ))
    return fake


def _make_spec(SpecCls, *, n_t=8, n_f=5, instrument="TEST"):
    """Build a duck-typed Spectrogram with fixed shape."""
    spec = SpecCls()

    t0 = datetime(2024, 5, 1, tzinfo=timezone.utc)
    spec.times = types.SimpleNamespace(
        to_datetime=lambda: np.array([
            datetime(2024, 5, 1, 0, 0, i, tzinfo=timezone.utc) for i in range(n_t)
        ]),
        unix=np.arange(n_t, dtype=np.float64) + t0.timestamp(),
    )
    # Use exact powers-of-two grid; size scales with n_f so shape is consistent.
    freq_vals = np.array([2.0 ** i for i in range(n_f)], dtype=np.float64)
    spec.frequencies = types.SimpleNamespace(
        to_value=lambda unit, _fv=freq_vals: _fv,
        unit="MHz",
    )
    rng = np.random.default_rng(0)
    spec.data = rng.random((n_f, n_t)).astype(np.float32)
    spec.meta = {"instrument": instrument, "wavelength_unit": "MHz"}
    return spec


def test_to_plot_returns_a_time_series_plot(fake_radiospectra):
    from sciqlop_radio.plot import spectrogram_to_plot
    spec = _make_spec(fake_radiospectra.Spectrogram)
    plot = spectrogram_to_plot(spec, parent=None)
    assert plot is not None
    assert getattr(plot, "_radio_n_time_samples", None) == 8
    assert getattr(plot, "_radio_n_freq_channels", None) == 5


def test_to_plot_data_orientation_is_time_by_freq(fake_radiospectra):
    """SciQLopPlot.colormap wants data shape (n_time, n_freq).

    radiospectra hands us (n_freq, n_time); the translator must transpose.
    """
    from sciqlop_radio.plot import spectrogram_to_plot
    spec = _make_spec(fake_radiospectra.Spectrogram, n_t=12, n_f=7)
    plot = spectrogram_to_plot(spec, parent=None)
    np.testing.assert_array_equal(plot._radio_data_shape, (12, 7))


def test_to_plot_extracts_frequency_array(fake_radiospectra):
    from sciqlop_radio.plot import spectrogram_to_plot
    spec = _make_spec(fake_radiospectra.Spectrogram)
    plot = spectrogram_to_plot(spec, parent=None)
    np.testing.assert_array_equal(
        plot._radio_y_array, np.array([1.0, 2.0, 4.0, 8.0, 16.0])
    )


def test_to_plot_uses_instrument_name_in_title(fake_radiospectra):
    from sciqlop_radio.plot import spectrogram_to_plot
    spec = _make_spec(fake_radiospectra.Spectrogram, instrument="PSP/RFS")
    plot = spectrogram_to_plot(spec, parent=None)
    assert "PSP/RFS" in plot._radio_title


def test_missing_times_raises_radio_plot_error(fake_radiospectra):
    from sciqlop_radio.plot import spectrogram_to_plot, RadioPlotError
    spec = _make_spec(fake_radiospectra.Spectrogram)
    spec.times = None
    with pytest.raises(RadioPlotError):
        spectrogram_to_plot(spec, parent=None)


def test_missing_data_raises_radio_plot_error(fake_radiospectra):
    from sciqlop_radio.plot import spectrogram_to_plot, RadioPlotError
    spec = _make_spec(fake_radiospectra.Spectrogram)
    spec.data = np.empty((0, 0))
    with pytest.raises(RadioPlotError):
        spectrogram_to_plot(spec, parent=None)


def test_sequence_concatenates_along_time(fake_radiospectra):
    from sciqlop_radio.plot import spectrogram_to_plot
    s1 = _make_spec(fake_radiospectra.Spectrogram, n_t=4)
    s2 = _make_spec(fake_radiospectra.Spectrogram, n_t=6)
    seq = fake_radiospectra.SpectrogramSequence([s1, s2])
    plot = spectrogram_to_plot(seq, parent=None)
    assert plot._radio_n_time_samples == 10
