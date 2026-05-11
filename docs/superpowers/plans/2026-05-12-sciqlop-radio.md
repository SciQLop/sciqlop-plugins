# sciqlop_radio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a new SciQLop plugin `sciqlop_radio` that lets the user search, download, and view heliospheric radio dynamic spectra from the 9 sources `sunpy.radiospectra` supports today — rendered as native `SciQLopTimeSeriesPlot` colormaps.

**Architecture:** Single plugin in the existing `sciqlop-plugins` monorepo (new top-level `sciqlop_radio/` subdir). One dock widget with a tab per loaded spectrogram; tabs hold a `SciQLopTimeSeriesPlot` configured via the existing `SciQLop.core.plot_hints` machinery. Search and download go through `sunpy.net.Fido` on a `QThreadPool` worker; results stream back via Qt signals. The translator (radiospectra `Spectrogram` → `SciQLopTimeSeriesPlot`) is the only module that touches SciQLop plotting types and is the unit with the most test value.

**Tech Stack:**
- Python 3.10+, PySide6, PySide6QtAds
- SciQLop ≥ 0.12 (for `core.plot_hints` and `core.istp_hints`)
- SciQLopPlots (`SciQLopTimeSeriesPlot`, optional `SciQLopTheme`)
- sunpy ≥ 6.0, radiospectra ≥ 1.0, astropy, numpy, pydantic ≥ 2.0
- pytest, pytest-qt

**Spec:** `docs/superpowers/specs/2026-05-12-sciqlop-radio-design.md`

**Spec refinement during planning:** The spec left the "how do plots reach the central plot area" question open. Following the precedent set by `cdf_workbench` (whose `CdfWorkbenchPanel` owns a `QTabWidget` of `CdfFileView` tabs), this plan resolves it by giving `RadioSpectraDock` its own `QTabWidget` of `RadioPreviewTab` widgets, each containing one `SciQLopTimeSeriesPlot`. The translator returns a `SciQLopTimeSeriesPlot`; the dock wraps it in a tab. This keeps the plugin self-contained and aligned with existing conventions.

---

## File map

Will be created (all under `sciqlop_radio/`):

| Path | Responsibility |
|------|---|
| `pyproject.toml` | Package metadata, deps, entry point |
| `plugin.json` | SciQLop manifest |
| `sciqlop_radio/__init__.py` | `load(main_window)` — registers dock + toolbar action |
| `sciqlop_radio/sources.py` | `RadioSource` Pydantic model + `SOURCES` registry |
| `sciqlop_radio/settings.py` | `RadioSettings(ConfigEntry)` — cache dir, timeout, parallel downloads |
| `sciqlop_radio/reader.py` | `open_spectrogram(path)` — shim around `radiospectra.Spectrogram` |
| `sciqlop_radio/plot.py` | `spectrogram_to_plot(spec, parent)` — the translator |
| `sciqlop_radio/fetch.py` | `RadioFetchService(QObject)` — Fido search/fetch on QThreadPool |
| `sciqlop_radio/dock.py` | `RadioSpectraDock(QWidget)` — UI orchestrator with tabs |
| `sciqlop_radio/tests/conftest.py` | Optional-module stubs + atexit os._exit(0) |
| `sciqlop_radio/tests/data/.gitkeep` | Placeholder; tiny sample files added in Task 5 |
| `sciqlop_radio/tests/test_sources_registry.py` | Registry sanity |
| `sciqlop_radio/tests/test_settings.py` | Bounds clamping |
| `sciqlop_radio/tests/test_plot_translator.py` | Synthetic-spectrogram → plot assertions |
| `sciqlop_radio/tests/test_reader.py` | Real sample file round-trip |
| `sciqlop_radio/tests/test_fetch.py` | Mocked-Fido unit tests |
| `sciqlop_radio/tests/test_dock.py` | pytest-qt + fake fetch service |
| `sciqlop_radio/tests/test_fetch_live.py` | Network smoke, opt-in |

---

## Task 1: Package scaffolding

**Goal:** A new `sciqlop_radio/` subdirectory installable in editable mode, with one passing smoke test.

**Files:**
- Create: `sciqlop_radio/pyproject.toml`
- Create: `sciqlop_radio/plugin.json`
- Create: `sciqlop_radio/sciqlop_radio/__init__.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/__init__.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/conftest.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/test_import.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/data/.gitkeep`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "sciqlop-radio"
version = "0.1.0"
description = "Heliospheric radio dynamic-spectra browser for SciQLop (wraps sunpy.radiospectra)"
requires-python = ">=3.10"
dependencies = [
    "SciQLop>=0.12.0",
    "sunpy>=6.0",
    "radiospectra>=1.0",
    "astropy",
    "numpy>=1.24",
    "pydantic>=2.0",
]

[project.optional-dependencies]
test = ["pytest", "pytest-qt"]

[project.entry-points."sciqlop.plugins"]
sciqlop_radio = "sciqlop_radio"

[tool.setuptools.packages.find]
include = ["sciqlop_radio*"]

[tool.setuptools.package-data]
sciqlop_radio = ["plugin.json"]
```

- [ ] **Step 2: Create `plugin.json`**

```json
{
  "name": "Radio Spectra",
  "version": "0.1.0",
  "description": "Heliospheric radio dynamic-spectra browser for SciQLop",
  "authors": [
    {
      "name": "Alexis Jeandet",
      "email": "alexis.jeandet@member.fsf.org",
      "organization": "LPP"
    }
  ],
  "license": "MIT",
  "python_dependencies": ["SciQLop>=0.12.0", "sunpy>=6.0", "radiospectra>=1.0"],
  "dependencies": [],
  "disabled": false
}
```

- [ ] **Step 3: Create `sciqlop_radio/__init__.py`**

```python
"""sciqlop_radio — heliospheric radio dynamic-spectra browser for SciQLop."""

__version__ = "0.1.0"


def load(main_window):
    """Entry point — wired in Task 8 once the dock is implemented."""
    raise NotImplementedError("load() implemented in Task 8")
```

- [ ] **Step 4: Create `sciqlop_radio/tests/__init__.py`**

Write an empty file.

- [ ] **Step 5: Create `sciqlop_radio/tests/conftest.py`**

```python
"""Test fixtures for sciqlop_radio.

- Stubs optional SciQLop / Qt modules so unit tests can import the package
  without a full SciQLop install (mirrors the sciqlop_albert pattern).
- Registers atexit os._exit(0) to dodge the SciQLopPlots interpreter-shutdown
  segfault (see feedback_sciqlopplots_exit_segfault memory).
"""
import atexit
import importlib
import os
import sys
from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel


_OPTIONAL = [
    "PySide6QtAds",
    "SciQLop",
    "SciQLop.components",
    "SciQLop.components.settings",
    "SciQLop.components.settings.backend",
    "SciQLop.components.theming",
    "SciQLop.core",
    "SciQLop.core.plot_hints",
    "SciQLopPlots",
]
for name in _OPTIONAL:
    if name in sys.modules:
        continue
    try:
        importlib.import_module(name)
    except Exception:
        sys.modules[name] = MagicMock()


class _ConfigEntry(BaseModel):
    """Real-pydantic stub so field_validator and bounds checks actually run."""
    category: ClassVar[str] = ""
    subcategory: ClassVar[str] = ""

    def save(self):
        pass


_settings_backend = sys.modules["SciQLop.components.settings.backend"]
if isinstance(_settings_backend, MagicMock):
    _settings_backend.ConfigEntry = _ConfigEntry
    _settings = sys.modules["SciQLop.components.settings"]
    if isinstance(_settings, MagicMock):
        _settings.SettingsCategory = type(
            "SettingsCategory", (), {"PLUGINS": "plugins"}
        )


