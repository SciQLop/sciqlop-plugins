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
    freq_vals = np.array([2.0 ** i for i in range(n_f)], dtype=np.float64)
    spec.frequencies = types.SimpleNamespace(
        to_value=lambda unit, _fv=freq_vals: _fv,
        unit="MHz",
    )
    rng = np.random.default_rng(0)
    spec.data = rng.random((n_f, n_t)).astype(np.float32)
    spec.meta = {"instrument": instrument, "wavelength_unit": "MHz"}
    return spec


def test_to_variable_is_2d_speasy_variable(fake_radiospectra):
    from speasy.products.variable import SpeasyVariable

    from sciqlop_radio.plot import spectrogram_to_speasy_variable
    spec = _make_spec(fake_radiospectra.Spectrogram)
    var = spectrogram_to_speasy_variable(spec)
    assert isinstance(var, SpeasyVariable)
    assert var.values.ndim == 2
    assert var.values.shape == (8, 5)  # (n_time, n_freq)
    assert len(var.axes) == 2


def test_to_variable_data_orientation_is_time_by_freq(fake_radiospectra):
    """radiospectra hands (n_freq, n_time); converter must transpose."""
    from sciqlop_radio.plot import spectrogram_to_speasy_variable
    spec = _make_spec(fake_radiospectra.Spectrogram, n_t=12, n_f=7)
    var = spectrogram_to_speasy_variable(spec)
    assert var.values.shape == (12, 7)


def test_to_variable_frequency_axis_values(fake_radiospectra):
    from sciqlop_radio.plot import spectrogram_to_speasy_variable
    spec = _make_spec(fake_radiospectra.Spectrogram)
    var = spectrogram_to_speasy_variable(spec)
    freq_axis = var.axes[1]
    np.testing.assert_array_equal(
        freq_axis.values, np.array([1.0, 2.0, 4.0, 8.0, 16.0])
    )


def test_to_variable_carries_instrument_in_columns(fake_radiospectra):
    from sciqlop_radio.plot import spectrogram_to_speasy_variable
    spec = _make_spec(fake_radiospectra.Spectrogram, instrument="PSP/RFS")
    var = spectrogram_to_speasy_variable(spec)
    assert "PSP/RFS" in var.columns


def test_missing_times_raises_radio_plot_error(fake_radiospectra):
    from sciqlop_radio.plot import RadioPlotError, spectrogram_to_speasy_variable
    spec = _make_spec(fake_radiospectra.Spectrogram)
    spec.times = None
    with pytest.raises(RadioPlotError):
        spectrogram_to_speasy_variable(spec)


def test_missing_data_raises_radio_plot_error(fake_radiospectra):
    from sciqlop_radio.plot import RadioPlotError, spectrogram_to_speasy_variable
    spec = _make_spec(fake_radiospectra.Spectrogram)
    spec.data = np.empty((0, 0))
    with pytest.raises(RadioPlotError):
        spectrogram_to_speasy_variable(spec)


def test_sequence_concatenates_along_time(fake_radiospectra):
    from sciqlop_radio.plot import spectrogram_to_speasy_variable

    def _spec_at(SpecCls, start_offset_s: int, n_t: int):
        spec = SpecCls()
        t0 = datetime(2024, 5, 1, tzinfo=timezone.utc).timestamp()
        spec.times = types.SimpleNamespace(
            unix=np.arange(n_t, dtype=np.float64) + t0 + start_offset_s,
            to_datetime=lambda: np.array([
                datetime.fromtimestamp(t0 + start_offset_s + i, tz=timezone.utc)
                for i in range(n_t)
            ]),
        )
        spec.frequencies = types.SimpleNamespace(
            to_value=lambda unit: np.array([1.0, 2.0, 4.0, 8.0, 16.0]),
            unit="MHz",
        )
        rng = np.random.default_rng(0)
        spec.data = rng.random((5, n_t)).astype(np.float32)
        spec.meta = {"instrument": "TEST", "wavelength_unit": "MHz"}
        return spec

    s1 = _spec_at(fake_radiospectra.Spectrogram, start_offset_s=0, n_t=4)
    s2 = _spec_at(fake_radiospectra.Spectrogram, start_offset_s=4, n_t=6)
    seq = fake_radiospectra.SpectrogramSequence([s2, s1])  # out of order on purpose
    var = spectrogram_to_speasy_variable(seq)
    assert var.values.shape[0] == 10  # 4 + 6 time samples
    time_ns = var.axes[0].values.astype("datetime64[ns]").astype("int64")
    assert np.all(np.diff(time_ns) >= 0), "concatenated times must be non-decreasing"


def test_list_of_cotemporal_bands_stacks_along_frequency(fake_radiospectra):
    """ILOFAR mode-357: radiospectra.Spectrogram(.dat) returns a plain *list*
    of band-spectrograms that share one time grid but cover different
    frequencies. They must be stacked along the frequency axis."""
    from sciqlop_radio.plot import spectrogram_to_speasy_variable

    t0 = datetime(2021, 9, 1, tzinfo=timezone.utc).timestamp()
    n_t = 6

    def band(freqs):
        s = fake_radiospectra.Spectrogram()
        s.times = types.SimpleNamespace(
            unix=np.arange(n_t, dtype=np.float64) + t0,
            to_datetime=lambda: np.array(
                [datetime.fromtimestamp(t0 + i, tz=timezone.utc) for i in range(n_t)]
            ),
        )
        fv = np.array(freqs, dtype=np.float64)
        s.frequencies = types.SimpleNamespace(to_value=lambda unit, _fv=fv: _fv, unit="MHz")
        s.data = np.zeros((len(fv), n_t), dtype=np.float32)  # (n_freq, n_time)
        s.meta = {"instrument": "ILOFAR", "wavelength_unit": "MHz"}
        return s

    bands = [band([210.0, 244.0]), band([10.0, 88.0]), band([110.0, 188.0])]  # unordered
    var = spectrogram_to_speasy_variable(bands)  # a plain list, not a Sequence
    assert var.values.shape == (n_t, 6)  # time preserved, 2+2+2 freqs stacked
    np.testing.assert_array_equal(
        var.axes[1].values, np.array([10.0, 88.0, 110.0, 188.0, 210.0, 244.0])
    )
