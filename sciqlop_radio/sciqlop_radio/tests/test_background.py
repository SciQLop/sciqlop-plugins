"""Tests for the shared background-removal knobs and transform.

`apply_background` is the only place the plugin touches SciQLop's DSP layer,
so these tests cover both the knob surface SciQLop introspects and the
never-raise contract the callbacks rely on.
"""
from __future__ import annotations

import numpy as np
import pytest


def _extract_specs(callback):
    """Run SciQLop's real knob introspection, or skip when it isn't installed."""
    knobs = pytest.importorskip("SciQLop.user_api.knobs")
    return {s.name: s for s in knobs.extract_specs_from_callback(callback)}


def test_knob_aliases_survive_sciqlop_introspection():
    """Regression for the module-globals trap. SciQLop resolves stringified
    annotations in the *callback's* module globals, so the aliases have to be
    real module-level names there. Both failure paths are silent — knobs just
    vanish from the UI — so this test is the only thing that catches a
    regression to a lazy import."""
    from sciqlop_radio.tests import _knob_probe

    cb = _knob_probe.build_probe_callback()
    specs = _extract_specs(cb)

    assert set(specs) == {"bg_mode", "bg_window_s", "bg_q"}
    assert type(specs["bg_mode"]).__name__ == "ChoiceKnob"
    assert specs["bg_mode"].default == "off"
    assert [value for _, value in specs["bg_mode"].choices] == ["off", "diff", "ratio", "db"]
    assert type(specs["bg_window_s"]).__name__ == "FloatKnob"
    assert (specs["bg_window_s"].default, specs["bg_window_s"].min,
            specs["bg_window_s"].max) == (0.0, 0.0, 86400.0)
    assert specs["bg_window_s"].unit == "s"
    assert type(specs["bg_q"]).__name__ == "FloatKnob"
    assert (specs["bg_q"].default, specs["bg_q"].min, specs["bg_q"].max) == (50.0, 0.0, 100.0)


def test_probe_callback_positional_args_stay_float_under_eval_str():
    """The second, quieter half of the same trap: EasyProvider calls
    `signature(callback, eval_str=True)` and on NameError silently retries
    without it, at which point `start: float` is the *string* "float", the
    provider falls back to ArgumentsType.Unknown and warns about missing type
    hints. Assert the annotations really do evaluate."""
    import inspect
    from sciqlop_radio.tests import _knob_probe

    cb = _knob_probe.build_probe_callback()
    sig = inspect.signature(cb, eval_str=True)
    assert [sig.parameters[n].annotation for n in ("start", "stop")] == [float, float]


@pytest.fixture
def spectrogram():
    """A 2-D SpeasyVariable with a per-channel background: channel k sits at a
    baseline of 10**k, so a correct per-channel removal collapses the spread
    between channels."""
    pytest.importorskip("speasy")
    from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
    from speasy.products.variable import SpeasyVariable

    def _make(n_time=200, n_freq=4, meta=None):
        t0 = np.datetime64("2024-01-01T00:00:00", "ns").astype("int64")
        times = (t0 + np.arange(n_time) * 1_000_000_000).astype("datetime64[ns]")
        baselines = 10.0 ** np.arange(n_freq)
        data = np.tile(baselines, (n_time, 1)) * (1.0 + 0.01 * np.arange(n_time)[:, None])
        return SpeasyVariable(
            axes=[VariableTimeAxis(values=times),
                  VariableAxis(name="frequency",
                               values=np.arange(n_freq, dtype=np.float64),
                               meta={"UNITS": "Hz"})],
            values=DataContainer(values=data,
                                 meta=dict(meta or {"UNITS": "sfu", "SCALETYP": "log"}),
                                 name="TEST"),
            columns=["TEST"])

    return _make


def test_off_returns_the_same_object(spectrogram):
    """The default must cost nothing at all — not a copy, not a transform."""
    from sciqlop_radio.background import apply_background
    v = spectrogram()
    assert apply_background(v, mode="off", window_s=30.0, q=10.0) is v


def test_none_passes_through():
    from sciqlop_radio.background import apply_background
    assert apply_background(None, mode="db") is None


@pytest.mark.parametrize("mode,units", [("diff", "sfu"), ("ratio", ""), ("db", "dB")])
def test_each_mode_preserves_axes_and_sets_meta(spectrogram, mode, units):
    """Shape, both axes and dtype survive; UNITS follows the mode; SCALETYP is
    forced to linear because 'log' is wrong for every mode (diff goes negative,
    db is already logarithmic)."""
    pytest.importorskip("SciQLop.user_api.dsp")
    from sciqlop_radio.background import apply_background
    v = spectrogram()
    out = apply_background(v, mode=mode)

    assert out is not v
    assert out.values.shape == v.values.shape
    assert np.array_equal(out.time, v.time)
    assert np.array_equal(out.axes[1].values, v.axes[1].values)
    assert out.meta["UNITS"] == units
    assert out.meta["SCALETYP"] == "linear"


def test_diff_flattens_the_per_channel_baseline(spectrogram):
    """The whole point: channels spanning four decades come out on one scale."""
    pytest.importorskip("SciQLop.user_api.dsp")
    from sciqlop_radio.background import apply_background
    v = spectrogram()
    raw_spread = np.ptp(np.asarray(v.values).mean(axis=0))
    out_spread = np.ptp(np.asarray(apply_background(v, mode="diff").values).mean(axis=0))
    assert out_spread < raw_spread / 100.0


def test_window_seconds_selects_the_sliding_background(spectrogram):
    """window_s > 0 must reach the sliding kernel, not the constant one. The
    fixture's baseline drifts with time, so a short sliding window tracks it
    and leaves a visibly smaller residual than one constant background."""
    pytest.importorskip("SciQLop.user_api.dsp")
    from sciqlop_radio.background import apply_background
    v = spectrogram()
    constant = np.abs(np.asarray(apply_background(v, mode="diff", window_s=0.0).values)).mean()
    sliding = np.abs(np.asarray(apply_background(v, mode="diff", window_s=20.0).values)).mean()
    assert sliding < constant


def test_single_channel_spectrogram_survives_a_sliding_window(spectrogram):
    """(n, 1) is the shape that trips the DSP layer's collapsed-column-axis
    trap. It is handled inside background_subtract; assert it stays handled."""
    pytest.importorskip("SciQLop.user_api.dsp")
    from sciqlop_radio.background import apply_background
    v = spectrogram(n_freq=1)
    out = apply_background(v, mode="db", window_s=30.0)
    assert out.values.shape == v.values.shape


def test_dsp_failure_returns_raw_data_and_logs(spectrogram, monkeypatch, caplog):
    """A bad knob value must degrade to an unprocessed plot, never a blank one."""
    import SciQLop.user_api.dsp as sciqlop_dsp
    from sciqlop_radio.background import apply_background

    def _boom(*args, **kwargs):
        raise RuntimeError("kernel exploded")

    monkeypatch.setattr(sciqlop_dsp, "background_subtract", _boom)
    v = spectrogram()
    with caplog.at_level("WARNING"):
        out = apply_background(v, mode="db", window_s=30.0)
    assert out is v
    assert "kernel exploded" in caplog.text


def test_non_2d_variable_is_returned_untouched(spectrogram, caplog):
    from sciqlop_radio.background import apply_background

    class _Fake:
        values = np.zeros((3, 4, 5))

    fake = _Fake()
    with caplog.at_level("WARNING"):
        assert apply_background(fake, mode="db") is fake
    assert "2-D" in caplog.text