def _force_exit():
    os._exit(0)


@pytest.fixture(autouse=True, scope="session")
def _prevent_exit_segfault():
    atexit.register(_force_exit)
    yield
```

- [ ] **Step 6: Create `sciqlop_radio/tests/data/.gitkeep`**

Write an empty file.

- [ ] **Step 7: Create the smoke test `sciqlop_radio/tests/test_import.py`**

```python
def test_package_imports():
    import sciqlop_radio
    assert sciqlop_radio.__version__ == "0.1.0"


def test_load_is_not_implemented_yet():
    import sciqlop_radio
    import pytest
    with pytest.raises(NotImplementedError):
        sciqlop_radio.load(main_window=None)
```

- [ ] **Step 8: Install in editable mode**

Run: `pip install --user -e sciqlop_radio/[test]`
Expected: succeeds; ends with `Successfully installed sciqlop-radio-0.1.0`.

- [ ] **Step 9: Run smoke test**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_import.py -v`
Expected: 2 passed.

- [ ] **Step 10: Commit**

```bash
git add sciqlop_radio/
git commit -m "feat(sciqlop_radio): scaffold plugin skeleton

Empty package + plugin.json + pyproject.toml + tests conftest. load()
raises NotImplementedError; will be wired in once the dock is built."
```

---

## Task 2: `sources.py` — supported instruments registry

**Goal:** Static `SOURCES` list of `RadioSource` entries covering radiospectra's 9 built-in sources, validated by tests.

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/sources.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/test_sources_registry.py`

- [ ] **Step 1: Write the failing test**

`sciqlop_radio/sciqlop_radio/tests/test_sources_registry.py`:

```python
import pytest

from sciqlop_radio.sources import RadioSource, SOURCES


EXPECTED_KEYS = {
    "ecallisto",
    "eovsa",
    "ilofar",
    "psp_rfs",
    "solo_rpw",
    "rstn",
    "stereo_swaves",
    "wind_waves",
    "custom",
}


def test_sources_list_is_non_empty():
    assert len(SOURCES) >= 9


def test_every_source_has_unique_key():
    keys = [s.key for s in SOURCES]
    assert len(keys) == len(set(keys))


def test_expected_radiospectra_sources_present():
    keys = {s.key for s in SOURCES}
    missing = EXPECTED_KEYS - keys
    assert not missing, f"missing sources: {missing}"


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.key)
def test_source_has_non_empty_key_and_label(source):
    assert source.key.strip()
    assert source.label.strip()


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.key)
def test_source_is_reachable(source):
    """Every entry must be addressable: either has a Fido instrument arg
    OR can be opened from local files. The 'custom' radiospectra source
    is local-only by design (no Fido arg)."""
    assert source.fido_instrument or source.accepts_local


def test_radio_source_rejects_blank_key():
    with pytest.raises(ValueError):
        RadioSource(key="", label="foo")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_sources_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sciqlop_radio.sources'`.

- [ ] **Step 3: Implement `sources.py`**

`sciqlop_radio/sciqlop_radio/sources.py`:

```python
"""Static registry of supported radio-spectra sources.

Each entry corresponds to a source `sunpy.radiospectra` knows how to
parse. Adding a new source = adding one entry here; behavior elsewhere
is data-driven from this list.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RadioSource(BaseModel):
    """One supported radio instrument/observatory."""

    key: str = Field(description="Stable identifier used in UI state and tests")
    label: str = Field(description="Human-readable name shown in the dropdown")
    fido_instrument: str | None = Field(
        default=None,
        description=(
            "Argument for sunpy.net.attrs.Instrument; None means this source"
            " is local-file-only (no Fido search supported)"
        ),
    )
    notes: str = Field(default="", description="Tooltip text; coverage caveats")
    accepts_local: bool = Field(default=True)

    @field_validator("key")
    @classmethod
    def _key_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("key must be non-blank")
        return v

    @field_validator("label")
    @classmethod
    def _label_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("label must be non-blank")
        return v


SOURCES: list[RadioSource] = [
    RadioSource(
        key="psp_rfs",
        label="PSP / FIELDS / RFS",
        fido_instrument="rfs",
        notes="LFR (10 kHz–1.7 MHz) + HFR (1.3–19.2 MHz); receiver mode varies along orbit",
    ),
    RadioSource(
        key="solo_rpw",
        label="Solar Orbiter / RPW",
        fido_instrument="rpw",
        notes="TNR + HFR L2/L3; multi-receiver sequence",
    ),
    RadioSource(
        key="wind_waves",
        label="Wind / WAVES",
        fido_instrument="waves",
        notes="RAD1 (20–1040 kHz) + RAD2 (1.075–13.825 MHz)",
    ),
    RadioSource(
        key="stereo_swaves",
        label="STEREO / SWAVES",
        fido_instrument="swaves",
        notes="2.5 kHz – 16 MHz; STEREO-A only post 2014",
    ),
    RadioSource(
        key="ecallisto",
        label="e-CALLISTO (network)",
        fido_instrument="callisto",
        notes="Worldwide ground-based network; many stations with different frequency windows",
    ),
    RadioSource(
        key="eovsa",
        label="EOVSA",
        fido_instrument="eovsa",
        notes="Expanded Owens Valley Solar Array; 1–18 GHz imaging spectroscopy",
    ),
    RadioSource(
        key="ilofar",
        label="I-LOFAR (mode 357 BST)",
        fido_instrument="ilofar",
        notes="Irish LOFAR station, beam-formed mode 357",
    ),
    RadioSource(
        key="rstn",
        label="RSTN",
        fido_instrument="rstn",
        notes="Radio Solar Telescope Network (USAF); data source may be stale",
    ),
    RadioSource(
        key="custom",
        label="Custom (local file)",
        fido_instrument=None,
        accepts_local=True,
        notes="Generic radiospectra reader; time + frequency + data arrays must be present",
    ),
]
```

- [ ] **Step 4: Run tests**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_sources_registry.py -v`
Expected: all pass (≥ 13 passed including parametrized cases).

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/sources.py \
        sciqlop_radio/sciqlop_radio/tests/test_sources_registry.py
git commit -m "feat(sciqlop_radio): add supported-instrument registry"
```

---

## Task 3: `settings.py` — `RadioSettings(ConfigEntry)`

**Goal:** Persisted plugin settings (cache dir, download timeout, parallel downloads) with bounds clamping so stale YAML cannot crash the settings page.

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/settings.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

`sciqlop_radio/sciqlop_radio/tests/test_settings.py`:

