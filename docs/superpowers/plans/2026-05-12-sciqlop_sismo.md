# sciqlop_sismo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a SciQLop plugin that produces seismic waveform / spectrogram products as Speasy `SpeasyVariable`s via FDSN web services (ObsPy `RoutingClient`), with a thin browser dock that discovers channels and adds them to the provider's inventory. All plotting goes to the SciQLop main timeline; no plots live inside the dock.

**Architecture:** A `SismoProvider(speasy.core.dataprovider.DataProvider)` exposes one dataset per NSLC channel (e.g. `sismo/G/SSB/00.HHZ`) with three parameters — `waveform`, `raw`, `spectrogram`. Pure-function I/O / processing / variable-building modules feed the provider. The `SismoBrowserDock` runs FDSN searches on `QThreadPool` workers and calls `provider.add_channel(...)` to register results. Detailed spec: `docs/superpowers/specs/2026-05-12-sciqlop_sismo-design.md`.

**Tech Stack:** Python ≥3.10, ObsPy ≥1.4, Speasy ≥1.7, NumPy, SciPy, PySide6, pydantic ≥2, PyYAML, pytest, pytest-qt.

---

## File Structure

```
sciqlop_sismo/
├── pyproject.toml
├── README.md
└── sciqlop_sismo/
    ├── __init__.py             # load(main_window) entry point
    ├── provider.py             # SismoProvider(DataProvider)
    ├── fdsn_client.py          # ObsPy RoutingClient wrapper (no Qt, no Speasy)
    ├── process.py              # pure fns: detrend, bandpass, default_pipeline
    ├── stream_to_variable.py   # Stream → SpeasyVariable (waveform + spectrogram)
    ├── local_files.py          # obspy.read(path) helpers
    ├── settings.py             # pydantic settings with field_validator clamping
    ├── dock.py                 # SismoBrowserDock shell + shared util
    ├── dock_stations.py        # Stations tab
    ├── dock_events.py          # Events tab
    ├── dock_local.py           # Local files tab
    └── tests/
        ├── __init__.py
        ├── conftest.py
        ├── test_load.py
        ├── test_settings.py
        ├── test_process.py
        ├── test_stream_to_variable.py
        ├── test_local_files.py
        ├── test_fdsn_client.py
        ├── test_fdsn_client_live.py
        ├── test_provider.py
        └── test_dock.py
```

Bottom-up build order: pure modules → provider → dock → plugin entry. Each task adds one focused file (or extends a file with one focused responsibility) and ends with a green test run + commit.

---

## Task 1: Scaffold the package

**Files:**
- Create: `sciqlop_sismo/pyproject.toml`
- Create: `sciqlop_sismo/sciqlop_sismo/__init__.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/__init__.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/conftest.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/test_load.py`
- Create: `sciqlop_sismo/README.md`

- [ ] **Step 1: Create the package directory structure**

```bash
mkdir -p sciqlop_sismo/sciqlop_sismo/tests
```

- [ ] **Step 2: Write `sciqlop_sismo/pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "sciqlop-sismo"
version = "0.1.0"
description = "SciQLop plugin for FDSN/ObsPy seismic waveforms"
requires-python = ">=3.10"
dependencies = [
    "obspy>=1.4",
    "speasy>=1.7",
    "numpy",
    "scipy",
    "pydantic>=2",
    "PyYAML",
]

[project.optional-dependencies]
test = ["pytest", "pytest-qt"]

[project.entry-points."sciqlop.plugins"]
sciqlop_sismo = "sciqlop_sismo"

[tool.setuptools.packages.find]
include = ["sciqlop_sismo*"]
```

- [ ] **Step 3: Write `sciqlop_sismo/README.md`**

```markdown
# sciqlop_sismo

SciQLop plugin for seismic waveforms.

Produces `SpeasyVariable` products from FDSN web services (via ObsPy
`RoutingClient`). Each NSLC channel is exposed as three parameters in
the `sismo/` Speasy tree: `waveform` (preprocessed time-series),
`raw` (instrument counts) and `spectrogram` (2-D time × frequency).

The dock is a *browser* — it discovers channels and adds them to the
inventory. Plotting happens on the SciQLop main timeline via drag-drop
or `panel.plot_product(uid)`.

Design: `docs/superpowers/specs/2026-05-12-sciqlop_sismo-design.md`
```

- [ ] **Step 4: Write `sciqlop_sismo/sciqlop_sismo/__init__.py`**

```python
"""sciqlop_sismo — FDSN/ObsPy seismology browser for SciQLop."""
from __future__ import annotations

__version__ = "0.1.0"


def load(main_window):
    """SciQLop plugin entry point.

    Filled in by a later task. For now a no-op so the entry point
    resolves and the smoke test passes.
    """
    return None
```

- [ ] **Step 5: Write `sciqlop_sismo/sciqlop_sismo/tests/__init__.py`** (empty)

```python
```

- [ ] **Step 6: Write `sciqlop_sismo/sciqlop_sismo/tests/conftest.py`**

```python
"""Local conftest: stub Qt-only imports + atexit segfault workaround.

The root conftest already stubs PySide6 modules for tests that don't
need a real Qt environment. We add the os._exit workaround per
`feedback_sciqlopplots_exit_segfault` so pytest doesn't segfault on
exit when SciQLopPlots has been imported.
"""
import atexit
import os


def _force_exit():
    os._exit(0)


# Registered last → runs first during interpreter teardown.
atexit.register(_force_exit)
```

- [ ] **Step 7: Write the failing smoke test `sciqlop_sismo/sciqlop_sismo/tests/test_load.py`**

```python
"""Smoke test: the plugin entry point resolves and load() is callable."""
from unittest.mock import MagicMock

import sciqlop_sismo


def test_version_is_set():
    assert sciqlop_sismo.__version__ == "0.1.0"


def test_load_callable_with_mock_main_window():
    main_window = MagicMock()
    result = sciqlop_sismo.load(main_window)
    assert result is None  # Will be a panel after Task 13.


def test_entry_point_resolves():
    from importlib.metadata import entry_points
    eps = entry_points(group="sciqlop.plugins")
    names = {ep.name for ep in eps}
    assert "sciqlop_sismo" in names
```

- [ ] **Step 8: Install the package editable, then run the smoke test**

Run:
```bash
pip install -e sciqlop_sismo[test]
pytest sciqlop_sismo/sciqlop_sismo/tests/test_load.py -v
```
Expected: 3 passed.

- [ ] **Step 9: Commit**

```bash
git add sciqlop_sismo/
git commit -m "feat(sciqlop_sismo): scaffold package with smoke test"
```

---

## Task 2: Settings module

**Files:**
- Create: `sciqlop_sismo/sciqlop_sismo/settings.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/test_settings.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for sciqlop_sismo.settings."""
from pathlib import Path

import pytest

from sciqlop_sismo.settings import SismoSettings


def test_defaults_are_sane():
    s = SismoSettings()
    assert s.default_routing == "iris-federator"
    assert s.bandpass_min_hz == pytest.approx(0.01)
    assert s.bandpass_max_hz == pytest.approx(10.0)
    assert s.cache_retention_days == 7
    assert s.stationxml_cache_hours == 12
    assert s.search_timeout_s == 60
    assert s.fetch_timeout_s == 120
    assert isinstance(s.cache_dir, Path)


def test_bandpass_clamped_when_out_of_range():
    # min < 0 → clamped to 0; max > 1000 → clamped to 1000.
    s = SismoSettings(bandpass_min_hz=-1, bandpass_max_hz=99999)
    assert s.bandpass_min_hz == 0.0
    assert s.bandpass_max_hz == 1000.0


def test_bandpass_min_below_max_after_clamp():
    # If user passes inverted band, clamp + swap so min <= max.
    s = SismoSettings(bandpass_min_hz=20, bandpass_max_hz=5)
    assert s.bandpass_min_hz == 5.0
    assert s.bandpass_max_hz == 20.0


def test_cache_retention_clamped():
    s = SismoSettings(cache_retention_days=-3)
    assert s.cache_retention_days == 0
    s2 = SismoSettings(cache_retention_days=99999)
    assert s2.cache_retention_days == 365


def test_routing_is_lowercased():
    s = SismoSettings(default_routing="IRIS-Federator")
    assert s.default_routing == "iris-federator"


def test_cache_dir_defaults_to_user_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    s = SismoSettings()
    assert s.cache_dir == tmp_path / "sciqlop" / "sismo"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_settings.py -v
```
Expected: ImportError (`SismoSettings` does not exist yet).

- [ ] **Step 3: Implement `sciqlop_sismo/sciqlop_sismo/settings.py`**

```python
"""Project-wide settings for sciqlop_sismo.

Bounded numeric fields clamp on load (per `feedback_configentry_clamp_bounds`)
so stale YAML never crashes a panel.
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator


def _default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "sciqlop" / "sismo"


class SismoSettings(BaseModel):
    default_routing: str = Field(default="iris-federator")
    bandpass_min_hz: float = Field(default=0.01)
    bandpass_max_hz: float = Field(default=10.0)
    cache_retention_days: int = Field(default=7)
    stationxml_cache_hours: int = Field(default=12)
    search_timeout_s: int = Field(default=60)
    fetch_timeout_s: int = Field(default=120)
    cache_dir: Path = Field(default_factory=_default_cache_dir)

    @field_validator("default_routing", mode="before")
    @classmethod
    def _lowercase_routing(cls, v):
        return str(v).lower()

    @field_validator("bandpass_min_hz", "bandpass_max_hz", mode="before")
    @classmethod
    def _clamp_band(cls, v):
        return max(0.0, min(1000.0, float(v)))

    @field_validator("cache_retention_days", mode="before")
    @classmethod
    def _clamp_retention(cls, v):
        return max(0, min(365, int(v)))

    @field_validator("stationxml_cache_hours", mode="before")
    @classmethod
    def _clamp_xml_hours(cls, v):
        return max(0, min(24 * 30, int(v)))

    @field_validator("search_timeout_s", "fetch_timeout_s", mode="before")
    @classmethod
    def _clamp_timeout(cls, v):
        return max(1, min(3600, int(v)))

    @model_validator(mode="after")
    def _swap_band_if_inverted(self):
        if self.bandpass_min_hz > self.bandpass_max_hz:
            self.bandpass_min_hz, self.bandpass_max_hz = (
                self.bandpass_max_hz,
                self.bandpass_min_hz,
            )
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_settings.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/settings.py sciqlop_sismo/sciqlop_sismo/tests/test_settings.py
git commit -m "feat(sciqlop_sismo): pydantic settings with clamping validators"
```

