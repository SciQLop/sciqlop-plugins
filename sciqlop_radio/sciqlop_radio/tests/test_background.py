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