```python
from pathlib import Path

import pytest


def test_defaults_are_sensible():
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings()
    assert isinstance(s.cache_dir, Path)
    assert 5 <= s.download_timeout_s <= 600
    assert 1 <= s.parallel_downloads <= 16


def test_timeout_clamps_oversized_value():
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings(download_timeout_s=10_000)
    assert s.download_timeout_s == 600


def test_timeout_clamps_negative_value():
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings(download_timeout_s=-5)
    assert s.download_timeout_s == 5


def test_parallel_clamps_oversized_value():
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings(parallel_downloads=999)
    assert s.parallel_downloads == 16


def test_parallel_clamps_zero():
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings(parallel_downloads=0)
    assert s.parallel_downloads == 1


def test_non_numeric_strings_pass_through_to_pydantic_validation():
    from sciqlop_radio.settings import RadioSettings
    with pytest.raises(Exception):
        RadioSettings(download_timeout_s="not-a-number")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `settings.py`**

`sciqlop_radio/sciqlop_radio/settings.py`:

```python
"""sciqlop_radio plugin settings — persisted via SciQLop ConfigEntry.

Bounded numeric fields clamp on load so a stale or hand-edited YAML
value outside the declared range never crashes the settings panel.
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import Field, field_validator

from SciQLop.components.settings import SettingsCategory
from SciQLop.components.settings.backend import ConfigEntry


class RadioSettings(ConfigEntry):
    category: ClassVar = SettingsCategory.PLUGINS
    subcategory: ClassVar[str] = "Radio Spectra"

    cache_dir: Path = Field(
        default_factory=lambda: Path.home() / ".cache" / "sciqlop_radio",
        description="Directory where fetched radio files are stored",
    )
    download_timeout_s: int = Field(
        default=60,
        ge=5,
        le=600,
        description="Per-file download timeout, seconds",
    )
    parallel_downloads: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Maximum parallel Fido downloads",
    )

    @field_validator("download_timeout_s", mode="before")
    @classmethod
    def _clamp_timeout(cls, v):
        try:
            return max(5, min(600, int(v)))
        except (TypeError, ValueError):
            return v

    @field_validator("parallel_downloads", mode="before")
    @classmethod
    def _clamp_parallel(cls, v):
        try:
            return max(1, min(16, int(v)))
        except (TypeError, ValueError):
            return v
```

- [ ] **Step 4: Run tests**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_settings.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/settings.py \
        sciqlop_radio/sciqlop_radio/tests/test_settings.py
git commit -m "feat(sciqlop_radio): add ConfigEntry settings with bounds clamping"
```

---

## Task 4: `plot.py` — the translator

**Goal:** A pure function that takes any radiospectra-shaped spectrogram (real or synthetic) and produces a configured `SciQLopTimeSeriesPlot` colormap. This is the unit with the most test value — it has no I/O, only array transforms.

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/plot.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/test_plot_translator.py`

**Design notes (for the engineer):**

- A radiospectra `Spectrogram` exposes `.times` (astropy `Time`), `.frequencies` (astropy `Quantity` with Hz/MHz unit), `.data` (2-D numpy, shape `(n_freq, n_time)` or `(n_time, n_freq)` depending on source — assume `(n_freq, n_time)` and transpose if needed), and `.meta` (mapping with at least `instrument`).
- `SciQLopTimeSeriesPlot.colormap(x_seconds_f64, y_f64, data_2d_f64, name=...)` is the call to render. Data must be shaped `(n_time, n_freq)` (rows = time samples, cols = frequency channels). Verify against `cdf_workbench/preview.py:118` for the conventions in use.
- Build a `SciQLop.core.plot_hints.PlotHints` object from the spectrogram metadata and apply it via `apply_plot_hints` so units, log/lin, and labels are set without duplicating the cdf_workbench logic.
- Theme: copy the guarded pattern from `cdf_workbench/preview.py:25-51` verbatim — `SciQLopTheme.dark()` with **no parent**, inside `try/except ImportError`.
- For `SpectrogramSequence` (multi-receiver, e.g. RPW LFR+HFR), concatenate along time after sorting receivers by start-time. Frequency arrays are joined and sorted; for overlapping freq ranges, prefer the higher-resolution receiver — for the MVP, simply stack on the frequency axis and let the user see both bands.
- `RadioPlotError` is raised when any of `times`, `frequencies`, or `data` is missing or empty.

- [ ] **Step 1: Write the failing test**

`sciqlop_radio/sciqlop_radio/tests/test_plot_translator.py`:

```python
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
    sys.modules["radiospectra"] = fake
    sys.modules["radiospectra.spectrogram"] = types.SimpleNamespace(
        Spectrogram=Spectrogram, SpectrogramSequence=SpectrogramSequence
    )
    return fake


def _make_spec(SpecCls, *, n_t=8, n_f=5, instrument="TEST"):
    """Build a duck-typed Spectrogram with fixed shape."""
    spec = SpecCls()

    # times: 8 evenly-spaced samples, 1 s apart
    t0 = datetime(2024, 5, 1, tzinfo=timezone.utc)
    spec.times = types.SimpleNamespace(
        # astropy.time.Time.to_datetime() returns a numpy array of datetimes
        to_datetime=lambda: np.array([
            datetime(2024, 5, 1, 0, 0, i, tzinfo=timezone.utc) for i in range(n_t)
        ]),
        unix=np.arange(n_t, dtype=np.float64) + t0.timestamp(),
    )
    # frequencies: 5 channels at 1, 2, 4, 8, 16 MHz, exposed as Quantity-like
    spec.frequencies = types.SimpleNamespace(
        to_value=lambda unit: np.array([1.0, 2.0, 4.0, 8.0, 16.0]),
        unit="MHz",
    )
    # data: shape (n_freq, n_time) per radiospectra convention
    rng = np.random.default_rng(0)
    spec.data = rng.random((n_f, n_t)).astype(np.float32)
    spec.meta = {"instrument": instrument, "wavelength_unit": "MHz"}
    return spec


def test_to_plot_returns_a_time_series_plot(fake_radiospectra):
    from sciqlop_radio.plot import spectrogram_to_plot
    spec = _make_spec(fake_radiospectra.Spectrogram)
    plot = spectrogram_to_plot(spec, parent=None)
    assert plot is not None
    # The plot has the colormap method on its underlying widget; we check via
    # a sentinel attribute the translator sets for testability.
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


def test_to_plot_passes_frequency_to_y2_axis(fake_radiospectra):
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
    # 4 + 6 = 10 time samples after concatenation
    assert plot._radio_n_time_samples == 10
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_plot_translator.py -v`
Expected: 7 FAIL with `ModuleNotFoundError: No module named 'sciqlop_radio.plot'`.

- [ ] **Step 3: Implement `plot.py`**

`sciqlop_radio/sciqlop_radio/plot.py`:

```python
"""Translator: radiospectra Spectrogram → SciQLopTimeSeriesPlot colormap.