---

## Task 3: Processing pipeline (pure functions on `obspy.Stream`)

**Files:**
- Create: `sciqlop_sismo/sciqlop_sismo/process.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/test_process.py`

- [ ] **Step 1: Write the failing tests**

```python
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
    assert out is not Stream([tr])  # detrend returns a new Stream
    assert np.mean(out[0].data) == pytest.approx(0.0, abs=1e-9)


def test_detrend_preserves_oscillation():
    n = 1000
    t = np.arange(n) / 100.0
    signal = np.sin(2 * np.pi * 1.0 * t)
    tr = _synthetic_trace(signal + 5.0)
    out = detrend(Stream([tr]))
    # Amplitude of the 1 Hz component is roughly preserved.
    assert out[0].data.max() == pytest.approx(1.0, abs=0.05)
    assert out[0].data.min() == pytest.approx(-1.0, abs=0.05)


def test_bandpass_attenuates_out_of_band():
    n = 4096
    sr = 100.0
    t = np.arange(n) / sr
    low = np.sin(2 * np.pi * 0.05 * t)   # below band
    mid = np.sin(2 * np.pi * 2.0 * t)    # in band
    high = np.sin(2 * np.pi * 40.0 * t)  # above band
    tr = _synthetic_trace(low + mid + high)
    out = bandpass(Stream([tr]), fmin=1.0, fmax=10.0)
    # In-band amplitude survives; out-of-band is suppressed.
    assert np.max(np.abs(out[0].data)) > 0.7
    # Crude spectrum check at high frequency: rfft amplitude at 40 Hz << at 2 Hz.
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_process.py -v
```
Expected: ImportError for `sciqlop_sismo.process`.

- [ ] **Step 3: Implement `sciqlop_sismo/sciqlop_sismo/process.py`**

```python
"""Minimal seismic preprocessing.

Pure functions that take an `obspy.Stream` and return a NEW
`Stream` — they never mutate the input. Compositions are explicit
(see `default_pipeline`). No Qt, no Speasy, no network.
"""
from __future__ import annotations

from obspy import Stream

from .settings import SismoSettings


def detrend(stream: Stream, type: str = "demean") -> Stream:
    """Remove the mean (or linear trend) from every trace.

    `type` is forwarded to `obspy.Trace.detrend` — typical values:
    `"demean"`, `"linear"`, `"polynomial"`. Default `"demean"` is
    sufficient for casual inspection; users who care about long-period
    drift should pass `"linear"`.
    """
    out = stream.copy()
    for tr in out:
        tr.detrend(type=type)
    return out


def bandpass(stream: Stream, fmin: float, fmax: float, corners: int = 4) -> Stream:
    """Zero-phase Butterworth bandpass on every trace."""
    out = stream.copy()
    for tr in out:
        tr.filter("bandpass", freqmin=fmin, freqmax=fmax, corners=corners, zerophase=True)
    return out


def default_pipeline(stream: Stream, settings: SismoSettings) -> Stream:
    """Minimal-but-sane defaults: demean + project-wide bandpass."""
    return bandpass(
        detrend(stream, type="demean"),
        fmin=settings.bandpass_min_hz,
        fmax=settings.bandpass_max_hz,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_process.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/process.py sciqlop_sismo/sciqlop_sismo/tests/test_process.py
git commit -m "feat(sciqlop_sismo): pure-function detrend/bandpass/default_pipeline"
```

---

## Task 4: Stream → SpeasyVariable translator

**Files:**
- Create: `sciqlop_sismo/sciqlop_sismo/stream_to_variable.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/test_stream_to_variable.py`

- [ ] **Step 1: Write the failing tests**

```python
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
    # Spacing should match sampling_rate (50 Hz → 0.02 s).
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
    assert var.values.shape[1] == 256 // 2 + 1  # rfft bin count
    # Frequency axis is the second axis, monotone non-negative.
    freq_axis = var.axes[1].values
    assert freq_axis[0] == pytest.approx(0.0)
    assert np.all(np.diff(freq_axis) > 0)


def test_spectrogram_variable_no_nan():
    tr = _synthetic_trace(npts=4096)
    var = spectrogram_from_stream(Stream([tr]), channel="HHZ")
    assert not np.any(np.isnan(var.values))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_stream_to_variable.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `sciqlop_sismo/sciqlop_sismo/stream_to_variable.py`**

```python
"""Translate ObsPy Streams to SpeasyVariable.

Pure functions. No Qt, no Speasy provider, no network. The output is
ready to drop onto a SciQLop panel (the provider exposes these
variables through `get_data`).
"""
from __future__ import annotations

import numpy as np
from obspy import Stream
from scipy.signal import spectrogram as _scipy_spectrogram
from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
from speasy.products.variable import SpeasyVariable


def _pick_trace(stream: Stream, channel: str):
    for tr in stream:
        if tr.stats.channel == channel:
            return tr
    raise KeyError(f"channel {channel!r} not found in stream")


def _trace_time_axis(tr) -> VariableTimeAxis:
    n = tr.stats.npts
    dt = tr.stats.delta
    start_ns = int(tr.stats.starttime.timestamp * 1e9)
    step_ns = int(round(dt * 1e9))
    epochs_ns = start_ns + np.arange(n, dtype=np.int64) * step_ns
    return VariableTimeAxis(values=epochs_ns.astype("datetime64[ns]"))


def stream_to_speasy_variable(
    stream: Stream, channel: str, units: str
) -> SpeasyVariable:
    """Convert one channel of a Stream to a 1-D `SpeasyVariable`."""
    tr = _pick_trace(stream, channel)
    nslc = ".".join(
        (tr.stats.network, tr.stats.station, tr.stats.location, tr.stats.channel)
    )
    time_axis = _trace_time_axis(tr)
    values = DataContainer(
        values=tr.data.astype(np.float64).reshape(-1, 1),
        meta={"UNITS": units},
        name=nslc,
    )
    return SpeasyVariable(axes=[time_axis], values=values, columns=[channel])


def spectrogram_from_stream(
    stream: Stream,
    channel: str,
    nperseg: int = 256,
    noverlap: int = 128,
) -> SpeasyVariable:
    """Compute STFT power spectrogram for one channel.

    Returns a 2-D `SpeasyVariable` with axis[0] = time and
    axis[1] = frequency (Hz). Power is dB (10·log10).
    """
    tr = _pick_trace(stream, channel)
    sr = float(tr.stats.sampling_rate)
    f, t_rel, sxx = _scipy_spectrogram(
        tr.data.astype(np.float64),
        fs=sr,
        nperseg=nperseg,
        noverlap=noverlap,
        scaling="density",
        mode="psd",
    )
    sxx = np.where(sxx > 0, sxx, np.finfo(np.float64).tiny)
    sxx_db = 10.0 * np.log10(sxx)

    start_ns = int(tr.stats.starttime.timestamp * 1e9)
    epochs_ns = start_ns + (t_rel * 1e9).astype(np.int64)
    time_axis = VariableTimeAxis(values=epochs_ns.astype("datetime64[ns]"))
    freq_axis = VariableAxis(
        name="frequency",
        values=f.astype(np.float64),
        meta={"UNITS": "Hz"},
    )
    nslc = ".".join(
        (tr.stats.network, tr.stats.station, tr.stats.location, tr.stats.channel)
    )
    values = DataContainer(
        values=sxx_db.T,  # shape (n_time, n_freq)
        meta={"UNITS": "dB"},
        name=f"{nslc}.spectrogram",
    )
    return SpeasyVariable(axes=[time_axis, freq_axis], values=values, columns=[channel])
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_stream_to_variable.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/stream_to_variable.py sciqlop_sismo/sciqlop_sismo/tests/test_stream_to_variable.py
git commit -m "feat(sciqlop_sismo): Stream → SpeasyVariable (waveform + spectrogram)"
```

---

## Task 5: Local-file reader

**Files:**
- Create: `sciqlop_sismo/sciqlop_sismo/local_files.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/test_local_files.py`

- [ ] **Step 1: Write the failing tests**

```python
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
    # 1000 samples at 100 Hz → 10 s duration (end inclusive of last sample).
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
    # 40-char hex sha1 after the prefix.
    assert info.routing.startswith("local:")
    suffix = info.routing.removeprefix("local:")
    assert len(suffix) == 40
    int(suffix, 16)  # raises if not hex
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_local_files.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `sciqlop_sismo/sciqlop_sismo/local_files.py`**

```python
"""Read local miniSEED / SAC files into channel descriptors.

Channel descriptors are pure data (`ChannelInfo`); injecting them into
the Speasy provider's inventory is the provider's job (Task 7).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import obspy


@dataclass(frozen=True)
class ChannelInfo:
    network: str
    station: str
    location: str
    channel: str
    sampling_rate_hz: float
    start_date: datetime
    stop_date: datetime
    routing: str
    path: Path | None = None


def _to_aware_utc(utc_dt: obspy.UTCDateTime) -> datetime:
    return datetime.fromtimestamp(utc_dt.timestamp, tz=timezone.utc)


def _sha1_of_path(p: Path) -> str:
    return hashlib.sha1(str(p.resolve()).encode("utf-8")).hexdigest()


def import_file(path: Path) -> List[ChannelInfo]:
    """Read a miniSEED / SAC file and return one ChannelInfo per channel."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    stream = obspy.read(str(p))
    routing = f"local:{_sha1_of_path(p)}"
    out: List[ChannelInfo] = []
    seen: set[tuple[str, str, str, str]] = set()
    for tr in stream:
        st = tr.stats
        key = (st.network, st.station, st.location, st.channel)
        if key in seen:
            continue
        seen.add(key)
        out.append(ChannelInfo(
            network=st.network,
            station=st.station,
            location=st.location,
            channel=st.channel,
            sampling_rate_hz=float(st.sampling_rate),
            start_date=_to_aware_utc(st.starttime),
            stop_date=_to_aware_utc(st.endtime),
            routing=routing,
            path=p,
        ))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_local_files.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/local_files.py sciqlop_sismo/sciqlop_sismo/tests/test_local_files.py
git commit -m "feat(sciqlop_sismo): import_file → ChannelInfo descriptors"
```

---

## Task 6: FDSN client wrapper

**Files:**
- Create: `sciqlop_sismo/sciqlop_sismo/fdsn_client.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/test_fdsn_client.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/test_fdsn_client_live.py`

- [ ] **Step 1: Write the failing mocked tests**

