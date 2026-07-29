# Radio Background-Removal Knobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose `SciQLop.user_api.dsp.background_subtract` as three inspector knobs on every radio spectrogram the `sciqlop_radio` plugin serves, so a user can remove the per-channel receiver background without writing code.

**Architecture:** One new module, `sciqlop_radio/background.py`, holds three `Annotated` knob aliases and a single `apply_background()` function. `continuous.py`'s and `lofar.py`'s callbacks import the aliases at module top level, declare them as keyword parameters, and pipe their result through `apply_background()` before returning. No numerics in the plugin — it delegates to `SciQLop.user_api.dsp`.

**Tech Stack:** Python 3.13, numpy, speasy (`SpeasyVariable`), SciQLop `user_api` (`knobs`, `dsp`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-28-radio-background-removal-knobs-design.md`

## Global Constraints

- Work happens in `/var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio`.
- Run tests with SciQLop's venv, from the plugin directory, with `QT_QPA_PLATFORM=xcb`:
  ```bash
  cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
    QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
    -m pytest sciqlop_radio/tests/ -q -m "not live"
  ```
  Baseline before any change: **186 passed, 5 skipped**. Never use `QT_QPA_PLATFORM=offscreen` — the suite hard-crashes in libxkbcommon under native Wayland, and `offscreen` is separately forbidden in this project.
- `Knob` and the annotation aliases MUST be imported at **module top level** in every module that declares them on a callback. See the spec's "module-globals trap" section — both SciQLop introspection paths fail silently otherwise.
- Every module in this package uses `from __future__ import annotations`. Keep that.
- `bg_mode` defaults to `'off'`, so all existing behaviour must be bit-identical when no knob is touched.
- `apply_background()` must never raise.
- Do not expose `gap_factor`. Do not add caching. Do not touch RFI flagging, median rebinning or Stokes I.
- The plugin has no CHANGELOG, and its README documents no knobs (not even the existing Beam/SAP pair). Do not add either — stay consistent with the package.

---

### Task 1: Knob annotation aliases

Creates the module and proves the three annotations survive SciQLop's introspection. This is the task that pins down the trap the whole design is shaped around.

**Files:**
- Create: `sciqlop_radio/background.py`
- Test: `sciqlop_radio/tests/test_background.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `sciqlop_radio.background.BgMode`, `.BgWindow`, `.BgQ` — three `typing.Annotated` aliases used as parameter annotations by Tasks 3 and 4. `BgMode` annotates a `str` defaulting to `'off'`; `BgWindow` and `BgQ` annotate `float` defaulting to `0.0` and `50.0`.

- [ ] **Step 1: Write the failing test**

Create `sciqlop_radio/tests/test_background.py`:

```python
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
```

Create `sciqlop_radio/tests/_knob_probe.py` — a minimal stand-in for a real callback module, so Task 1 can prove the aliases work before any callback is wired up:

```python
"""A minimal module that declares the background knobs on a nested callback,
exactly as `continuous.py` and `lofar.py` do. Exists so the introspection
regression test has a target that isolates the annotations from the rest of
the fetch machinery."""
from __future__ import annotations

from sciqlop_radio.background import BgMode, BgQ, BgWindow


def build_probe_callback():
    def _probe(start: float, stop: float, bg_mode: BgMode = 'off',
               bg_window_s: BgWindow = 0.0, bg_q: BgQ = 50.0):
        return (start, stop, bg_mode, bg_window_s, bg_q)

    return _probe
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_background.py -q
```

Expected: both tests FAIL — `ModuleNotFoundError: No module named 'sciqlop_radio.background'`.

- [ ] **Step 3: Create `sciqlop_radio/background.py` with the aliases**

```python
"""Per-channel background removal shared by the radio spectrogram callbacks.

Exposes `SciQLop.user_api.dsp.background_subtract` as three knobs that
`continuous.py` and `lofar.py` declare on their fetch callbacks. All numerics
live in SciQLop's DSP layer; only the knob surface, the seconds-to-duration
conversion and the colour-scale policy are instrument/display concerns and
therefore belong here.
"""
from __future__ import annotations

import logging
from typing import Annotated, Literal

import numpy as np

log = logging.getLogger(__name__)


# Module-level Knob binding — SciQLop resolves the stringified annotations
# below in the *callback's* module globals, not in this one, so the aliases
# must be importable as plain top-level names by every module that declares
# them. Both of SciQLop's introspection paths degrade silently on a NameError
# (knobs vanish from the UI; the provider warns about missing type hints and
# assumes float), so a lazy import here would be invisible until someone
# noticed the knobs missing. Headless tests without a SciQLop install fall
# back to a no-op stub so module import never breaks.
try:
    from SciQLop.user_api.knobs import Knob
except ImportError:  # pragma: no cover — only hit in headless CI
    class Knob:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            pass


BgMode = Annotated[
    Literal['off', 'diff', 'ratio', 'db'],
    Knob(label="Background",
         description="Per-channel background removal: off, S-bg, S/bg, "
                     "or 10*log10(S/bg)."),
]

# Seconds rather than samples: I-LOFAR runs at 1 s cadence and e-Callisto at
# 0.25 s, so one shared sample-count default would mean a different duration
# per product. It also keeps the plugin clear of `resolve_window`'s
# int-vs-timedelta dispatch — we only ever pass None or an np.timedelta64.
BgWindow = Annotated[
    float,
    Knob(min=0.0, max=86400.0, step=1.0, unit="s", label="BG window",
         description="Sliding background duration in seconds; 0 uses one "
                     "constant background over the whole view."),
]

BgQ = Annotated[
    float,
    Knob(min=0.0, max=100.0, step=1.0, unit="%", label="BG percentile",
         description="Percentile of the background estimator. 50 is the "
                     "median; 5-10 when bursts fill much of the view."),
]
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_background.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add sciqlop_radio/sciqlop_radio/background.py \
        sciqlop_radio/sciqlop_radio/tests/test_background.py \
        sciqlop_radio/sciqlop_radio/tests/_knob_probe.py
git commit -m "feat(sciqlop_radio): background-removal knob annotations"
```

---

### Task 2: `apply_background()` — transform, display policy, never-raise contract

**Files:**
- Modify: `sciqlop_radio/background.py` (append after the aliases)
- Test: `sciqlop_radio/tests/test_background.py` (append)

**Interfaces:**
- Consumes: `sciqlop_radio.background` from Task 1.
- Produces: `apply_background(variable, *, mode: str = 'off', window_s: float = 0.0, q: float = 50.0)`. Returns a `SpeasyVariable`, or `None` if `variable` is `None`. Returns the **same object** when `mode == 'off'`. Never raises. Tasks 3 and 4 call it with exactly these keyword names.

**Background for the implementer:** `SpeasyVariable.values` is a plain `ndarray`; `SpeasyVariable.meta` is a mutable `dict`. `dsp.background_subtract` already sets `UNITS` per mode (`''` for ratio, `'dB'` for db, untouched for diff) and preserves both axes and the shape, but it copies `SCALETYP` from the input unchanged — which is `'log'` on every radio product and wrong for all three modes. A single-channel spectrogram has shape `(n, 1)`, still 2-D, and the DSP layer already handles it.

- [ ] **Step 1: Write the failing tests**

Append to `sciqlop_radio/tests/test_background.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_background.py -q
```

Expected: the 2 tests from Task 1 pass; the new ones FAIL with `ImportError: cannot import name 'apply_background'`.

- [ ] **Step 3: Append `apply_background` to `sciqlop_radio/background.py`**

```python
def apply_background(variable, *, mode: str = 'off',
                     window_s: float = 0.0, q: float = 50.0):
    """Remove a per-channel background from a spectrogram variable.

    `mode` is 'off' (return the input untouched), 'diff', 'ratio' or 'db'.
    `window_s` is the sliding-background duration in seconds; 0 estimates one
    constant background per channel over the whole view. `q` is the estimator
    percentile.

    Never raises. A processing failure logs and returns the untransformed
    variable, so a bad knob value degrades to an unprocessed plot rather than
    a blank one.
    """
    if variable is None or mode == 'off':
        return variable

    if np.ndim(getattr(variable, 'values', None)) != 2:
        log.warning("background: expected a 2-D spectrogram, got ndim=%s — skipping",
                    np.ndim(getattr(variable, 'values', None)))
        return variable

    try:
        from SciQLop.user_api import dsp
        window = None if window_s <= 0.0 else np.timedelta64(int(window_s * 1e9), 'ns')
        out = dsp.background_subtract(variable, q=q, window=window, mode=mode)
    except Exception as exc:  # noqa: BLE001
        log.warning("background: mode=%s q=%s window_s=%s failed: %s — returning raw data",
                    mode, q, window_s, exc)
        return variable

    # Every radio product declares SCALETYP 'log', which is wrong for all three
    # modes: diff output goes negative and db is already logarithmic. hints.py's
    # plot_hints_from_variable reads this back out of the returned variable.
    out.meta['SCALETYP'] = 'linear'
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_background.py -q
```

Expected: `11 passed` (2 from Task 1, 9 here — the mode test is parametrized three ways).

- [ ] **Step 5: Commit**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add sciqlop_radio/sciqlop_radio/background.py \
        sciqlop_radio/sciqlop_radio/tests/test_background.py
git commit -m "feat(sciqlop_radio): apply_background transform with never-raise contract"
```

---

### Task 3: Wire the knobs into the continuous callback

Reaches `radio/eovsa`, `radio/ilofar/X`, `radio/ilofar/Y` **and** every dock-built e-Callisto/RSTN stream, because `make_stream_source` feeds the same `_build_callback`.

**Files:**
- Modify: `sciqlop_radio/continuous.py` (imports near line 36; `_build_callback` at lines 436-509)
- Test: `sciqlop_radio/tests/test_continuous.py` (append)

**Interfaces:**
- Consumes: `apply_background`, `BgMode`, `BgWindow`, `BgQ` from Tasks 1-2.
- Produces: `_build_callback(source, cache_dir, open_and_convert)` now returns `_callback(start, stop, bg_mode='off', bg_window_s=0.0, bg_q=50.0)`.

- [ ] **Step 1: Write the failing tests**

`test_continuous.py` does not currently import `Path`. Add it to the import block at the top of the file, after `from datetime import datetime, timezone`:

```python
from pathlib import Path
```

Then append:

```python
def _stub_continuous_pipeline(monkeypatch, variable):
    """Short-circuit search/fetch/parse so the callback tests exercise only the
    knob plumbing. Returns the ContinuousSource the callback is built for."""
    from sciqlop_radio import continuous

    monkeypatch.setattr(continuous, "_search_rows_for_window",
                        lambda t0, t1, source, cache_dir: [{"url": "u"}])
    monkeypatch.setattr(continuous, "_filter_rows_for_stream", lambda rows, source: rows)
    monkeypatch.setattr(continuous, "_fetch_paths", lambda rows, cache_dir: [Path("f.fit")])
    monkeypatch.setattr(continuous, "_concat_spectrograms", lambda variables: variable)
    return continuous.CONTINUOUS_SOURCES[0]


def test_continuous_callback_exposes_the_background_knobs(tmp_path):
    """The knobs must reach SciQLop's introspection through the real callback,
    not just through the probe module — this is what a user actually sees."""
    knobs = pytest.importorskip("SciQLop.user_api.knobs")
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES, _build_callback

    cb = _build_callback(CONTINUOUS_SOURCES[0], tmp_path, lambda p: None)
    specs = {s.name: s for s in knobs.extract_specs_from_callback(cb)}
    assert {"bg_mode", "bg_window_s", "bg_q"} <= set(specs)
    assert specs["bg_mode"].default == "off"


def test_continuous_callback_default_leaves_data_untouched(monkeypatch, tmp_path,
                                                           speasy_variable_factory):
    """Defaults must be bit-identical to the pre-knob behaviour."""
    from sciqlop_radio.continuous import _build_callback

    v = speasy_variable_factory("2024-01-01T00:00:00", 20, 3)
    source = _stub_continuous_pipeline(monkeypatch, v)
    cb = _build_callback(source, tmp_path, lambda p: v)
    assert cb(0.0, 100.0) is v


def test_continuous_callback_applies_background_when_asked(monkeypatch, tmp_path,
                                                           speasy_variable_factory):
    from sciqlop_radio.continuous import _build_callback

    v = speasy_variable_factory("2024-01-01T00:00:00", 20, 3)
    source = _stub_continuous_pipeline(monkeypatch, v)
    seen = {}

    def _spy(variable, *, mode, window_s, q):
        seen.update(mode=mode, window_s=window_s, q=q)
        return variable

    monkeypatch.setattr("sciqlop_radio.continuous.apply_background", _spy)
    cb = _build_callback(source, tmp_path, lambda p: v)
    cb(0.0, 100.0, bg_mode="db", bg_window_s=30.0, bg_q=10.0)
    assert seen == {"mode": "db", "window_s": 30.0, "q": 10.0}
```

Add `from pathlib import Path` to the imports at the top of `test_continuous.py` if it is not already there, and remove the redundant local import above if it is.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_continuous.py -q -k background
```

Expected: FAIL — no `bg_mode` in the specs, and `AttributeError` on `sciqlop_radio.continuous.apply_background`.

- [ ] **Step 3: Wire it into `continuous.py`**

Add to the module-level imports, right after `from .plot import frequency_signature` (around line 37):

```python
from .background import BgMode, BgQ, BgWindow, apply_background
```

Change the callback signature in `_build_callback` from:

```python
    def _callback(start: float, stop: float):
```

to:

```python
    def _callback(start: float, stop: float, bg_mode: BgMode = 'off',
                  bg_window_s: BgWindow = 0.0, bg_q: BgQ = 50.0):
```

Then replace the tail of `_callback` — the block starting `out = _concat_spectrograms(variables)` — with:

```python
            out = _concat_spectrograms(variables)
            out = apply_background(out, mode=bg_mode, window_s=bg_window_s, q=bg_q)
            if out is None:
                log.warning("continuous(%s): no usable data after concat", source.vp_path)
            else:
                log.warning(
                    "continuous(%s): returning SpeasyVariable shape=%s",
                    source.vp_path, tuple(out.values.shape),
                )
                counter("sciqlop_radio.continuous.points", out.values.size, cat="sciqlop_radio")
            return out
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_continuous.py sciqlop_radio/tests/test_continuous_cache.py \
            sciqlop_radio/tests/test_streams.py sciqlop_radio/tests/test_dock.py -q
```

Expected: PASS, including every pre-existing test in those four files.

- [ ] **Step 5: Commit**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add sciqlop_radio/sciqlop_radio/continuous.py \
        sciqlop_radio/sciqlop_radio/tests/test_continuous.py
git commit -m "feat(sciqlop_radio): background knobs on the continuous products"
```

---

### Task 4: Wire the knobs into the LOFAR LBA callback

**Files:**
- Modify: `sciqlop_radio/lofar.py` (imports near line 35; `_build_callback` at lines 292-341)
- Test: `sciqlop_radio/tests/test_lofar.py` (append; extend one existing test)

**Interfaces:**
- Consumes: `apply_background`, `BgMode`, `BgWindow`, `BgQ` from Tasks 1-2.
- Produces: `_build_callback(cache_dir)` now returns `lofar(start, stop, beam=0, sap=0, bg_mode='off', bg_window_s=0.0, bg_q=50.0)`.

- [ ] **Step 1: Write the failing test and extend the existing signature test**

In `sciqlop_radio/tests/test_lofar.py`, change the assertion in the existing `test_callback_signature_resolves_under_eval_str` from:

```python
    assert {"start", "stop", "beam", "sap"} <= set(sig.parameters)
```

to:

```python
    assert {"start", "stop", "beam", "sap",
            "bg_mode", "bg_window_s", "bg_q"} <= set(sig.parameters)
    assert [sig.parameters[n].annotation for n in ("start", "stop")] == [float, float]
```

Then append:

```python
def test_lofar_callback_exposes_beam_sap_and_background_knobs(tmp_path):
    """All five knobs must coexist — adding the background trio must not knock
    out the Beam/SAP pair that was already there."""
    knobs = pytest.importorskip("SciQLop.user_api.knobs")
    from sciqlop_radio.lofar import _build_callback

    specs = {s.name: s for s in knobs.extract_specs_from_callback(_build_callback(tmp_path))}
    assert set(specs) == {"beam", "sap", "bg_mode", "bg_window_s", "bg_q"}
    assert specs["beam"].default == 0
    assert specs["bg_mode"].default == "off"


def test_lofar_callback_applies_background_when_asked(monkeypatch, tmp_path):
    from sciqlop_radio import lofar

    from types import SimpleNamespace

    sentinel = SimpleNamespace(values=np.zeros((4, 3)))
    monkeypatch.setattr(lofar, "_entries_in_range",
                        lambda cache_dir, t0, t1, beam, sap: [object()])
    monkeypatch.setattr(lofar, "_fits_url_for_entry", lambda entry: "u")
    monkeypatch.setattr(lofar, "_read_lofar", lambda url: sentinel)
    monkeypatch.setattr("speasy.products.variable.merge", lambda variables: sentinel)
    seen = {}

    def _spy(variable, *, mode, window_s, q):
        seen.update(mode=mode, window_s=window_s, q=q)
        return variable

    monkeypatch.setattr(lofar, "apply_background", _spy)
    cb = lofar._build_callback(tmp_path)
    cb(0.0, 100.0, bg_mode="ratio", bg_window_s=45.0, bg_q=5.0)
    assert seen == {"mode": "ratio", "window_s": 45.0, "q": 5.0}
```

The sentinel carries a real `values` array because the callback's tail evaluates `counter("sciqlop_radio.lofar.points", result.values.size, ...)`. Patching `counter` to a no-op does **not** help — Python evaluates call arguments before the callee runs, so a bare `object()` raises `AttributeError` regardless. Do not add a `None`/attribute guard to `lofar.py` to work around this: unlike `continuous.py`, whose `_concat_spectrograms` genuinely returns `None`, `lofar.py` has no such path (`merge` has returned non-`None` by that line, and `apply_background` only returns `None` for `None` input), so a guard there would be dead code that misleads the next reader.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_lofar.py -q -k "signature or background or knobs"
```

Expected: FAIL — the signature assertion misses `bg_mode`, and `lofar.apply_background` does not exist.

- [ ] **Step 3: Wire it into `lofar.py`**

Add to the module-level imports, right after `from .tracing_compat import zone, traced, counter` (around line 35):

```python
from .background import BgMode, BgQ, BgWindow, apply_background
```

Change the nested callback signature in `_build_callback` from:

```python
    def lofar(
        start: float,
        stop: float,
        beam: Annotated[int, Knob(min=0, max=216, step=1, label="Beam")] = 0,
        sap: Annotated[int, Knob(min=0, max=1, step=1, label="SAP")] = 0,
    ):
```

to:

```python
    def lofar(
        start: float,
        stop: float,
        beam: Annotated[int, Knob(min=0, max=216, step=1, label="Beam")] = 0,
        sap: Annotated[int, Knob(min=0, max=1, step=1, label="SAP")] = 0,
        bg_mode: BgMode = 'off',
        bg_window_s: BgWindow = 0.0,
        bg_q: BgQ = 50.0,
    ):
```

Then replace the tail of the callback — the `try:`/`except` around `merge` and the two lines after it — with:

```python
            try:
                with zone("sciqlop_radio.lofar.merge", cat="sciqlop_radio", n_files=len(variables)):
                    result = merge(variables)
            except Exception as exc:  # noqa: BLE001
                log.warning("lofar: merge failed (%d var(s)): %s", len(variables), exc)
                return None
            result = apply_background(result, mode=bg_mode, window_s=bg_window_s, q=bg_q)
            counter("sciqlop_radio.lofar.points", result.values.size, cat="sciqlop_radio")
            return result
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_lofar.py -q
```

Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add sciqlop_radio/sciqlop_radio/lofar.py \
        sciqlop_radio/sciqlop_radio/tests/test_lofar.py
git commit -m "feat(sciqlop_radio): background knobs on the LOFAR LBA product"
```

---

### Task 5: Full-suite verification and a real-data check

**Files:**
- Create: (scratch only — nothing committed from the real-data script)
- Test: the whole `sciqlop_radio` suite

- [ ] **Step 1: Run the full suite**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/ -q -m "not live"
```

Expected: the 186-passed baseline plus the new tests, 5 skipped, **exit code 0**. Read the real pass/fail counts and the exit code — do not infer success from a grep. If anything regressed, fix it before continuing.

- [ ] **Step 2: Verify on real I-LOFAR data**

Write this to the scratchpad and run it. It needs no network — the files are already cached.

```python
import sys
sys.path.insert(0, '/var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio')
from pathlib import Path
import numpy as np
from sciqlop_radio.reader import open_spectrogram
from sciqlop_radio.plot import spectrogram_to_speasy_variable
from sciqlop_radio.background import apply_background

v = spectrogram_to_speasy_variable(open_spectrogram(
    Path.home() / '.cache/sciqlop_radio/20250726_130037_bst_00X.dat'))
raw = np.asarray(v.values)
print('shape', raw.shape, 'raw per-channel std', np.asarray(raw.mean(axis=0)).std())

for mode in ('diff', 'ratio', 'db'):
    out = apply_background(v, mode=mode)
    y = np.asarray(out.values)
    print(mode, 'std', float(np.nanstd(np.nanmean(y, axis=0))),
          'finite', float(np.isfinite(y).mean()),
          'UNITS', out.meta['UNITS'], 'SCALETYP', out.meta['SCALETYP'])

sliding = apply_background(v, mode='db', window_s=300.0, q=10.0)
print('sliding shape', sliding.values.shape,
      'finite', float(np.isfinite(np.asarray(sliding.values)).mean()))
assert apply_background(v, mode='off') is v
```

Expected: shape `(3565, 488)`; the raw per-channel **std** is ~4.3e7 and the `db` std collapses to ~0.31; every mode stays finite; `UNITS`/`SCALETYP` match the table in Task 2; the sliding call returns the same shape. If `20250726_130037_bst_00X.dat` is missing, any other `~/.cache/sciqlop_radio/20250726_*_bst_00X.dat` file works.

Use **std**, not `np.ptp`. The earlier phase's 4.3e7 → 0.31 dB figures are standard deviations across channels; `ptp` on the same data reads 7.07e8 → 5.36, because max−min is dominated by a handful of permanently-hot RFI channels (worst: channel 29 at 4.1 dB). Both metrics describe a working transform, but only std is comparable to the recorded baseline — and the `ptp` outliers are exactly what the deferred RFI-flagging work targets.

- [ ] **Step 3: Confirm the knobs render in the running app**

Launch SciQLop, drag `radio/ilofar/X` onto a panel, and check the inspector shows **Background**, **BG window** and **BG percentile** alongside the existing controls. Switch Background to `db` and confirm the plot re-fetches and the bandpass band disappears. Also confirm **no** "missing type hints" warning appears in the log widget — that warning is the second half of the module-globals trap.

This is a manual check. If SciQLop cannot be launched in this session, say so explicitly in the completion report rather than claiming it passed.

- [ ] **Step 4: Commit any fixes from Steps 1-3**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add -A sciqlop_radio/
git commit -m "test(sciqlop_radio): verify background knobs on real I-LOFAR data"
```

Skip this commit if Steps 1-3 needed no changes.

---

## Notes for the implementer

- **Do not push.** Pushing is always an explicit request from the user. All three repos are already several commits ahead of their remotes.
- The plugin's tests stub `SciQLop.*` with `MagicMock` only when the real import fails (`tests/conftest.py:64-72`). In the documented venv the real modules import, so `pytest.importorskip` guards are for other environments, not this one.
- `sciqlop_radio` has no CHANGELOG and its README documents no knobs. Do not add either.
- If a task's test does not fail at its Step 2, stop — the test is not testing what it claims to.