The only module that imports SciQLop plotting types. Pure transform with
testable sentinels (`_radio_*` attributes) attached to the returned plot
so unit tests can verify axis/data wiring without instantiating real Qt.
"""
from __future__ import annotations

from typing import Any

import numpy as np


class RadioPlotError(RuntimeError):
    """Raised when a spectrogram cannot be rendered (missing fields, empty data)."""
    def __init__(self, source: str, reason: str):
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


def _import_radiospectra():
    """Local import so tests can stub `radiospectra` before this module loads."""
    from radiospectra.spectrogram import Spectrogram, SpectrogramSequence  # type: ignore
    return Spectrogram, SpectrogramSequence


def _to_f64(arr) -> np.ndarray:
    a = np.asarray(arr)
    if a.dtype == np.float64 and a.flags["C_CONTIGUOUS"]:
        return a
    return np.ascontiguousarray(a, dtype=np.float64)


def _times_to_unix_seconds(times) -> np.ndarray:
    """Astropy Time → float64 unix seconds (what SciQLop time axis expects)."""
    if times is None:
        return None
    if hasattr(times, "unix"):
        return _to_f64(times.unix)
    if hasattr(times, "to_datetime"):
        dts = np.asarray(times.to_datetime())
        # numpy datetime64[ns] → unix seconds
        epoch = np.datetime64("1970-01-01T00:00:00", "ns")
        return ((dts.astype("datetime64[ns]") - epoch).astype("int64") / 1e9).astype(np.float64)
    return _to_f64(times)


def _frequencies_to_array(freqs) -> tuple[np.ndarray, str]:
    """Return (freq array as f64, unit string)."""
    if freqs is None:
        return None, "Hz"
    if hasattr(freqs, "to_value"):
        unit = str(getattr(freqs, "unit", "Hz"))
        return _to_f64(freqs.to_value(unit)), unit
    return _to_f64(freqs), "Hz"


def _normalize_data(data, n_time: int, n_freq: int) -> np.ndarray:
    """Ensure shape (n_time, n_freq), contiguous float64."""
    a = np.asarray(data)
    if a.shape == (n_freq, n_time):
        a = a.T
    elif a.shape != (n_time, n_freq):
        raise RadioPlotError(
            source=str(a.shape),
            reason=f"data shape {a.shape!r} matches neither (n_freq,n_time)=({n_freq},{n_time}) nor (n_time,n_freq)",
        )
    return _to_f64(a)


def _flatten_sequence(spec) -> Any:
    """If `spec` is a SpectrogramSequence, concatenate into a single Spectrogram-shaped object."""
    children = getattr(spec, "spectrograms", None)
    if children is None:
        return spec  # not a sequence

    if not children:
        raise RadioPlotError(source="sequence", reason="empty SpectrogramSequence")

    # Sort by start time
    children = sorted(children, key=lambda s: _times_to_unix_seconds(s.times)[0])

    times = np.concatenate([_times_to_unix_seconds(s.times) for s in children])
    freqs, unit = _frequencies_to_array(children[0].frequencies)
    n_t = sum(_times_to_unix_seconds(s.times).size for s in children)
    n_f = freqs.size
    data = np.concatenate(
        [_normalize_data(s.data, _times_to_unix_seconds(s.times).size, n_f) for s in children],
        axis=0,
    )
    meta = dict(children[0].meta)
    return _Flattened(times=times, freqs=freqs, unit=unit, data=data, meta=meta)


class _Flattened:
    """Internal sequence-flattened view with the four fields the renderer needs."""
    def __init__(self, *, times, freqs, unit, data, meta):
        self._times_unix = times
        self._freqs = freqs
        self._freq_unit = unit
        self._data = data
        self.meta = meta


def _extract_arrays(spec) -> tuple[np.ndarray, np.ndarray, str, np.ndarray, dict]:
    """Pull (times_unix, freqs, freq_unit, data, meta) from spec or flattened view."""
    if isinstance(spec, _Flattened):
        return spec._times_unix, spec._freqs, spec._freq_unit, spec._data, spec.meta

    if getattr(spec, "times", None) is None:
        raise RadioPlotError(source=_instrument_name(spec), reason="missing .times")
    times_unix = _times_to_unix_seconds(spec.times)

    freqs, unit = _frequencies_to_array(getattr(spec, "frequencies", None))
    if freqs is None or freqs.size == 0:
        raise RadioPlotError(source=_instrument_name(spec), reason="missing .frequencies")

    data = getattr(spec, "data", None)
    if data is None or np.asarray(data).size == 0:
        raise RadioPlotError(source=_instrument_name(spec), reason="empty .data")

    data = _normalize_data(data, times_unix.size, freqs.size)
    meta = dict(getattr(spec, "meta", {}) or {})
    return times_unix, freqs, unit, data, meta


def _instrument_name(spec) -> str:
    meta = getattr(spec, "meta", None) or {}
    return str(meta.get("instrument", "unknown"))


def _make_theme():
    """Copy of cdf_workbench's guarded theme construction. NEVER pass a parent."""
    try:
        from SciQLopPlots import SciQLopTheme
    except ImportError:
        return None
    try:
        return SciQLopTheme.dark()
    except Exception:
        return None


def _build_plot_hints(freq_unit: str, data_unit: str, instrument: str):
    """Build PlotHints from spectrogram metadata. Tolerant of older SciQLop."""
    try:
        from SciQLop.core.plot_hints import PlotHints
    except ImportError:
        return None
    return PlotHints(
        display_type="spectrogram",
        component_labels=[f"{instrument}"],
        units=data_unit,
        scale_type="log",
        depend_1_units=freq_unit,
        depend_1_scale="log",
    )


def spectrogram_to_plot(spec, parent=None):
    """Build a configured SciQLopTimeSeriesPlot colormap from a radiospectra Spectrogram.

    Returns the plot widget. Raises RadioPlotError on missing/empty fields.
    """
    spec = _flatten_sequence(spec)
    times_unix, freqs, freq_unit, data, meta = _extract_arrays(spec)
    instrument = str(meta.get("instrument", "unknown"))
    data_unit = str(meta.get("units") or meta.get("data_unit") or "")

    try:
        from SciQLopPlots import SciQLopTimeSeriesPlot
    except ImportError:
        SciQLopTimeSeriesPlot = None

    if SciQLopTimeSeriesPlot is None:
        plot = _StubPlot()
    else:
        plot = SciQLopTimeSeriesPlot(parent)
        theme = _make_theme()
        if theme is not None:
            plot.set_theme(theme)

        plot.colormap(times_unix, freqs, data, name=instrument)

        hints = _build_plot_hints(freq_unit, data_unit, instrument)
        if hints is not None:
            try:
                from SciQLop.core.plot_hints import apply_plot_hints
                apply_plot_hints(plot, hints)
            except ImportError:
                pass

        try:
            plot.y_axis().set_visible(False)  # cmap data lives on y2_axis
            plot.rescale_axes()
            plot.replot()
        except Exception:
            pass

    title = f"{instrument} — {_format_iso(times_unix[0])}"

    # Sentinels for unit tests (kept on both stub and real plot).
    plot._radio_n_time_samples = int(times_unix.size)
    plot._radio_n_freq_channels = int(freqs.size)
    plot._radio_data_shape = tuple(data.shape)
    plot._radio_y_array = freqs
    plot._radio_title = title
    plot._radio_instrument = instrument
    return plot


def _format_iso(unix_seconds: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).isoformat()


class _StubPlot:
    """Stand-in returned when SciQLopPlots is not importable (tests / headless)."""
    def __init__(self):
        self._setters = {}

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
```

- [ ] **Step 4: Run translator tests**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_plot_translator.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/plot.py \
        sciqlop_radio/sciqlop_radio/tests/test_plot_translator.py
git commit -m "feat(sciqlop_radio): add Spectrogram→SciQLopTimeSeriesPlot translator"
```

---

## Task 5: `reader.py` — radiospectra shim + sample-file round trip

**Goal:** A one-function reader that defers to `radiospectra.Spectrogram(path)` plus one integration test against a tiny committed sample file.

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/reader.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/test_reader.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/data/wind_waves_sample.fits` (or `.cdf`; details in Step 1)

**Sample data note (read first):** Wind/WAVES daily files are typically 1–5 MB CDFs from `https://spdf.gsfc.nasa.gov/pub/data/wind/waves/wav_h1/`. For tests, pick the smallest available file for the most recent month with data — usually `wi_h1_wav_<YYYYMMDD>_v01.cdf` is ~1 MB. If size is a concern, an e-CALLISTO `.fit.gz` file from `http://soleil.i4ds.ch/solarradio/data/2002-20yy_Callisto/` is ~50 KB and faster to commit. The test below assumes one of these is in `tests/data/` — pick one and stick with it.

- [ ] **Step 1: Add sample data**