```python
"""Tests for sciqlop_sismo.fdsn_client (no real network)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from obspy import Inventory, Stream, Trace, UTCDateTime
from obspy.core.inventory import Channel, Network, Station

from sciqlop_sismo.fdsn_client import (
    fetch_stream,
    search_events,
    search_stations,
)


def _utc(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


@pytest.fixture
def fake_stream():
    tr = Trace(
        data=np.zeros(100, dtype=np.float32),
        header={
            "network": "IU", "station": "ANMO", "location": "00",
            "channel": "BHZ", "sampling_rate": 40.0,
            "starttime": UTCDateTime("2026-01-01T00:00:00"),
        },
    )
    return Stream([tr])


def test_fetch_stream_uses_routing_client_by_default(fake_stream):
    with patch("sciqlop_sismo.fdsn_client.RoutingClient") as RC:
        client = MagicMock()
        client.get_waveforms.return_value = fake_stream
        RC.return_value = client
        out = fetch_stream(
            ("IU", "ANMO", "00", "BHZ"),
            _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1),
            routing="iris-federator",
        )
    RC.assert_called_once_with("iris-federator")
    client.get_waveforms.assert_called_once()
    args, kwargs = client.get_waveforms.call_args
    assert kwargs["network"] == "IU"
    assert kwargs["station"] == "ANMO"
    assert kwargs["location"] == "00"
    assert kwargs["channel"] == "BHZ"
    assert isinstance(kwargs["starttime"], UTCDateTime)
    assert isinstance(kwargs["endtime"], UTCDateTime)
    assert out is fake_stream


def test_fetch_stream_uses_single_center_when_routing_is_a_center_code(fake_stream):
    with patch("sciqlop_sismo.fdsn_client.Client") as Cl, \
         patch("sciqlop_sismo.fdsn_client.RoutingClient") as RC:
        client = MagicMock()
        client.get_waveforms.return_value = fake_stream
        Cl.return_value = client
        fetch_stream(
            ("IU", "ANMO", "00", "BHZ"),
            _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1),
            routing="IRIS",
        )
    Cl.assert_called_once_with("IRIS")
    RC.assert_not_called()


def test_fetch_stream_raises_on_empty_result():
    with patch("sciqlop_sismo.fdsn_client.RoutingClient") as RC:
        client = MagicMock()
        client.get_waveforms.return_value = Stream([])
        RC.return_value = client
        with pytest.raises(RuntimeError, match="no data"):
            fetch_stream(
                ("IU", "ANMO", "00", "BHZ"),
                _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1),
                routing="iris-federator",
            )


def test_search_stations_forwards_filters_and_returns_inventory():
    inv = Inventory(networks=[Network(code="IU")], source="test")
    with patch("sciqlop_sismo.fdsn_client.RoutingClient") as RC:
        client = MagicMock()
        client.get_stations.return_value = inv
        RC.return_value = client
        out = search_stations(
            network="IU", station="ANMO", location="00", channel="BHZ",
            start_time=_utc(2026, 1, 1), end_time=_utc(2026, 1, 2),
            routing="iris-federator",
        )
    assert out is inv
    args, kwargs = client.get_stations.call_args
    assert kwargs["level"] == "channel"
    assert kwargs["network"] == "IU"


def test_search_stations_passes_geographic_filters_when_given():
    with patch("sciqlop_sismo.fdsn_client.RoutingClient") as RC:
        client = MagicMock()
        client.get_stations.return_value = Inventory(networks=[], source="t")
        RC.return_value = client
        search_stations(
            network="*", station="*", location="*", channel="HHZ",
            start_time=_utc(2026, 1, 1), end_time=_utc(2026, 1, 2),
            routing="iris-federator",
            latitude=45.0, longitude=5.0,
            min_radius_deg=0.0, max_radius_deg=30.0,
        )
    kwargs = client.get_stations.call_args.kwargs
    assert kwargs["latitude"] == 45.0
    assert kwargs["longitude"] == 5.0
    assert kwargs["minradius"] == 0.0
    assert kwargs["maxradius"] == 30.0


def test_search_events_returns_catalog():
    sentinel_catalog = MagicMock()
    with patch("sciqlop_sismo.fdsn_client.Client") as Cl:
        client = MagicMock()
        client.get_events.return_value = sentinel_catalog
        Cl.return_value = client
        out = search_events(
            start_time=_utc(2026, 1, 1), end_time=_utc(2026, 1, 2),
            min_magnitude=5.0, provider="USGS",
        )
    Cl.assert_called_once_with("USGS")
    args, kwargs = client.get_events.call_args
    assert kwargs["minmagnitude"] == 5.0
    assert out is sentinel_catalog
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_fdsn_client.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `sciqlop_sismo/sciqlop_sismo/fdsn_client.py`**

```python
"""Thin wrapper around ObsPy's FDSN clients.

`routing` is a string:
  - "iris-federator" or "eida-routing" → `RoutingClient`
  - any other value (e.g. "IRIS", "RESIF", "GEOFON") → `Client`
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from obspy import Stream, UTCDateTime
from obspy.clients.fdsn import Client, RoutingClient

_KNOWN_ROUTERS = {"iris-federator", "eida-routing"}


def _client_for(routing: str):
    if routing.lower() in _KNOWN_ROUTERS:
        return RoutingClient(routing.lower())
    return Client(routing)


def _to_utc(dt: datetime) -> UTCDateTime:
    return UTCDateTime(dt.timestamp())


def fetch_stream(
    nslc: Tuple[str, str, str, str],
    start_time: datetime,
    end_time: datetime,
    routing: str = "iris-federator",
) -> Stream:
    """Fetch waveforms for one NSLC tuple. Raises if the result is empty."""
    net, sta, loc, chan = nslc
    client = _client_for(routing)
    stream = client.get_waveforms(
        network=net, station=sta, location=loc, channel=chan,
        starttime=_to_utc(start_time), endtime=_to_utc(end_time),
    )
    if len(stream) == 0:
        raise RuntimeError(
            f"no data returned for {net}.{sta}.{loc}.{chan} "
            f"between {start_time.isoformat()} and {end_time.isoformat()} (routing={routing})"
        )
    return stream


def search_stations(
    network: str, station: str, location: str, channel: str,
    start_time: datetime, end_time: datetime,
    routing: str = "iris-federator",
    *,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    min_radius_deg: Optional[float] = None,
    max_radius_deg: Optional[float] = None,
):
    """Query the FDSN station service at channel level."""
    client = _client_for(routing)
    kwargs = dict(
        network=network, station=station, location=location, channel=channel,
        starttime=_to_utc(start_time), endtime=_to_utc(end_time),
        level="channel",
    )
    if latitude is not None and longitude is not None:
        kwargs["latitude"] = latitude
        kwargs["longitude"] = longitude
    if min_radius_deg is not None:
        kwargs["minradius"] = min_radius_deg
    if max_radius_deg is not None:
        kwargs["maxradius"] = max_radius_deg
    return client.get_stations(**kwargs)


def search_events(
    start_time: datetime, end_time: datetime,
    *,
    min_magnitude: Optional[float] = None,
    min_lat: Optional[float] = None, max_lat: Optional[float] = None,
    min_lon: Optional[float] = None, max_lon: Optional[float] = None,
    latitude: Optional[float] = None, longitude: Optional[float] = None,
    min_radius_deg: Optional[float] = None, max_radius_deg: Optional[float] = None,
    provider: str = "USGS",
):
    """Query an FDSN event service. `provider` is an FDSN-event center."""
    client = Client(provider)
    kwargs = dict(starttime=_to_utc(start_time), endtime=_to_utc(end_time))
    if min_magnitude is not None:
        kwargs["minmagnitude"] = min_magnitude
    if min_lat is not None: kwargs["minlatitude"] = min_lat
    if max_lat is not None: kwargs["maxlatitude"] = max_lat
    if min_lon is not None: kwargs["minlongitude"] = min_lon
    if max_lon is not None: kwargs["maxlongitude"] = max_lon
    if latitude is not None: kwargs["latitude"] = latitude
    if longitude is not None: kwargs["longitude"] = longitude
    if min_radius_deg is not None: kwargs["minradius"] = min_radius_deg
    if max_radius_deg is not None: kwargs["maxradius"] = max_radius_deg
    return client.get_events(**kwargs)
```

- [ ] **Step 4: Run mocked tests to verify they pass**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_fdsn_client.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Write `sciqlop_sismo/sciqlop_sismo/tests/test_fdsn_client_live.py` (skipped by default)**

```python
"""Live FDSN tests — disabled by default, run with `pytest -m live`."""
from datetime import datetime, timedelta, timezone

import pytest

from sciqlop_sismo.fdsn_client import fetch_stream, search_stations

pytestmark = pytest.mark.live


def test_live_fetch_iris_anmo():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(seconds=30)
    stream = fetch_stream(("IU", "ANMO", "00", "BHZ"), t0, t1, routing="IRIS")
    assert len(stream) >= 1
    assert stream[0].stats.sampling_rate > 0


def test_live_search_stations_iris():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t1 = t0 + timedelta(days=1)
    inv = search_stations(
        network="IU", station="ANMO", location="00", channel="BHZ",
        start_time=t0, end_time=t1, routing="IRIS",
    )
    assert len(inv.networks) >= 1
```

- [ ] **Step 6: Register the `live` marker**

Modify `sciqlop_sismo/pyproject.toml` — append at end:

```toml
[tool.pytest.ini_options]
markers = ["live: tests that hit real FDSN data centers (slow; skipped by default)"]
addopts = "-m 'not live'"
```

- [ ] **Step 7: Confirm the live tests are skipped**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/ -v
```
Expected: `test_fdsn_client_live.py` lines show "deselected"; all other tests pass.

- [ ] **Step 8: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/fdsn_client.py sciqlop_sismo/sciqlop_sismo/tests/test_fdsn_client.py sciqlop_sismo/sciqlop_sismo/tests/test_fdsn_client_live.py sciqlop_sismo/pyproject.toml
git commit -m "feat(sciqlop_sismo): FDSN client (RoutingClient + per-center) with live test marker"
```

---

## Task 7: SismoProvider — inventory, get_data dispatch

**Files:**
- Create: `sciqlop_sismo/sciqlop_sismo/provider.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/test_provider.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for sciqlop_sismo.provider — Speasy DataProvider integration."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime
from speasy.core.inventory.indexes import DatasetIndex, ParameterIndex
from speasy.products.variable import SpeasyVariable

from sciqlop_sismo.provider import SismoProvider
from sciqlop_sismo.local_files import ChannelInfo


@pytest.fixture
def provider(tmp_path, monkeypatch):
    # Persist inventory under tmp_path to avoid touching the real ~/.config.
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
    # No parameters before any add_channel call.
    assert len(tree.parameters) == 0


def test_add_channel_creates_dataset_and_three_parameters(provider):
    provider.add_channel(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    flat = provider.flat_inventory
    # Three parameters: waveform / raw / spectrogram.
    chan_params = [
        uid for uid in flat.parameters
        if uid.startswith("sismo/G/SSB/00.HHZ/")
    ]
    assert set(p.rsplit("/", 1)[-1] for p in chan_params) == {
        "waveform", "raw", "spectrogram",
    }
    # The dataset exists too.
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
    assert var.unit == "m/s"  # default pipeline → m/s units label
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
    fs.assert_not_called()  # local files must not hit the network
    assert var.values.shape[0] == 500


def test_inventory_persisted_to_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIQLOP_SISMO_INVENTORY_DIR", str(tmp_path))
    p1 = SismoProvider()
    p1.add_channel(
        network="G", station="SSB", location="00", channel="HHZ",
        start_date=_utc(2020, 1, 1), stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0, routing="iris-federator",
    )
    # Reload: a new provider instance should see the channel.
    p2 = SismoProvider()
    assert "sismo/G/SSB/00.HHZ" in p2.flat_inventory.datasets
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_provider.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement `sciqlop_sismo/sciqlop_sismo/provider.py`**

```python
"""Speasy provider for FDSN seismic waveforms."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from speasy.core import AllowedKwargs, AnyDateTimeType
from speasy.core.dataprovider import (
    GET_DATA_ALLOWED_KWARGS,
    DataProvider,
)
from speasy.core.inventory.indexes import (
    DatasetIndex,
    ParameterIndex,
    SpeasyIndex,
)
from speasy.products.variable import SpeasyVariable