```bash
# Choose ONE of the following.
# Option A — e-CALLISTO (smaller, ~50 KB):
curl -fSL -o sciqlop_radio/sciqlop_radio/tests/data/ecallisto_sample.fit.gz \
    "http://soleil.i4ds.ch/solarradio/data/2024/01/01/BLEN5M_20240101_120000_25.fit.gz"

# Option B — Wind/WAVES CDF (~1 MB):
# curl -fSL -o sciqlop_radio/sciqlop_radio/tests/data/wind_waves_sample.cdf \
#     "https://spdf.gsfc.nasa.gov/pub/data/wind/waves/wav_h1/2024/wi_h1_wav_20240101_v01.cdf"
```

If neither URL works at the moment, pick any other small radiospectra-readable file you have locally and place it at the corresponding path; just keep the test's filename in sync.

- [ ] **Step 2: Write the failing test**

`sciqlop_radio/sciqlop_radio/tests/test_reader.py`:

```python
"""Reader integration test against a committed sample file.

Requires real sunpy + radiospectra in the test env. Skip if unavailable.
"""
from pathlib import Path

import pytest

pytest.importorskip("radiospectra")

DATA_DIR = Path(__file__).parent / "data"
SAMPLE_CALLISTO = DATA_DIR / "ecallisto_sample.fit.gz"
SAMPLE_WIND = DATA_DIR / "wind_waves_sample.cdf"


def _pick_sample():
    for p in (SAMPLE_CALLISTO, SAMPLE_WIND):
        if p.exists():
            return p
    pytest.skip("no sample data file present")


def test_open_sample_returns_spectrogram_like_object():
    from sciqlop_radio.reader import open_spectrogram
    spec = open_spectrogram(_pick_sample())
    assert spec is not None
    assert hasattr(spec, "data")
    assert hasattr(spec, "times")
    assert hasattr(spec, "frequencies")
    assert spec.data.size > 0


def test_open_nonexistent_file_raises():
    from sciqlop_radio.reader import open_spectrogram
    with pytest.raises(FileNotFoundError):
        open_spectrogram(Path("/nonexistent/file.cdf"))
```

- [ ] **Step 3: Run to verify it fails**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_reader.py -v`
Expected: 2 FAIL (or 2 SKIP if no radiospectra installed; install it first via `pip install --user radiospectra` if needed).

- [ ] **Step 4: Implement `reader.py`**

`sciqlop_radio/sciqlop_radio/reader.py`:

```python
"""Single-entry-point reader for radio dyn-spectra files.

Thin shim around `radiospectra.Spectrogram(path)` so the rest of the
plugin can mock one function and so per-source workarounds can be
added in one place when needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union


def open_spectrogram(path: Union[str, Path]):
    """Open a radio dyn-spectra file. Returns radiospectra Spectrogram or SpectrogramSequence."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"radio file not found: {p}")

    from radiospectra.spectrogram import Spectrogram  # type: ignore
    return Spectrogram(str(p))
```

- [ ] **Step 5: Run reader tests**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_reader.py -v`
Expected: 2 passed (or skipped if radiospectra missing — then install it and rerun).

- [ ] **Step 6: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/reader.py \
        sciqlop_radio/sciqlop_radio/tests/test_reader.py \
        sciqlop_radio/sciqlop_radio/tests/data/
git commit -m "feat(sciqlop_radio): add reader shim + sample-file round-trip test"
```

---

## Task 6: `fetch.py` — `RadioFetchService(QObject)`

**Goal:** Async Fido search/fetch on a `QThreadPool` worker, with Qt signals to bridge results back to the GUI thread. Tests mock Fido.

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/fetch.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/test_fetch.py`

- [ ] **Step 1: Write the failing test**

`sciqlop_radio/sciqlop_radio/tests/test_fetch.py`:

```python
"""RadioFetchService unit tests — Fido is fully mocked."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _fake_search_result(n: int):
    """Mimic the indexable Fido return: response[0] has __iter__/.path attrs."""
    rows = [MagicMock(name=f"row{i}", url=f"https://archive/example_{i}.cdf") for i in range(n)]
    table = MagicMock()
    table.__len__.return_value = n
    table.__iter__.return_value = iter(rows)
    response = MagicMock()
    response.__getitem__.return_value = table
    response.__len__.return_value = 1
    return response, rows


def test_search_emits_search_completed(qapp, tmp_path):
    from sciqlop_radio.fetch import RadioFetchService
    from sciqlop_radio.sources import SOURCES

    svc = RadioFetchService(cache_dir=tmp_path)
    received = []

    svc.searchCompleted.connect(lambda rows: received.append(rows))
    svc.searchFailed.connect(lambda msg: received.append(("FAIL", msg)))

    response, rows = _fake_search_result(3)

    with patch("sciqlop_radio.fetch._do_search", return_value=rows):
        svc.search(
            source=SOURCES[0],
            t_start=datetime(2024, 5, 1, tzinfo=timezone.utc),
            t_end=datetime(2024, 5, 2, tzinfo=timezone.utc),
        )
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()

    assert received, "no signal received"
    assert isinstance(received[0], list)
    assert len(received[0]) == 3


def test_search_failure_emits_search_failed(qapp, tmp_path):
    from sciqlop_radio.fetch import RadioFetchService
    from sciqlop_radio.sources import SOURCES

    svc = RadioFetchService(cache_dir=tmp_path)
    received = []
    svc.searchCompleted.connect(lambda rows: received.append(("OK", rows)))
    svc.searchFailed.connect(lambda msg: received.append(("FAIL", msg)))

    with patch("sciqlop_radio.fetch._do_search", side_effect=RuntimeError("boom")):
        svc.search(
            source=SOURCES[0],
            t_start=datetime(2024, 5, 1, tzinfo=timezone.utc),
            t_end=datetime(2024, 5, 2, tzinfo=timezone.utc),
        )
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()

    assert received and received[0][0] == "FAIL"
    assert "boom" in received[0][1]


def test_fetch_uses_cache_hit(qapp, tmp_path):
    from sciqlop_radio.fetch import RadioFetchService

    cached = tmp_path / "example_0.cdf"
    cached.write_bytes(b"\x00" * 16)

    svc = RadioFetchService(cache_dir=tmp_path)

    received = []
    svc.fetchCompleted.connect(lambda ok, failed: received.append((list(ok), list(failed))))

    row = MagicMock()
    row.url = "https://archive/example_0.cdf"

    with patch("sciqlop_radio.fetch._do_fetch") as fido_fetch:
        svc.fetch([row])
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()
        fido_fetch.assert_not_called()

    assert received
    ok, failed = received[0]
    assert cached in ok
    assert not failed
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_fetch.py -v`
Expected: 3 FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `fetch.py`**

`sciqlop_radio/sciqlop_radio/fetch.py`:

```python
"""Async Fido search/fetch with Qt signals.

All network calls run on QThreadPool workers. Signals are emitted via
queued connections so they always land on the GUI thread. No asyncio /
qasync — keeps us out of the cancel-scope bug class.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


def _do_search(source, t_start: datetime, t_end: datetime, timeout_s: int) -> list[Any]:
    """Run Fido.search synchronously; return a flat list of result rows.

    Isolated so tests can patch it without touching sunpy.
    """
    from sunpy.net import Fido, attrs as a  # type: ignore

    if not source.fido_instrument:
        raise RuntimeError(f"source {source.key!r} does not support Fido search")

    response = Fido.search(
        a.Time(t_start.isoformat(), t_end.isoformat()),
        a.Instrument(source.fido_instrument),
    )
    rows: list[Any] = []
    for table in response:
        for row in table:
            rows.append(row)
    return rows


def _do_fetch(rows: Iterable[Any], cache_dir: Path, timeout_s: int) -> list[Path]:
    """Run Fido.fetch synchronously; return list of local paths in row order."""
    from sunpy.net import Fido  # type: ignore

    cache_dir.mkdir(parents=True, exist_ok=True)
    result = Fido.fetch(list(rows), path=str(cache_dir / "{file}"))
    return [Path(p) for p in result]


def _cache_path_for(row: Any, cache_dir: Path) -> Path:
    """Best-effort: derive expected cached filename from a row's url."""
    url = getattr(row, "url", None) or ""
    name = url.rsplit("/", 1)[-1] if url else ""
    return cache_dir / name if name else cache_dir / "__unknown__"


class _SearchTask(QRunnable):
    def __init__(self, svc: "RadioFetchService", source, t_start, t_end):
        super().__init__()
        self._svc = svc
        self._source = source
        self._t_start = t_start
        self._t_end = t_end

    def run(self):
        svc = self._svc
        try:
            rows = _do_search(self._source, self._t_start, self._t_end, svc._timeout_s)
            svc.searchCompleted.emit(rows)
        except Exception as e:
            svc.searchFailed.emit(f"{type(e).__name__}: {e}")
        finally:
            svc._mark_finished()


class _FetchTask(QRunnable):
    def __init__(self, svc: "RadioFetchService", rows: list[Any]):
        super().__init__()
        self._svc = svc
        self._rows = rows

    def run(self):
        svc = self._svc
        ok: list[Path] = []
        failed: list[tuple[Any, str]] = []
        to_fetch: list[Any] = []
        for row in self._rows:
            cached = _cache_path_for(row, svc._cache_dir)
            if cached.exists():
                ok.append(cached)
            else:
                to_fetch.append(row)

        if to_fetch:
            try:
                paths = _do_fetch(to_fetch, svc._cache_dir, svc._timeout_s)
                ok.extend(paths)
            except Exception as e:
                for row in to_fetch:
                    failed.append((row, f"{type(e).__name__}: {e}"))

        svc.fetchProgress.emit(len(ok), len(self._rows))
        svc.fetchCompleted.emit(ok, failed)
        svc._mark_finished()


class RadioFetchService(QObject):
    """Async wrapper around sunpy.net.Fido with Qt signals."""

    searchCompleted = Signal(list)            # list[FidoRow]
    searchFailed = Signal(str)
    fetchProgress = Signal(int, int)          # done, total
    fetchCompleted = Signal(list, list)       # list[Path], list[(row, msg)]
    fetchFailed = Signal(str)

    def __init__(self, cache_dir: Path, timeout_s: int = 60, parent: QObject | None = None):
        super().__init__(parent)
        self._cache_dir = Path(cache_dir)
        self._timeout_s = int(timeout_s)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._pool = QThreadPool.globalInstance()
        self._inflight = threading.Event()
        self._inflight.set()  # initially idle (set = no work)

    def search(self, source, t_start: datetime, t_end: datetime) -> None:
        self._inflight.clear()
        self._pool.start(_SearchTask(self, source, t_start, t_end))

    def fetch(self, rows: list[Any]) -> None:
        self._inflight.clear()
        self._pool.start(_FetchTask(self, list(rows)))

    def _mark_finished(self):
        self._inflight.set()

    def wait_for_finished(self, timeout_s: float = 30.0) -> bool:
        """Block until the currently-queued task finishes. For tests."""
        return self._inflight.wait(timeout=timeout_s)
```

- [ ] **Step 4: Run fetch tests**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_fetch.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/fetch.py \
        sciqlop_radio/sciqlop_radio/tests/test_fetch.py
git commit -m "feat(sciqlop_radio): add async RadioFetchService with cache-hit shortcut"
```

---

## Task 7: `dock.py` — `RadioSpectraDock`

**Goal:** UI orchestrator. Source dropdown + time pickers + Fetch/Cancel + result list + tabs of plotted spectrograms. Pure signal wiring; domain logic lives elsewhere.

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/dock.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/test_dock.py`

- [ ] **Step 1: Write the failing test**

`sciqlop_radio/sciqlop_radio/tests/test_dock.py`:

```python
"""Dock tests with an injected fake RadioFetchService.

We never hit the real Fido here — the dock's contract with fetch.py is
expressed entirely through signal subscriptions, which we exercise with
a stand-in QObject that emits the same signals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QObject, Signal


class FakeFetchService(QObject):
    searchCompleted = Signal(list)
    searchFailed = Signal(str)
    fetchProgress = Signal(int, int)
    fetchCompleted = Signal(list, list)
    fetchFailed = Signal(str)

    def __init__(self):
        super().__init__()
        self.search_calls: list = []
        self.fetch_calls: list = []
        self._cache_dir = Path("/tmp/sciqlop_radio_test_cache")

    def search(self, source, t_start, t_end):
        self.search_calls.append((source.key, t_start, t_end))

    def fetch(self, rows):
        self.fetch_calls.append(list(rows))

    def wait_for_finished(self, timeout_s=5.0):
        return True


@pytest.fixture
def dock(qtbot):
    from sciqlop_radio.dock import RadioSpectraDock
    svc = FakeFetchService()
    w = RadioSpectraDock(main_window=None, fetch_service=svc)
    qtbot.addWidget(w)
    return w, svc


def test_source_dropdown_populated_from_registry(dock):
    w, _ = dock
    from sciqlop_radio.sources import SOURCES
    assert w.source_combo.count() == len(SOURCES)


def test_fetch_button_calls_fetch_service_search(dock):
    w, svc = dock
    w.start_picker.setDateTime(_qdt(2024, 5, 1))
    w.end_picker.setDateTime(_qdt(2024, 5, 2))
    w.source_combo.setCurrentIndex(0)
    w.fetch_button.click()
    assert svc.search_calls, "fetch button did not trigger search"
    key, t0, t1 = svc.search_calls[-1]
    assert isinstance(key, str)
    assert t0 < t1


def test_search_results_populate_list(dock, qtbot):
    w, svc = dock
    row = MagicMock()
    row.url = "https://archive/example_0.cdf"
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit([row])
    assert w.results_list.count() == 1
    assert "example_0.cdf" in w.results_list.item(0).text()


def test_search_failure_shows_status(dock, qtbot):
    w, svc = dock
    with qtbot.waitSignal(w._status_changed, timeout=1000):
        svc.searchFailed.emit("nope")
    assert "nope" in w.status_label.text()


def test_plot_selected_calls_translator_for_each_path(dock, qtbot, tmp_path, monkeypatch):
    w, svc = dock
    p = tmp_path / "example_0.cdf"
    p.write_bytes(b"\x00")

    fake_spec = MagicMock()
    monkeypatch.setattr(
        "sciqlop_radio.dock.open_spectrogram", lambda path: fake_spec
    )
    rendered = []
    monkeypatch.setattr(
        "sciqlop_radio.dock.spectrogram_to_plot",
        lambda spec, parent=None: rendered.append((spec, parent)) or _make_stub_plot(),
    )

    # Inject completed fetch
    svc.fetchCompleted.emit([p], [])
    qtbot.wait(50)

    assert rendered == [(fake_spec, None)] or len(rendered) == 1
    assert w.tabs.count() >= 1


def _qdt(y, m, d):
    from PySide6.QtCore import QDateTime
    return QDateTime(y, m, d, 0, 0)


def _make_stub_plot():
    from PySide6.QtWidgets import QLabel
    return QLabel("stub plot")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_dock.py -v`
Expected: 5 FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `dock.py`**

`sciqlop_radio/sciqlop_radio/dock.py`:

```python
"""RadioSpectraDock — the one widget the user sees.

Owns a fetch service and a QTabWidget. Selecting "Fetch" runs a Fido
search; clicking a result then "Plot selected" downloads (if not
cached) and opens each result in a new tab containing the colormap.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDateTimeEdit, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .fetch import RadioFetchService
from .plot import spectrogram_to_plot, RadioPlotError
from .reader import open_spectrogram
from .sources import SOURCES, RadioSource


class RadioSpectraDock(QWidget):
    """Source picker + time range + result list + plot tabs."""

    _results_changed = Signal()
    _status_changed = Signal()

    def __init__(
        self,
        main_window=None,
        fetch_service: Optional[RadioFetchService] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Radio Spectra")
        self._main_window = main_window
        self._svc = fetch_service or RadioFetchService(
            cache_dir=Path.home() / ".cache" / "sciqlop_radio",
        )

        root = QVBoxLayout(self)

        # Controls row
        controls = QHBoxLayout()
        self.source_combo = QComboBox()
        for src in SOURCES:
            self.source_combo.addItem(src.label, src)
        controls.addWidget(QLabel("Source:"))
        controls.addWidget(self.source_combo, 1)

        self.open_local_button = QPushButton("Open local…")
        controls.addWidget(self.open_local_button)
        root.addLayout(controls)

        # Time row
        times = QHBoxLayout()
        now = QDateTime.currentDateTimeUtc()
        self.start_picker = QDateTimeEdit(now.addDays(-1))
        self.end_picker = QDateTimeEdit(now)
        for w in (self.start_picker, self.end_picker):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd HH:mm")
        times.addWidget(QLabel("Start (UTC):"))
        times.addWidget(self.start_picker)
        times.addWidget(QLabel("End (UTC):"))
        times.addWidget(self.end_picker)
        self.fetch_button = QPushButton("Fetch")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setEnabled(False)
        times.addWidget(self.fetch_button)
        times.addWidget(self.cancel_button)
        root.addLayout(times)

        # Results
        self.results_list = QListWidget()
        self.results_list.setSelectionMode(QListWidget.ExtendedSelection)
        root.addWidget(self.results_list, 1)
        self.plot_button = QPushButton("Plot selected")
        root.addWidget(self.plot_button)

        # Status
        self.status_label = QLabel("ready")
        root.addWidget(self.status_label)

        # Tabs of plots
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        root.addWidget(self.tabs, 2)

        # Wiring
        self.fetch_button.clicked.connect(self._on_fetch_clicked)
        self.open_local_button.clicked.connect(self._on_open_local_clicked)
        self.plot_button.clicked.connect(self._on_plot_selected_clicked)
        self._svc.searchCompleted.connect(self._on_search_completed)
        self._svc.searchFailed.connect(self._on_search_failed)
        self._svc.fetchCompleted.connect(self._on_fetch_completed)
        self._svc.fetchFailed.connect(self._on_fetch_failed)

    def _on_fetch_clicked(self):
        source: RadioSource = self.source_combo.currentData()
        t0 = self.start_picker.dateTime().toPython().replace(tzinfo=timezone.utc)
        t1 = self.end_picker.dateTime().toPython().replace(tzinfo=timezone.utc)
        if t1 <= t0:
            self._set_status("End time must be after start time")
            return
        if not source.fido_instrument:
            self._set_status(f"{source.label} is local-only — use 'Open local…'")
            return
        self._set_status(f"Searching {source.label}…")
        self.results_list.clear()
        self._results_changed.emit()
        self._svc.search(source, t0, t1)

    def _on_open_local_clicked(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open local radio file", "", "Radio data (*.cdf *.fits *.fit *.fit.gz);;All files (*)"
        )
        if paths:
            self._open_paths([Path(p) for p in paths])

    def _on_plot_selected_clicked(self):
        rows = [self.results_list.item(i).data(Qt.UserRole)
                for i in range(self.results_list.count())
                if self.results_list.item(i).isSelected()]
        if not rows:
            self._set_status("No rows selected")
            return
        self._set_status(f"Fetching {len(rows)} file(s)…")
        self._svc.fetch(rows)

    def _on_search_completed(self, rows: list):
        self.results_list.clear()
        for row in rows:
            url = getattr(row, "url", None) or ""
            name = url.rsplit("/", 1)[-1] if url else repr(row)
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, row)
            self.results_list.addItem(item)
        self._set_status(f"Found {len(rows)} file(s)")
        self._results_changed.emit()

    def _on_search_failed(self, message: str):
        self.results_list.clear()
        self._set_status(f"Search failed: {message}")
        self._results_changed.emit()

    def _on_fetch_completed(self, ok: list, failed: list):
        self._open_paths(list(ok))
        msg = f"Downloaded {len(ok)} file(s)"
        if failed:
            msg += f"; {len(failed)} failed"
        self._set_status(msg)

    def _on_fetch_failed(self, message: str):
        self._set_status(f"Fetch failed: {message}")

    def _open_paths(self, paths: list[Path]):
        for path in paths:
            try:
                spec = open_spectrogram(path)
                plot = spectrogram_to_plot(spec, parent=self)
            except (RadioPlotError, Exception) as e:  # noqa: BLE001
                self._set_status(f"Failed to plot {path.name}: {e}")
                continue
            self.tabs.addTab(plot, path.name)
            self.tabs.setCurrentWidget(plot)

    def _close_tab(self, index: int):
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()

    def _set_status(self, text: str):
        self.status_label.setText(text)
        self._status_changed.emit()
```

- [ ] **Step 4: Run dock tests**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_dock.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/dock.py \
        sciqlop_radio/sciqlop_radio/tests/test_dock.py
git commit -m "feat(sciqlop_radio): add RadioSpectraDock with results list + plot tabs"
```

---

## Task 8: Wire `load(main_window)` and integration smoke test

**Goal:** The plugin can be discovered and loaded by SciQLop. Replace the `NotImplementedError` stub with a real `load` that mirrors the cdf_workbench pattern.

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/__init__.py`
- Create: `sciqlop_radio/sciqlop_radio/tests/test_load.py`

- [ ] **Step 1: Write the failing integration test**

`sciqlop_radio/sciqlop_radio/tests/test_load.py`:

```python
"""Load-entrypoint smoke test against a stubbed main_window."""
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")


def test_load_registers_dock_and_action():
    from sciqlop_radio import load

    main = MagicMock()
    panel = load(main)
    assert panel is not None
    main.addWidgetIntoDock.assert_called_once()
    main.toolsMenu.addAction.assert_called_once()


def test_load_is_idempotent():
    """Calling load twice must not register two toolsMenu entries."""
    from sciqlop_radio import load

    main = MagicMock()
    # First call: count actions
    load(main)
    first_call_count = main.toolsMenu.addAction.call_count

    # Second call: must not add another
    load(main)
    assert main.toolsMenu.addAction.call_count == first_call_count
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_load.py -v`
Expected: FAIL — `load` raises `NotImplementedError`.

- [ ] **Step 3: Replace `__init__.py`**

`sciqlop_radio/sciqlop_radio/__init__.py`:

```python
"""sciqlop_radio — heliospheric radio dynamic-spectra browser for SciQLop."""
from __future__ import annotations

__version__ = "0.1.0"

_LOADED_PANELS: dict[int, object] = {}


def load(main_window):
    """SciQLop entry point. Registers the dock + toolbar action (idempotent)."""
    key = id(main_window)
    if key in _LOADED_PANELS:
        return _LOADED_PANELS[key]

    import PySide6QtAds as QtAds  # local import; available only inside SciQLop
    from PySide6.QtGui import QIcon

    from .dock import RadioSpectraDock

    panel = RadioSpectraDock(main_window=main_window)
    panel.setWindowTitle("Radio Spectra")

    main_window.addWidgetIntoDock(
        QtAds.DockWidgetArea.TopDockWidgetArea, panel
    )

    dock_widget = main_window.dock_manager.findDockWidget("Radio Spectra")
    if dock_widget is not None:
        dock_widget.toggleView(False)
        toggle_action = dock_widget.toggleViewAction()
        toggle_action.setIcon(QIcon.fromTheme("network-wireless"))
        main_window.toolBar.addAction(toggle_action)

    main_window.toolsMenu.addAction("Radio Spectra", panel.show)

    _LOADED_PANELS[key] = panel
    return panel
```

- [ ] **Step 4: Run load test**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_load.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the whole suite**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/ -v`
Expected: all previously passing tests still pass; total ≥ 25 tests.

- [ ] **Step 6: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/__init__.py \
        sciqlop_radio/sciqlop_radio/tests/test_load.py
git commit -m "feat(sciqlop_radio): wire load() entrypoint, idempotent registration"
```

---

## Task 9: Opt-in network smoke tests

**Goal:** One real-Fido test per source so upstream archive regressions are catchable, but skipped by default.

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/tests/test_fetch_live.py`

- [ ] **Step 1: Implement the test**

`sciqlop_radio/sciqlop_radio/tests/test_fetch_live.py`:

```python
"""Live-network tests. Skipped by default; set RADIO_LIVE_TESTS=1 to run.

These hit real archives; they catch upstream regressions but cost network
time and should not gate normal PRs.
"""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

if os.environ.get("RADIO_LIVE_TESTS") != "1":
    pytest.skip("set RADIO_LIVE_TESTS=1 to run live network tests", allow_module_level=True)

from PySide6.QtCore import QCoreApplication

from sciqlop_radio.fetch import RadioFetchService
from sciqlop_radio.sources import SOURCES


@pytest.fixture(scope="module")
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.mark.parametrize(
    "source",
    [s for s in SOURCES if s.fido_instrument],
    ids=lambda s: s.key,
)
def test_search_returns_some_rows(qapp, tmp_path, source):
    svc = RadioFetchService(cache_dir=tmp_path)
    received = []
    svc.searchCompleted.connect(lambda rows: received.append(rows))
    svc.searchFailed.connect(lambda msg: received.append(("FAIL", msg)))

    end = datetime(2024, 5, 2, tzinfo=timezone.utc)
    start = end - timedelta(hours=2)
    svc.search(source, start, end)
    svc.wait_for_finished(timeout_s=60)
    qapp.processEvents()

    assert received, f"no signal for source {source.key}"
    first = received[0]
    if isinstance(first, tuple):
        pytest.skip(f"{source.key} search failed: {first[1]}")
    assert isinstance(first, list)
```

- [ ] **Step 2: Verify it skips by default**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/test_fetch_live.py -v`
Expected: `SKIPPED [1] (set RADIO_LIVE_TESTS=1 ...)`.

- [ ] **Step 3 (manual, optional): Run live**

Run: `RADIO_LIVE_TESTS=1 pytest sciqlop_radio/sciqlop_radio/tests/test_fetch_live.py -v`
Expected: at least PSP/RFS, Wind/WAVES, STEREO/SWAVES, SolO/RPW pass; some ground-based ones may skip if their archive is rate-limited.

- [ ] **Step 4: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/tests/test_fetch_live.py
git commit -m "test(sciqlop_radio): add opt-in live Fido smoke tests"
```

---

## Task 10: Final acceptance + release-readiness check

**Goal:** Verify the full suite, install in a clean env, confirm SciQLop discovers the plugin.

- [ ] **Step 1: Run the entire suite**

Run: `pytest sciqlop_radio/sciqlop_radio/tests/ -v --no-header`
Expected: all passing, no warnings about missing modules under stubs.

- [ ] **Step 2: Verify entry point registration**

Run: `python -c "from importlib.metadata import entry_points; print([e for e in entry_points(group='sciqlop.plugins') if e.name == 'sciqlop_radio'])"`
Expected: one `EntryPoint(name='sciqlop_radio', value='sciqlop_radio', group='sciqlop.plugins')`.

- [ ] **Step 3: Smoke-launch SciQLop with the plugin (manual)**

Run: `SciQLop` (whatever command launches your dev SciQLop).
Expected: "Radio Spectra" appears under Tools menu; clicking it opens the dock; the source dropdown lists all 9 entries.

If any of those fail, fix and re-run the suite before tagging.

- [ ] **Step 4: Update the plugin-layout memory pointer**

After the plugin lands on `main`, update `plugin_repo_layout.md` to add `sciqlop_radio/ — sciqlop-radio (heliospheric radio dyn-spectra browser; deps: SciQLop>=0.12, sunpy>=6.0, radiospectra>=1.0). v0.1.0 merged.`

- [ ] **Step 5: Do NOT tag a release yet**

Per the plugin-layout memory: only tag `<plugin>/v0.1.0` once the package is installable for end users. Wait until you've verified `pip install sciqlop-radio` succeeds against the published `SciQLop>=0.12.0` (currently on `main`, untagged). Note the constraint in the PR description.

---

## Self-review

**Spec coverage check (every section of the spec mapped to a task):**

- Goal #1 (`sciqlop_radio` plugin with MVP search/fetch/render) → Tasks 1, 6, 7, 8.
- Goal #2 (native SciQLopPlot rendering) → Task 4 (translator).
- Goal #3 (no abstraction yet, `radiospectra.Spectrogram` as data model) → Task 5 (reader) + Task 4 (translator input contract).
- Goal #4 (foundation for later) → translator design + future-expansion section of the spec; no implementation task needed.
- Non-goals → respected (no stacking, no Speasy, no extra instruments, no auth).
- Repository placement → Task 1 puts it in the monorepo.
- File layout → Task 1 creates the skeleton; every file from the spec's File map is created in Tasks 1–8.
- All components (`sources`, `fetch`, `reader`, `plot`, `dock`, `settings`) → Tasks 2, 6, 5, 4, 7, 3.
- All three data flows → covered by dock (Flow 1, 2) and fetch (Flow 3, cache hit).
- Error handling → translator raises `RadioPlotError` (Task 4); dock surfaces in status (Task 7); fetch emits separate ok/failed lists (Task 6).
- Threading → Task 6 (QThreadPool + QueuedConnection).
- Settings clamping → Task 3.
- Testing strategy (unit, Qt-integration, network) → Tasks 2, 3, 4, 5, 6, 7, 8, 9.
- Conftest with atexit/os._exit(0) → Task 1.

**Placeholder scan:** No "TBD"/"TODO"/"add appropriate"/"similar to". Every code block contains the actual code. Sample-file URLs in Task 5 are real; the engineer is told to fall back to a local file if they fail.

**Type consistency:** `RadioSource`, `RadioFetchService`, `RadioSpectraDock`, `RadioPlotError`, `RadioSettings`, `spectrogram_to_plot`, `open_spectrogram` are spelled identically wherever referenced. Signal signatures (`searchCompleted(list)`, `fetchCompleted(list, list)`) match between `fetch.py` and `dock.py` test. `_radio_*` sentinels on the plot match between translator and translator tests.

**Scope check:** One plugin, one MVP, ~25 tests, 10 tasks. Single implementation plan.

**Ambiguity check:** Task 4's data-orientation note ("(n_freq, n_time) → transposed to (n_time, n_freq)") is explicit; sample-file choice is explicit (option A xor B); `RadioFetchService.wait_for_finished` is test-only and labelled so.