from .fdsn_client import fetch_stream
from .local_files import ChannelInfo, import_file
from .process import default_pipeline
from .settings import SismoSettings
from .stream_to_variable import (
    spectrogram_from_stream,
    stream_to_speasy_variable,
)

PROVIDER_NAME = "sismo"


def _inventory_dir() -> Path:
    override = os.environ.get("SCIQLOP_SISMO_INVENTORY_DIR")
    if override:
        return Path(override)
    return Path.home() / ".config" / "sciqlop" / "sismo"


def _inventory_path() -> Path:
    return _inventory_dir() / "inventory.yaml"


def _to_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso_utc(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class SismoProvider(DataProvider):
    """FDSN waveforms exposed as Speasy variables.

    One channel → one DatasetIndex → three ParameterIndex children
    (`waveform`, `raw`, `spectrogram`).
    """

    def __init__(self, settings: Optional[SismoSettings] = None):
        self._settings = settings or SismoSettings()
        self._pending_records: list[dict] = []
        DataProvider.__init__(
            self,
            provider_name=PROVIDER_NAME,
            provider_alt_names=["seismic", "fdsn"],
            inventory_disable_proxy=True,
        )

    # ----- DataProvider hooks ------------------------------------------------

    def build_inventory(self, root: SpeasyIndex) -> SpeasyIndex:
        for record in self._load_persisted_records():
            self._materialize_record(root, record)
        return root

    @AllowedKwargs(GET_DATA_ALLOWED_KWARGS)
    def get_data(
        self,
        product,
        start_time: AnyDateTimeType,
        stop_time: AnyDateTimeType,
        **kwargs,
    ) -> Optional[SpeasyVariable]:
        param = self._to_parameter_index(product)
        meta = param.__dict__
        kind = meta.get("kind")
        nslc = tuple(meta["nslc"])
        routing = meta.get("routing", "iris-federator")
        t0 = self._coerce_datetime(start_time)
        t1 = self._coerce_datetime(stop_time)
        stream = self._fetch_stream_for_meta(meta, nslc, t0, t1, routing)
        channel = nslc[3]
        if kind == "raw":
            return stream_to_speasy_variable(stream, channel=channel, units="counts")
        if kind == "waveform":
            processed = default_pipeline(stream, self._settings)
            return stream_to_speasy_variable(processed, channel=channel, units="m/s")
        if kind == "spectrogram":
            processed = default_pipeline(stream, self._settings)
            return spectrogram_from_stream(processed, channel=channel)
        raise ValueError(f"unknown kind: {kind!r}")

    # ----- Public API for the dock ------------------------------------------

    def add_channel(
        self,
        network: str,
        station: str,
        location: str,
        channel: str,
        start_date: datetime,
        stop_date: datetime,
        sampling_rate_hz: float,
        routing: str = "iris-federator",
    ) -> None:
        record = {
            "network": network, "station": station, "location": location,
            "channel": channel,
            "start_date": _to_iso_utc(start_date), "stop_date": _to_iso_utc(stop_date),
            "sampling_rate_hz": float(sampling_rate_hz), "routing": routing,
        }
        self._upsert_record(record)
        self.update_inventory()

    def add_channel_from_local(self, info: ChannelInfo) -> None:
        self.add_channel(
            network=info.network, station=info.station,
            location=info.location, channel=info.channel,
            start_date=info.start_date, stop_date=info.stop_date,
            sampling_rate_hz=info.sampling_rate_hz, routing=info.routing,
        )

    def remove_channel(
        self, network: str, station: str, location: str, channel: str
    ) -> None:
        key = (network, station, location, channel)
        self._pending_records = [
            r for r in self._pending_records
            if (r["network"], r["station"], r["location"], r["channel"]) != key
        ]
        self._persist_records()
        self.update_inventory()

    # ----- Internals --------------------------------------------------------

    def _load_persisted_records(self) -> list[dict]:
        # Refresh _pending_records from disk on each inventory build.
        path = _inventory_path()
        if path.exists():
            with path.open("r") as f:
                payload = yaml.safe_load(f) or {}
            self._pending_records = list(payload.get("channels", []))
        return list(self._pending_records)

    def _persist_records(self) -> None:
        path = _inventory_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            yaml.safe_dump({"channels": self._pending_records}, f, sort_keys=False)

    def _upsert_record(self, record: dict) -> None:
        key = (record["network"], record["station"], record["location"], record["channel"])
        self._pending_records = [
            r for r in self._pending_records
            if (r["network"], r["station"], r["location"], r["channel"]) != key
        ]
        self._pending_records.append(record)
        self._persist_records()

    def _materialize_record(self, root: SpeasyIndex, record: dict) -> None:
        net = record["network"]; sta = record["station"]
        loc = record["location"]; chan = record["channel"]
        dataset_uid = f"sismo/{net}/{sta}/{loc}.{chan}"
        net_node = self._get_or_make_child(root, net, provider=PROVIDER_NAME)
        sta_node = self._get_or_make_child(net_node, sta, provider=PROVIDER_NAME)
        dataset = DatasetIndex(
            name=f"{loc}.{chan}",
            provider=PROVIDER_NAME,
            uid=dataset_uid,
            meta={
                "nslc": [net, sta, loc, chan],
                "routing": record["routing"],
                "sampling_rate_hz": record["sampling_rate_hz"],
            },
        )
        dataset.start_date = _from_iso_utc(record["start_date"])
        dataset.stop_date = _from_iso_utc(record["stop_date"])
        sta_node.__dict__[dataset.spz_name()] = dataset
        for kind, units_label in (
            ("waveform", "m/s"), ("raw", "counts"), ("spectrogram", "dB"),
        ):
            param = ParameterIndex(
                name=kind, provider=PROVIDER_NAME,
                uid=f"{dataset_uid}/{kind}",
                meta={
                    "nslc": [net, sta, loc, chan], "kind": kind,
                    "routing": record["routing"], "units": units_label,
                    "sampling_rate_hz": record["sampling_rate_hz"],
                },
            )
            param.start_date = dataset.start_date
            param.stop_date = dataset.stop_date
            dataset.__dict__[kind] = param

    @staticmethod
    def _get_or_make_child(parent: SpeasyIndex, name: str, provider: str) -> SpeasyIndex:
        if name in parent.__dict__:
            return parent.__dict__[name]
        node = SpeasyIndex(name=name, provider=provider, uid=f"{parent.spz_name()}/{name}")
        parent.__dict__[name] = node
        return node

    def _to_parameter_index(self, product) -> ParameterIndex:
        if isinstance(product, ParameterIndex):
            return product
        if isinstance(product, str):
            if product in self.flat_inventory.parameters:
                return self.flat_inventory.parameters[product]
            raise ValueError(f"unknown product: {product!r}")
        raise TypeError(f"unsupported product type: {type(product)}")

    @staticmethod
    def _coerce_datetime(value) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(str(value))

    def _fetch_stream_for_meta(self, meta, nslc, t0, t1, routing):
        if routing.startswith("local:"):
            path = self._find_local_path_for(nslc, routing)
            stream = self._read_local(path)
            return stream.slice(
                starttime=stream[0].stats.starttime if stream else None,
                endtime=stream[0].stats.endtime if stream else None,
            )
        return fetch_stream(nslc, t0, t1, routing=routing)

    def _find_local_path_for(self, nslc, routing):
        # Records remembered by add_channel_from_local; look up by nslc+routing.
        for record in self._pending_records:
            key = (record["network"], record["station"], record["location"], record["channel"])
            if key == tuple(nslc) and record["routing"] == routing:
                path = record.get("path")
                if path:
                    return Path(path)
        raise RuntimeError(f"no local file remembered for {nslc} ({routing})")

    @staticmethod
    def _read_local(path: Path):
        import obspy
        return obspy.read(str(path))
```

- [ ] **Step 4: Patch `add_channel_from_local` to store the path**

The previous implementation forgot the `path` field. Replace `add_channel_from_local` with:

```python
    def add_channel_from_local(self, info: ChannelInfo) -> None:
        record = {
            "network": info.network, "station": info.station,
            "location": info.location, "channel": info.channel,
            "start_date": _to_iso_utc(info.start_date),
            "stop_date": _to_iso_utc(info.stop_date),
            "sampling_rate_hz": info.sampling_rate_hz,
            "routing": info.routing,
            "path": str(info.path) if info.path else None,
        }
        self._upsert_record(record)
        self.update_inventory()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_provider.py -v
```
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/provider.py sciqlop_sismo/sciqlop_sismo/tests/test_provider.py
git commit -m "feat(sciqlop_sismo): SismoProvider with waveform/raw/spectrogram dispatch + YAML persistence"
```

---

## Task 8: Dock — shell + Stations tab (search + Add to inventory)

**Files:**
- Create: `sciqlop_sismo/sciqlop_sismo/dock.py`
- Create: `sciqlop_sismo/sciqlop_sismo/dock_stations.py`
- Create: `sciqlop_sismo/sciqlop_sismo/tests/test_dock.py`

- [ ] **Step 1: Verify pytest-qt is installed and required**

Modify `sciqlop_sismo/pyproject.toml` — confirm `test = ["pytest", "pytest-qt"]` is in `[project.optional-dependencies]`. Already done in Task 1.

Run:
```bash
pip install -e 'sciqlop_sismo[test]'
python -c "import pytestqt; print(pytestqt.__version__)"
```
Expected: a version number prints.

- [ ] **Step 2: Write the failing dock tests**

```python
"""Tests for sciqlop_sismo.dock (Qt-headless via pytest-qt)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from obspy.core.inventory import Channel, Inventory, Network, Station


@pytest.fixture
def fake_inventory():
    chan = Channel(
        code="HHZ", location_code="00", latitude=45.0, longitude=5.0,
        elevation=600.0, depth=0.0, sample_rate=100.0,
        start_date=datetime(2010, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    sta = Station(
        code="SSB", latitude=45.0, longitude=5.0, elevation=600.0,
        channels=[chan],
    )
    net = Network(code="G", stations=[sta])
    return Inventory(networks=[net], source="test")


@pytest.fixture
def mock_provider():
    return MagicMock()


@pytest.fixture
def dock(qtbot, mock_provider):
    from sciqlop_sismo.dock import SismoBrowserDock
    w = SismoBrowserDock(provider=mock_provider)
    qtbot.addWidget(w)
    return w


def test_dock_has_three_tabs(dock):
    assert dock.tab_widget.count() == 3
    tab_titles = [dock.tab_widget.tabText(i) for i in range(3)]
    assert tab_titles == ["Stations", "Events", "Local files"]


def test_stations_tab_search_calls_fdsn_client(qtbot, dock, fake_inventory):
    tab = dock.stations_tab
    tab.network_edit.setText("G")
    tab.station_edit.setText("SSB")
    tab.channel_edit.setText("HHZ")
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory) as ss:
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    ss.assert_called_once()
    kwargs = ss.call_args.kwargs
    assert kwargs["network"] == "G"
    assert kwargs["station"] == "SSB"
    assert kwargs["channel"] == "HHZ"


def test_search_results_populate_tree(qtbot, dock, fake_inventory):
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    # Tree should now contain "G" → "SSB" → "00.HHZ".
    model = tab.results_tree.model()
    assert model.rowCount() >= 1  # at least one Network row
    net_index = model.index(0, 0)
    assert model.data(net_index) == "G"


def test_add_to_inventory_calls_provider(qtbot, dock, fake_inventory, mock_provider):
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    # Select the channel row.
    model = tab.results_tree.model()
    net = model.index(0, 0)
    sta = model.index(0, 0, net)
    chan = model.index(0, 0, sta)
    tab.results_tree.selectionModel().select(
        chan, tab.results_tree.selectionModel().ClearAndSelect | tab.results_tree.selectionModel().Rows
    )
    qtbot.mouseClick(tab.add_button, _Qt_LeftButton())
    mock_provider.add_channel.assert_called_once()
    kwargs = mock_provider.add_channel.call_args.kwargs
    assert kwargs["network"] == "G"
    assert kwargs["station"] == "SSB"
    assert kwargs["location"] == "00"
    assert kwargs["channel"] == "HHZ"


def test_search_error_lands_in_status_bar(qtbot, dock):
    tab = dock.stations_tab
    with patch(
        "sciqlop_sismo.dock_stations.search_stations",
        side_effect=RuntimeError("boom"),
    ):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    assert "boom" in dock.status_label.text()


def _Qt_LeftButton():
    from PySide6.QtCore import Qt
    return Qt.LeftButton
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_dock.py -v
```
Expected: ImportError for `sciqlop_sismo.dock`.

- [ ] **Step 4: Implement `sciqlop_sismo/sciqlop_sismo/dock.py` (shell)**

```python
"""SismoBrowserDock — top-level widget hosting three tabs.

The dock owns no plot widgets. Each tab discovers/imports channels and
calls `provider.add_channel(...)` to make them first-class Speasy
products visible in the SciQLop main inventory.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from .dock_stations import StationsTab


class SismoBrowserDock(QWidget):
    def __init__(self, provider, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Sismo")
        self._provider = provider

        root = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        self.stations_tab = StationsTab(provider=provider, status_sink=self._set_status)
        self.events_tab = QWidget()    # filled in Task 10
        self.local_tab = QWidget()     # filled in Task 11
        self.tab_widget.addTab(self.stations_tab, "Stations")
        self.tab_widget.addTab(self.events_tab, "Events")
        self.tab_widget.addTab(self.local_tab, "Local files")
        root.addWidget(self.tab_widget, 1)

        self.status_label = QLabel("ready")
        self.status_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
```

- [ ] **Step 5: Implement `sciqlop_sismo/sciqlop_sismo/dock_stations.py`**

```python
"""Stations tab — search + add to inventory.

Threading: a `QRunnable` runs `fdsn_client.search_stations` on the
global QThreadPool; results land on a queued `Signal` in the GUI
thread. No qasync (per `feedback_qasync_httpx_async_client`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from PySide6.QtCore import (
    QAbstractItemModel, QModelIndex, QObject, QRunnable, Qt, QThreadPool,
    Signal,
)
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox, QDateTimeEdit, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTreeView, QVBoxLayout, QWidget, QAbstractItemView,
)

from .fdsn_client import search_stations


class _SearchRunnable(QRunnable):
    def __init__(self, callback_obj, **kwargs):
        super().__init__()
        self._cb = callback_obj
        self._kwargs = kwargs

    def run(self):
        try:
            inv = search_stations(**self._kwargs)
            self._cb.completed.emit(inv)
        except Exception as exc:  # noqa: BLE001
            self._cb.failed.emit(f"{type(exc).__name__}: {exc}")


class _SearchSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class StationsTab(QWidget):
    search_finished = Signal()  # for tests; emitted on either completed or failed

    def __init__(self, provider, status_sink: Callable[[str], None], parent=None):
        super().__init__(parent)
        self._provider = provider
        self._status_sink = status_sink
        self._signals = _SearchSignals()
        self._signals.completed.connect(self._on_search_completed)
        self._signals.failed.connect(self._on_search_failed)

        root = QVBoxLayout(self)
        form = QHBoxLayout()
        self.network_edit = QLineEdit("G,FR,IU")
        self.station_edit = QLineEdit("*")
        self.location_edit = QLineEdit("*")
        self.channel_edit = QLineEdit("HH?,BH?")
        for label, w in (("Net", self.network_edit), ("Sta", self.station_edit),
                          ("Loc", self.location_edit), ("Chan", self.channel_edit)):
            form.addWidget(QLabel(label))
            form.addWidget(w)
        root.addLayout(form)

        times = QHBoxLayout()
        now = datetime.now(tz=timezone.utc)
        self.start_picker = QDateTimeEdit()
        self.start_picker.setCalendarPopup(True)
        self.start_picker.setDateTime(_to_qdatetime(now.replace(hour=0, minute=0)))
        self.end_picker = QDateTimeEdit()
        self.end_picker.setCalendarPopup(True)
        self.end_picker.setDateTime(_to_qdatetime(now))
        for label, w in (("Start UTC", self.start_picker), ("End UTC", self.end_picker)):
            times.addWidget(QLabel(label))
            times.addWidget(w)
        self.routing_combo = QComboBox()
        self.routing_combo.addItems(["iris-federator", "eida-routing", "IRIS", "RESIF", "GEOFON", "IPGP"])
        times.addWidget(QLabel("Routing"))
        times.addWidget(self.routing_combo)
        self.search_button = QPushButton("Search")
        times.addWidget(self.search_button)
        root.addLayout(times)

        self.results_tree = QTreeView()
        self.results_tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["Code", "Sample rate", "Coverage"])
        self.results_tree.setModel(self._model)
        root.addWidget(self.results_tree, 1)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add to inventory")
        buttons.addWidget(self.add_button)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.search_button.clicked.connect(self._on_search_clicked)
        self.add_button.clicked.connect(self._on_add_clicked)

    # ----- Search -----

    def _on_search_clicked(self):
        self._status_sink(f"Searching {self.routing_combo.currentText()}…")
        QThreadPool.globalInstance().start(_SearchRunnable(
            self._signals,
            network=self.network_edit.text(),
            station=self.station_edit.text(),
            location=self.location_edit.text(),
            channel=self.channel_edit.text(),
            start_time=self.start_picker.dateTime().toPython().replace(tzinfo=timezone.utc),
            end_time=self.end_picker.dateTime().toPython().replace(tzinfo=timezone.utc),
            routing=self.routing_combo.currentText(),
        ))

    def _on_search_completed(self, inv):
        self._populate_tree(inv)
        n_chans = sum(
            len(s.channels) for net in inv.networks for s in net.stations
        )
        self._status_sink(f"Found {n_chans} channel(s)")
        self.search_finished.emit()

    def _on_search_failed(self, message: str):
        self._status_sink(f"Search failed: {message}")
        self.search_finished.emit()

    def _populate_tree(self, inv):
        self._model.clear()
        self._model.setHorizontalHeaderLabels(["Code", "Sample rate", "Coverage"])
        for net in inv.networks:
            net_item = QStandardItem(net.code)
            net_item.setEditable(False)
            for sta in net.stations:
                sta_item = QStandardItem(sta.code)
                sta_item.setEditable(False)
                for chan in sta.channels:
                    loc_chan = f"{chan.location_code}.{chan.code}"
                    chan_item = QStandardItem(loc_chan)
                    chan_item.setEditable(False)
                    chan_item.setData({
                        "network": net.code, "station": sta.code,
                        "location": chan.location_code, "channel": chan.code,
                        "sample_rate": float(chan.sample_rate or 0.0),
                        "start_date": chan.start_date,
                        "end_date": chan.end_date,
                    }, Qt.UserRole)
                    rate_item = QStandardItem(f"{chan.sample_rate or 0:.2f} Hz")
                    rate_item.setEditable(False)
                    coverage = f"{chan.start_date} → {chan.end_date}"
                    cov_item = QStandardItem(coverage)
                    cov_item.setEditable(False)
                    sta_item.appendRow([chan_item, rate_item, cov_item])
                net_item.appendRow([sta_item])
            self._model.appendRow([net_item])
        self.results_tree.expandAll()

    # ----- Add to inventory -----

    def _on_add_clicked(self):
        rows = self._selected_channel_rows()
        if not rows:
            self._status_sink("No channel selected")
            return
        for payload in rows:
            self._provider.add_channel(
                network=payload["network"], station=payload["station"],
                location=payload["location"], channel=payload["channel"],
                start_date=_obspy_to_dt(payload["start_date"]),
                stop_date=_obspy_to_dt(payload["end_date"]),
                sampling_rate_hz=payload["sample_rate"],
                routing=self.routing_combo.currentText(),
            )
        self._status_sink(f"Added {len(rows)} channel(s) to inventory")

    def _selected_channel_rows(self) -> list[dict]:
        rows = []
        for index in self.results_tree.selectionModel().selectedIndexes():
            if index.column() != 0:
                continue
            payload = self._model.itemFromIndex(index).data(Qt.UserRole)
            if isinstance(payload, dict) and "channel" in payload:
                rows.append(payload)
        return rows


def _to_qdatetime(dt: datetime):
    from PySide6.QtCore import QDateTime
    return QDateTime.fromString(dt.strftime("%Y-%m-%dT%H:%M:%S"), "yyyy-MM-ddTHH:mm:ss")


def _obspy_to_dt(value) -> datetime:
    if value is None:
        return datetime.now(tz=timezone.utc)
    if hasattr(value, "datetime"):
        d = value.datetime
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value))
```

- [ ] **Step 6: Run tests to verify they pass**

The root `conftest.py` stubs `PySide6` with MagicMock — but we need a real `PySide6` for pytest-qt tests. Add a guard at the top of the new `test_dock.py` (and `conftest.py` in tests/) to **unstub PySide6** if a real install is present, OR add `pytestmark = pytest.mark.skipif(not _real_pyside, ...)`.

Update `sciqlop_sismo/sciqlop_sismo/tests/conftest.py`:

```python
"""Local conftest: undo root-conftest PySide6 stubbing if a real install exists."""
import atexit
import importlib
import os
import sys


def _force_exit():
    os._exit(0)


atexit.register(_force_exit)


def _restore_real_pyside():
    try:
        for mod_name in list(sys.modules.keys()):
            if mod_name.startswith("PySide6"):
                sys.modules.pop(mod_name, None)
        importlib.import_module("PySide6.QtWidgets")
    except ImportError:
        # No real PySide6 available — leave stubs in place; Qt tests will skip.
        pass


_restore_real_pyside()
```

Run:
```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_dock.py -v
```
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/dock.py sciqlop_sismo/sciqlop_sismo/dock_stations.py sciqlop_sismo/sciqlop_sismo/tests/test_dock.py sciqlop_sismo/sciqlop_sismo/tests/conftest.py
git commit -m "feat(sciqlop_sismo): dock shell + Stations tab (search + Add to inventory)"
```

---

## Task 9: Dock — Stations tab plot buttons

**Files:**
- Modify: `sciqlop_sismo/sciqlop_sismo/dock_stations.py`
- Modify: `sciqlop_sismo/sciqlop_sismo/tests/test_dock.py`

- [ ] **Step 1: Add the failing tests for plot buttons**

Append to `sciqlop_sismo/sciqlop_sismo/tests/test_dock.py`:

```python
def test_plot_waveform_calls_create_plot_panel(qtbot, dock, fake_inventory, mock_provider):
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    chan = model.index(0, 0, model.index(0, 0, model.index(0, 0)))
    tab.results_tree.selectionModel().select(
        chan, tab.results_tree.selectionModel().ClearAndSelect | tab.results_tree.selectionModel().Rows
    )
    panel = MagicMock()
    with patch("sciqlop_sismo.dock_stations._create_plot_panel", return_value=panel) as cpp:
        qtbot.mouseClick(tab.plot_waveform_button, _Qt_LeftButton())
    cpp.assert_called_once()
    panel.plot_product.assert_called_once_with("sismo/G/SSB/00.HHZ/waveform")


def test_plot_spectrogram_uses_spectrogram_uid(qtbot, dock, fake_inventory, mock_provider):
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    chan = model.index(0, 0, model.index(0, 0, model.index(0, 0)))
    tab.results_tree.selectionModel().select(
        chan, tab.results_tree.selectionModel().ClearAndSelect | tab.results_tree.selectionModel().Rows
    )
    panel = MagicMock()
    with patch("sciqlop_sismo.dock_stations._create_plot_panel", return_value=panel):
        qtbot.mouseClick(tab.plot_spectrogram_button, _Qt_LeftButton())
    panel.plot_product.assert_called_once_with("sismo/G/SSB/00.HHZ/spectrogram")


def test_plot_buttons_noop_when_create_plot_panel_unavailable(qtbot, dock, fake_inventory, mock_provider):
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    chan = model.index(0, 0, model.index(0, 0, model.index(0, 0)))
    tab.results_tree.selectionModel().select(
        chan, tab.results_tree.selectionModel().ClearAndSelect | tab.results_tree.selectionModel().Rows
    )
    with patch("sciqlop_sismo.dock_stations._create_plot_panel", side_effect=ImportError):
        qtbot.mouseClick(tab.plot_waveform_button, _Qt_LeftButton())
    # Status mentions the missing host runtime.
    assert "SciQLop" in dock.status_label.text() or "unavailable" in dock.status_label.text().lower()
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_dock.py -v -k "plot_"
```
Expected: 3 failures — buttons don't exist yet.

- [ ] **Step 3: Add plot buttons + handler to `dock_stations.py`**

In `StationsTab.__init__`, replace the buttons block:

```python
        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add to inventory")
        self.plot_waveform_button = QPushButton("Plot waveform")
        self.plot_spectrogram_button = QPushButton("Plot spectrogram")
        for b in (self.add_button, self.plot_waveform_button, self.plot_spectrogram_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        root.addLayout(buttons)
```

In the wiring section, add:

```python
        self.plot_waveform_button.clicked.connect(lambda: self._on_plot_clicked("waveform"))
        self.plot_spectrogram_button.clicked.connect(lambda: self._on_plot_clicked("spectrogram"))
```

Add the helper near the top of `dock_stations.py` (before `StationsTab`):

```python
def _create_plot_panel():
    """Lazy import of SciQLop's plot panel helper.

    Raises ImportError if SciQLop's host runtime is not available
    (e.g. headless test).
    """
    from SciQLop.user_api.plot import create_plot_panel
    return create_plot_panel()
```

Add the method to `StationsTab`:

```python
    def _on_plot_clicked(self, kind: str):
        rows = self._selected_channel_rows()
        if not rows:
            self._status_sink("No channel selected")
            return
        # Make sure rows are in the inventory before plotting.
        self._on_add_clicked()
        try:
            panel = _create_plot_panel()
        except ImportError:
            self._status_sink("SciQLop main-window plot API unavailable")
            return
        for payload in rows:
            uid = (
                f"sismo/{payload['network']}/{payload['station']}/"
                f"{payload['location']}.{payload['channel']}/{kind}"
            )
            panel.plot_product(uid)
        self._status_sink(f"Plotted {len(rows)} {kind}(s)")
```

- [ ] **Step 4: Run the dock tests to verify they pass**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_dock.py -v
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/dock_stations.py sciqlop_sismo/sciqlop_sismo/tests/test_dock.py
git commit -m "feat(sciqlop_sismo): Stations tab plot waveform/spectrogram buttons"
```

---

## Task 10: Dock — Events tab

**Files:**
- Create: `sciqlop_sismo/sciqlop_sismo/dock_events.py`
- Modify: `sciqlop_sismo/sciqlop_sismo/dock.py`
- Modify: `sciqlop_sismo/sciqlop_sismo/tests/test_dock.py`

- [ ] **Step 1: Add the failing tests**

Append to `sciqlop_sismo/sciqlop_sismo/tests/test_dock.py`:

```python
@pytest.fixture
def fake_catalog():
    from unittest.mock import MagicMock
    event = MagicMock()
    origin = MagicMock()
    origin.time = MagicMock()
    origin.time.datetime = datetime(2024, 4, 2, 14, 0, tzinfo=timezone.utc)
    origin.latitude = 45.0
    origin.longitude = 5.0
    origin.depth = 10000.0
    magnitude = MagicMock()
    magnitude.mag = 5.5
    event.preferred_origin = MagicMock(return_value=origin)
    event.preferred_magnitude = MagicMock(return_value=magnitude)
    cat = MagicMock()
    cat.__iter__ = MagicMock(return_value=iter([event]))
    cat.__len__ = MagicMock(return_value=1)
    return cat


def test_events_tab_search_events_populates_table(qtbot, dock, fake_catalog):
    tab = dock.events_tab
    with patch("sciqlop_sismo.dock_events.search_events", return_value=fake_catalog) as se:
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    se.assert_called_once()
    assert tab.events_table.rowCount() == 1
    # Magnitude column shows 5.5.
    assert "5.5" in tab.events_table.item(0, 4).text()


def test_find_stations_uses_event_coordinates(qtbot, dock, fake_catalog, fake_inventory):
    tab = dock.events_tab
    with patch("sciqlop_sismo.dock_events.search_events", return_value=fake_catalog):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    tab.events_table.selectRow(0)
    with patch("sciqlop_sismo.dock_events.search_stations", return_value=fake_inventory) as ss:
        with qtbot.waitSignal(tab.stations_finished, timeout=5000):
            qtbot.mouseClick(tab.find_stations_button, _Qt_LeftButton())
    kwargs = ss.call_args.kwargs
    assert kwargs["latitude"] == 45.0
    assert kwargs["longitude"] == 5.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_dock.py -v -k "events"
```
Expected: AttributeError or `dock.events_tab` is a plain QWidget.

- [ ] **Step 3: Implement `sciqlop_sismo/sciqlop_sismo/dock_events.py`**

```python
"""Events tab — pick an earthquake, then list stations around it.

Same threading model as the Stations tab (`QThreadPool` + `QRunnable`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from PySide6.QtCore import (
    QAbstractTableModel, QObject, QRunnable, Qt, QThreadPool, Signal,
)
from PySide6.QtWidgets import (
    QComboBox, QDateTimeEdit, QDoubleSpinBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTreeView, QVBoxLayout, QWidget, QAbstractItemView,
)

from .fdsn_client import search_events, search_stations


class _EventsSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _SearchEventsRunnable(QRunnable):
    def __init__(self, signals, **kwargs):
        super().__init__()
        self._signals = signals
        self._kwargs = kwargs

    def run(self):
        try:
            cat = search_events(**self._kwargs)
            self._signals.completed.emit(cat)
        except Exception as exc:  # noqa: BLE001
            self._signals.failed.emit(f"{type(exc).__name__}: {exc}")


class _StationsSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _SearchStationsRunnable(QRunnable):
    def __init__(self, signals, **kwargs):
        super().__init__()
        self._signals = signals
        self._kwargs = kwargs

    def run(self):
        try:
            inv = search_stations(**self._kwargs)
            self._signals.completed.emit(inv)
        except Exception as exc:  # noqa: BLE001
            self._signals.failed.emit(f"{type(exc).__name__}: {exc}")


class EventsTab(QWidget):
    search_finished = Signal()
    stations_finished = Signal()

    def __init__(self, provider, status_sink: Callable[[str], None], parent=None):
        super().__init__(parent)
        self._provider = provider
        self._status_sink = status_sink
        self._events_signals = _EventsSignals()
        self._events_signals.completed.connect(self._on_events_completed)
        self._events_signals.failed.connect(self._on_events_failed)
        self._stations_signals = _StationsSignals()
        self._stations_signals.completed.connect(self._on_stations_completed)
        self._stations_signals.failed.connect(self._on_stations_failed)
        self._events = []  # cached list of obspy.event.Event from the latest search

        root = QVBoxLayout(self)
        row = QHBoxLayout()
        now = datetime.now(tz=timezone.utc)
        self.start_picker = QDateTimeEdit()
        self.start_picker.setCalendarPopup(True)
        self.start_picker.setDateTime(_qt_dt(now.replace(year=now.year - 1)))
        self.end_picker = QDateTimeEdit()
        self.end_picker.setCalendarPopup(True)
        self.end_picker.setDateTime(_qt_dt(now))
        self.min_mag_spin = QDoubleSpinBox()
        self.min_mag_spin.setRange(0.0, 10.0)
        self.min_mag_spin.setSingleStep(0.1)
        self.min_mag_spin.setValue(5.5)
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["USGS", "EMSC", "ISC"])
        self.search_button = QPushButton("Search events")
        for label, w in (
            ("Start UTC", self.start_picker), ("End UTC", self.end_picker),
            ("Min mag", self.min_mag_spin), ("Catalog", self.provider_combo),
        ):
            row.addWidget(QLabel(label))
            row.addWidget(w)
        row.addWidget(self.search_button)
        root.addLayout(row)

        self.events_table = QTableWidget(0, 5)
        self.events_table.setHorizontalHeaderLabels(
            ["Origin time (UTC)", "Lat", "Lon", "Depth (km)", "Magnitude"]
        )
        self.events_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.events_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.events_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self.events_table, 1)

        radius_row = QHBoxLayout()
        self.min_radius_spin = QDoubleSpinBox()
        self.min_radius_spin.setRange(0.0, 180.0)
        self.min_radius_spin.setValue(0.0)
        self.max_radius_spin = QDoubleSpinBox()
        self.max_radius_spin.setRange(0.0, 180.0)
        self.max_radius_spin.setValue(30.0)
        self.channel_edit = QLineEdit("HH?,BH?")
        self.find_stations_button = QPushButton("Find stations")
        self.add_all_button = QPushButton("Add all to inventory")
        for label, w in (
            ("Min radius°", self.min_radius_spin),
            ("Max radius°", self.max_radius_spin),
            ("Chan filter", self.channel_edit),
        ):
            radius_row.addWidget(QLabel(label))
            radius_row.addWidget(w)
        radius_row.addWidget(self.find_stations_button)
        radius_row.addWidget(self.add_all_button)
        root.addLayout(radius_row)

        self.stations_table = QTableWidget(0, 5)
        self.stations_table.setHorizontalHeaderLabels(
            ["Network", "Station", "Loc.Chan", "Sample rate", "Coverage"]
        )
        self.stations_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.stations_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.stations_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        root.addWidget(self.stations_table, 1)

        self.search_button.clicked.connect(self._on_search_events)
        self.find_stations_button.clicked.connect(self._on_find_stations)
        self.add_all_button.clicked.connect(self._on_add_all)

    # ----- Events search -----

    def _on_search_events(self):
        self._status_sink(f"Searching {self.provider_combo.currentText()} events…")
        QThreadPool.globalInstance().start(_SearchEventsRunnable(
            self._events_signals,
            start_time=self.start_picker.dateTime().toPython().replace(tzinfo=timezone.utc),
            end_time=self.end_picker.dateTime().toPython().replace(tzinfo=timezone.utc),
            min_magnitude=self.min_mag_spin.value(),
            provider=self.provider_combo.currentText(),
        ))

    def _on_events_completed(self, catalog):
        self._events = list(catalog)
        self.events_table.setRowCount(len(self._events))
        for row, event in enumerate(self._events):
            origin = event.preferred_origin()
            mag = event.preferred_magnitude()
            t = origin.time.datetime
            self.events_table.setItem(row, 0, QTableWidgetItem(t.isoformat()))
            self.events_table.setItem(row, 1, QTableWidgetItem(f"{origin.latitude:.3f}"))
            self.events_table.setItem(row, 2, QTableWidgetItem(f"{origin.longitude:.3f}"))
            depth_km = (origin.depth or 0.0) / 1000.0
            self.events_table.setItem(row, 3, QTableWidgetItem(f"{depth_km:.1f}"))
            self.events_table.setItem(row, 4, QTableWidgetItem(f"{mag.mag:.1f}"))
        self._status_sink(f"Found {len(self._events)} event(s)")
        self.search_finished.emit()

    def _on_events_failed(self, message: str):
        self._status_sink(f"Event search failed: {message}")
        self.search_finished.emit()

    # ----- Stations near event -----

    def _on_find_stations(self):
        idx = self.events_table.currentRow()
        if idx < 0 or idx >= len(self._events):
            self._status_sink("No event selected")
            return
        event = self._events[idx]
        origin = event.preferred_origin()
        t0 = origin.time.datetime.replace(tzinfo=timezone.utc)
        # 30 min window centred on origin; configurable later.
        from datetime import timedelta
        t_start = t0 - timedelta(minutes=5)
        t_end = t0 + timedelta(minutes=25)
        self._status_sink("Searching stations around event…")
        QThreadPool.globalInstance().start(_SearchStationsRunnable(
            self._stations_signals,
            network="*", station="*", location="*",
            channel=self.channel_edit.text(),
            start_time=t_start, end_time=t_end,
            routing="iris-federator",
            latitude=origin.latitude, longitude=origin.longitude,
            min_radius_deg=self.min_radius_spin.value(),
            max_radius_deg=self.max_radius_spin.value(),
        ))

    def _on_stations_completed(self, inv):
        rows = []
        for net in inv.networks:
            for sta in net.stations:
                for chan in sta.channels:
                    rows.append({
                        "network": net.code, "station": sta.code,
                        "location": chan.location_code, "channel": chan.code,
                        "sample_rate": float(chan.sample_rate or 0.0),
                        "start_date": chan.start_date, "end_date": chan.end_date,
                    })
        self.stations_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.stations_table.setItem(r, 0, QTableWidgetItem(row["network"]))
            self.stations_table.setItem(r, 1, QTableWidgetItem(row["station"]))
            self.stations_table.setItem(r, 2, QTableWidgetItem(f"{row['location']}.{row['channel']}"))
            self.stations_table.setItem(r, 3, QTableWidgetItem(f"{row['sample_rate']:.2f} Hz"))
            self.stations_table.setItem(r, 4, QTableWidgetItem(f"{row['start_date']} → {row['end_date']}"))
            item = self.stations_table.item(r, 0)
            item.setData(Qt.UserRole, row)
        self._status_sink(f"Found {len(rows)} channel(s) near event")
        self.stations_finished.emit()

    def _on_stations_failed(self, message: str):
        self._status_sink(f"Station search failed: {message}")
        self.stations_finished.emit()

    def _on_add_all(self):
        selected = self.stations_table.selectionModel().selectedRows()
        if not selected:
            self._status_sink("No station rows selected")
            return
        for index in selected:
            row = self.stations_table.item(index.row(), 0).data(Qt.UserRole)
            self._provider.add_channel(
                network=row["network"], station=row["station"],
                location=row["location"], channel=row["channel"],
                start_date=_obspy_dt(row["start_date"]),
                stop_date=_obspy_dt(row["end_date"]),
                sampling_rate_hz=row["sample_rate"],
                routing="iris-federator",
            )
        self._status_sink(f"Added {len(selected)} channel(s)")


def _qt_dt(dt: datetime):
    from PySide6.QtCore import QDateTime
    return QDateTime.fromString(dt.strftime("%Y-%m-%dT%H:%M:%S"), "yyyy-MM-ddTHH:mm:ss")


def _obspy_dt(value) -> datetime:
    if value is None:
        return datetime.now(tz=timezone.utc)
    if hasattr(value, "datetime"):
        d = value.datetime
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value))
```

- [ ] **Step 4: Wire `EventsTab` into the dock**

In `sciqlop_sismo/sciqlop_sismo/dock.py`, replace the events_tab line:

```python
        from .dock_events import EventsTab
        self.events_tab = EventsTab(provider=provider, status_sink=self._set_status)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_dock.py -v
```
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/dock_events.py sciqlop_sismo/sciqlop_sismo/dock.py sciqlop_sismo/sciqlop_sismo/tests/test_dock.py
git commit -m "feat(sciqlop_sismo): Events tab (search events + find stations near event)"
```

---

## Task 11: Dock — Local files tab

**Files:**
- Create: `sciqlop_sismo/sciqlop_sismo/dock_local.py`
- Modify: `sciqlop_sismo/sciqlop_sismo/dock.py`
- Modify: `sciqlop_sismo/sciqlop_sismo/tests/test_dock.py`

- [ ] **Step 1: Add the failing tests**

Append to `sciqlop_sismo/sciqlop_sismo/tests/test_dock.py`:

```python
def test_local_tab_open_file_calls_provider(qtbot, dock, mock_provider, tmp_path):
    import numpy as np
    from obspy import Stream, Trace, UTCDateTime
    fp = tmp_path / "x.mseed"
    Trace(
        data=np.zeros(100, dtype=np.float32),
        header={
            "network": "XX", "station": "TEST", "location": "00",
            "channel": "HHZ", "sampling_rate": 100.0,
            "starttime": UTCDateTime("2026-01-01T00:00:00"),
        },
    ).write(str(fp), format="MSEED")
    tab = dock.local_tab
    with patch(
        "sciqlop_sismo.dock_local.QFileDialog.getOpenFileNames",
        return_value=([str(fp)], "Seismic files (*.mseed *.sac)"),
    ):
        qtbot.mouseClick(tab.open_button, _Qt_LeftButton())
    mock_provider.add_channel_from_local.assert_called_once()
    info = mock_provider.add_channel_from_local.call_args.args[0]
    assert info.network == "XX"
```

- [ ] **Step 2: Run new test to verify it fails**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_dock.py -v -k "local_tab"
```
Expected: AttributeError (`dock.local_tab` lacks `open_button`).

- [ ] **Step 3: Implement `sciqlop_sismo/sciqlop_sismo/dock_local.py`**

```python
"""Local files tab — open miniSEED / SAC via ObsPy."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from .local_files import import_file


class LocalFilesTab(QWidget):
    def __init__(self, provider, status_sink: Callable[[str], None], parent=None):
        super().__init__(parent)
        self._provider = provider
        self._status_sink = status_sink

        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.open_button = QPushButton("Open local…")
        controls.addWidget(self.open_button)
        controls.addStretch(1)
        root.addLayout(controls)

        self.files_list = QListWidget()
        root.addWidget(self.files_list, 1)

        self.open_button.clicked.connect(self._on_open_clicked)

    def _on_open_clicked(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open seismic file",
            "", "Seismic files (*.mseed *.sac);;All files (*)",
        )
        if not paths:
            return
        added = 0
        errors: list[tuple[str, str]] = []
        for p in paths:
            try:
                for info in import_file(Path(p)):
                    self._provider.add_channel_from_local(info)
                    item = QListWidgetItem(
                        f"{info.network}.{info.station}.{info.location}.{info.channel}  {p}"
                    )
                    item.setData(Qt.UserRole, info)
                    self.files_list.addItem(item)
                    added += 1
            except Exception as exc:  # noqa: BLE001
                errors.append((str(p), f"{type(exc).__name__}: {exc}"))
        if errors and added == 0:
            self._status_sink(
                f"Failed to import any of {len(paths)} file(s); last: {errors[-1][1]}"
            )
        elif errors:
            self._status_sink(
                f"Imported {added} channel(s); {len(errors)} file(s) failed"
            )
        else:
            self._status_sink(f"Imported {added} channel(s)")
```

- [ ] **Step 4: Wire `LocalFilesTab` into the dock**

In `sciqlop_sismo/sciqlop_sismo/dock.py`, replace the local_tab line:

```python
        from .dock_local import LocalFilesTab
        self.local_tab = LocalFilesTab(provider=provider, status_sink=self._set_status)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_dock.py -v
```
Expected: 11 passed.

- [ ] **Step 6: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/dock_local.py sciqlop_sismo/sciqlop_sismo/dock.py sciqlop_sismo/sciqlop_sismo/tests/test_dock.py
git commit -m "feat(sciqlop_sismo): Local files tab (Open local… → provider)"
```

---

## Task 12: Plugin entry point (`load(main_window)`)

**Files:**
- Modify: `sciqlop_sismo/sciqlop_sismo/__init__.py`
- Modify: `sciqlop_sismo/sciqlop_sismo/tests/test_load.py`

- [ ] **Step 1: Replace the test_load.py with the richer plugin-load test**

```python
"""Smoke + integration tests for the plugin entry point."""
from unittest.mock import MagicMock, patch

import pytest

import sciqlop_sismo


def test_version_is_set():
    assert sciqlop_sismo.__version__ == "0.1.0"


def test_entry_point_resolves():
    from importlib.metadata import entry_points
    eps = entry_points(group="sciqlop.plugins")
    names = {ep.name for ep in eps}
    assert "sciqlop_sismo" in names


def test_load_registers_dock_and_returns_handle():
    main_window = MagicMock()
    # Simulate PySide6QtAds enum used by addWidgetIntoDock.
    with patch("sciqlop_sismo._import_qtads", return_value=MagicMock()):
        handle = sciqlop_sismo.load(main_window)
    assert handle is not None
    # The dock was added.
    main_window.addWidgetIntoDock.assert_called_once()
    main_window.toolsMenu.addAction.assert_called_once()


def test_load_idempotent():
    main_window = MagicMock()
    with patch("sciqlop_sismo._import_qtads", return_value=MagicMock()):
        h1 = sciqlop_sismo.load(main_window)
        h2 = sciqlop_sismo.load(main_window)
    assert h1 is h2
    # Dock added only once per main_window.
    main_window.addWidgetIntoDock.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_load.py -v
```
Expected: 2 failures (`_import_qtads` missing, `load` is a no-op).

- [ ] **Step 3: Implement the full `load` in `sciqlop_sismo/sciqlop_sismo/__init__.py`**

```python
"""sciqlop_sismo — FDSN/ObsPy seismology browser for SciQLop."""
from __future__ import annotations

from typing import Any

__version__ = "0.1.0"

_LOADED_PANELS: dict[int, Any] = {}


def _import_qtads():
    """Indirection so tests can patch the QtAds import."""
    import PySide6QtAds as QtAds
    return QtAds


def load(main_window):
    """SciQLop entry point. Registers the dock + toolbar action (idempotent)."""
    key = id(main_window)
    if key in _LOADED_PANELS:
        return _LOADED_PANELS[key]

    from PySide6.QtGui import QIcon

    from .dock import SismoBrowserDock
    from .provider import SismoProvider

    QtAds = _import_qtads()

    provider = SismoProvider()
    dock = SismoBrowserDock(provider=provider)
    dock.setWindowTitle("Sismo")

    main_window.addWidgetIntoDock(QtAds.DockWidgetArea.TopDockWidgetArea, dock)

    dock_widget = main_window.dock_manager.findDockWidget("Sismo")
    if dock_widget is not None:
        dock_widget.toggleView(False)
        toggle_action = dock_widget.toggleViewAction()
        toggle_action.setIcon(QIcon.fromTheme("applications-science"))
        main_window.toolBar.addAction(toggle_action)

    main_window.toolsMenu.addAction("Sismo", dock.show)

    handle = (provider, dock)
    _LOADED_PANELS[key] = handle
    return handle
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/test_load.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Run the full test suite**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/ -v
```
Expected: ~38 passed, ~2 deselected (the live tests).

- [ ] **Step 6: Commit**

```bash
git add sciqlop_sismo/sciqlop_sismo/__init__.py sciqlop_sismo/sciqlop_sismo/tests/test_load.py
git commit -m "feat(sciqlop_sismo): plugin entry point — register provider + dock"
```

---

## Task 13: README + final polish

**Files:**
- Modify: `sciqlop_sismo/README.md`

- [ ] **Step 1: Expand the README**

```markdown
# sciqlop_sismo

SciQLop plugin for seismic waveforms via FDSN / ObsPy.

## What it does

Implements a Speasy `DataProvider` (`provider_name="sismo"`) that
produces `SpeasyVariable` products from FDSN web services. Once a
channel is added to the provider's inventory, it is a first-class
SciQLop product — drag-drop onto any panel, mix with other space-
physics data, attach catalogs.

Each NSLC channel exposes three parameters:

| UID suffix     | Type            | Units    | Notes                                                  |
|----------------|-----------------|----------|--------------------------------------------------------|
| `/waveform`    | 1-D time-series | m/s      | Demean + bandpass (settings-driven, default 0.01–10 Hz)|
| `/raw`         | 1-D time-series | counts   | Unprocessed instrument output                          |
| `/spectrogram` | 2-D colormap    | dB       | scipy STFT, 256-pt window, 50 % overlap                |

## Usage

1. Open SciQLop. A "Sismo" dock appears (toggle in the toolbar or
   Tools menu).
2. **Stations tab** — fill in NSLC patterns and a time range, hit
   *Search*. Pick channels from the tree and click *Add to inventory*
   (or *Plot waveform* / *Plot spectrogram* to add + immediately drop
   on a fresh panel).
3. **Events tab** — search an earthquake catalog (USGS/EMSC/ISC), pick
   an event, hit *Find stations* to list channels in a given degree
   radius, then *Add all to inventory*.
4. **Local files tab** — open local miniSEED / SAC files; their
   channels appear in the same `sismo/` inventory tree.
5. The inventory is persisted to `~/.config/sciqlop/sismo/inventory.yaml`
   (override via `SCIQLOP_SISMO_INVENTORY_DIR`).

## Data centers

Default routing is `iris-federator`, which transparently fans a single
query out across all major FDSN data centers. Alternatives in the
dropdown:
- `eida-routing` — European Integrated Data Archive
- `IRIS`, `RESIF`, `GEOFON`, `IPGP` — direct single-center queries

## Design

See `docs/superpowers/specs/2026-05-12-sciqlop_sismo-design.md`.

## Development

```bash
pip install -e '.[test]'
pytest sciqlop_sismo/tests/             # mocked tests
pytest sciqlop_sismo/tests/ -m live     # live FDSN tests (slow)
```
```

- [ ] **Step 2: Run the full test suite one more time**

```bash
pytest sciqlop_sismo/sciqlop_sismo/tests/ -v
```
Expected: all green (live tests deselected).

- [ ] **Step 3: Commit**

```bash
git add sciqlop_sismo/README.md
git commit -m "docs(sciqlop_sismo): README with usage + design pointer"
```

- [ ] **Step 4: Tag the release**

```bash
git tag sciqlop_sismo/v0.1.0
```

(Push tag separately when ready; not part of this plan.)

---

## Self-review checklist

- [x] **Spec coverage:**
  - Provider with `build_inventory` / `add_channel` / `get_data` → Task 7
  - Three params per channel (waveform / raw / spectrogram) → Task 7
  - `fdsn_client` (RoutingClient + single-center) → Task 6
  - `process` (detrend + bandpass + default_pipeline) → Task 3
  - `stream_to_variable` (waveform + spectrogram) → Task 4
  - `local_files` (`obspy.read`, ChannelInfo) → Task 5 + 11
  - `dock` (3 tabs: Stations, Events, Local) → Tasks 8–11
  - Pydantic settings with clamping → Task 2
  - QThreadPool + QRunnable + Signal threading → Tasks 8, 10
  - YAML-persisted inventory → Task 7
  - Live test marker, deselected by default → Task 6
  - Entry point `sciqlop.plugins/sciqlop_sismo` → Task 1, validated Task 12
- [x] **Placeholders:** none (every step shows the code).
- [x] **Type consistency:** `ChannelInfo` fields, `SismoProvider` method names, parameter UIDs (`sismo/<NET>/<STA>/<LOC>.<CHAN>/<kind>`) all match across tasks.
- [x] **Files-that-don't-exist references:** none — every `import` resolves to a module created earlier in the plan.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-12-sciqlop_sismo.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session with checkpoints for review.

Which approach?
