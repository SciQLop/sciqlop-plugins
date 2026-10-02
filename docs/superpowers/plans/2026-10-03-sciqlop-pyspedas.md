# sciqlop_pyspedas (MMS particle spectra) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new SciQLop plugin exposing MMS FPI/HPCA energy, pitch-angle and gyrophase spectrograms computed by pyspedas `mms_part_getspec`, as live out-of-process virtual products.

**Architecture:** 18 spectrogram virtual products (6 sources × 3 spectra), probe and data rate as `Literal` knobs. Callbacks are cloudpickled into SciQLop's per-plugin remote worker, which imports pyspedas lazily, checks a range cap, and serves hour fragments through Speasy `@Cacheable`; one `mms_part_getspec` call computes all three spectra and an `lru_cache(maxsize=1)` lets the sibling spectra reuse it.

**Tech Stack:** Python ≥3.10, pyspedas 2.2 (`mms_part_getspec`, `get_data`, `del_data`), Speasy (`Cacheable`, `SpeasyVariable`), SciQLop ≥0.13 (`EasySpectrogram(out_of_process=True)`, `PlotHints`), pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-sciqlop-pyspedas-design.md`

## Global Constraints

- Plugin dir `sciqlop_pyspedas/`, package `sciqlop_pyspedas`, pip name `sciqlop-pyspedas`, version `0.1.0`.
- Dependencies: `pyspedas>=2.2,<3`, `speasy>=1.7`, `numpy`, `SciQLop>=0.13.0,<0.15.0` (remote worker first shipped in v0.13.0).
- pyspedas is imported **only** inside `worker._pyspedas_api()` — never at module top of any plugin module.
- `SPEDAS_DATA_DIR = $SCIQLOP_WORKSPACE_DIR/spedas_data`, set in the worker before pyspedas is imported.
- No data → empty SpeasyVariable, never `None`, from any `@Cacheable` function.
- Range caps (hours): `fast` 6, `srvy` 6, `brst` 0.5. Over the cap → `RangeTooLong` raised before any download.
- `virtual_products.py` must NOT use `from __future__ import annotations` (SciQLop evaluates knob annotations from the callback's globals).
- Run tests with the SciQLop dev venv from the plugins repo root:
  `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_pyspedas/sciqlop_pyspedas/tests -v`
  One test invocation at a time, in the foreground. Never `pip install` / `uv pip install` anything; never create a venv.
- Commit with explicit pathspecs only (the tree has unrelated untracked files: `docs/sciqlop-user-api-retro-2026-05-16.md`, `sciqlop_radio/uv.lock`). End messages with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **HPCA cache keys must include data rate** — the HPCA tplot name has no rate in it (`mms1_hpca_hplus_phase_space_density_energy`), so keying the cache on the tplot name would serve srvy data for a brst request. Test in Task 3 (`test_cache_key_distinguishes_hpca_rates`).
2. **Energy then pitch angle for the same window → one `mms_part_getspec` call.** Test in Task 3 (`test_sibling_spectra_share_one_compute`).
3. **A window with no data at all** must not raise and must be cached (second request makes no new call). Test in Task 3 (`test_no_data_is_cached_not_refetched`).
4. **Range exactly at the cap is allowed, just over is refused**, and the message tells the user what to do. Test in Task 3 (`test_range_cap_boundary`).
5. **The pyspedas tplot store is wiped after each compute, even when reading fails** — otherwise the long-lived worker leaks memory. Test in Task 3 (`test_store_cleared_even_on_error`).

---

### Task 1: Package skeleton + catalog

**Files:**
- Create: `sciqlop_pyspedas/pyproject.toml`
- Create: `sciqlop_pyspedas/README.md`
- Create: `sciqlop_pyspedas/sciqlop_pyspedas/__init__.py`
- Create: `sciqlop_pyspedas/sciqlop_pyspedas/plugin.json`
- Create: `sciqlop_pyspedas/sciqlop_pyspedas/catalog.py`
- Create: `sciqlop_pyspedas/sciqlop_pyspedas/tests/__init__.py` (empty)
- Create: `sciqlop_pyspedas/sciqlop_pyspedas/tests/conftest.py`
- Test: `sciqlop_pyspedas/sciqlop_pyspedas/tests/test_catalog.py`

**Interfaces:**
- Produces: `Output(label, bin_label, bin_units, bin_log)` NamedTuple; `OUTPUTS: dict[str, Output]` with keys `"energy"`, `"pa"`, `"gyro"` (pyspedas output names); `Source(instrument, species, label, data_rates)` frozen dataclass; `SOURCES: tuple[Source, ...]` (6 entries); `PROBES = ("1","2","3","4")`; `tplot_name(source, probe, data_rate, output) -> str`; `cache_key(source, probe, data_rate, output) -> str`; `product_path(source, output) -> str`.

- [ ] **Step 1: Write packaging files**

`sciqlop_pyspedas/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "sciqlop-pyspedas"
version = "0.1.0"
description = "Experimental SciQLop plugin: MMS particle spectra computed by pyspedas"
requires-python = ">=3.10"
dependencies = [
    "pyspedas>=2.2,<3",
    "speasy>=1.7",
    "numpy",
    "SciQLop>=0.13.0,<0.15.0",
]

[project.optional-dependencies]
test = ["pytest"]

[project.entry-points."sciqlop.plugins"]
sciqlop_pyspedas = "sciqlop_pyspedas"

[tool.setuptools.packages.find]
include = ["sciqlop_pyspedas*"]

[tool.setuptools.package-data]
sciqlop_pyspedas = ["plugin.json"]

[tool.pytest.ini_options]
markers = ["live: tests that download real MMS data (slow; skipped by default)"]
addopts = "-m 'not live'"
```

`sciqlop_pyspedas/sciqlop_pyspedas/plugin.json`:
```json
{
  "name": "pyspedas",
  "version": "0.1.0",
  "description": "Experimental: MMS FPI/HPCA energy, pitch-angle and gyrophase spectrograms computed by pyspedas",
  "authors": [
    {
      "name": "Alexis Jeandet",
      "email": "alexis.jeandet@member.fsf.org",
      "organization": "LPP"
    }
  ],
  "license": "MIT",
  "python_dependencies": ["pyspedas>=2.2,<3", "speasy>=1.7", "numpy", "SciQLop>=0.13.0,<0.15.0"],
  "dependencies": [],
  "disabled": false
}
```

`sciqlop_pyspedas/sciqlop_pyspedas/__init__.py` (load() is filled in Task 4):
```python
"""sciqlop_pyspedas — experimental MMS particle spectra from pyspedas."""

__version__ = "0.1.0"
```

`sciqlop_pyspedas/README.md`:
```markdown
# sciqlop-pyspedas (experimental)

MMS particle spectrograms computed by [pyspedas](https://github.com/spedas/pyspedas)
`mms_part_getspec`, exposed as SciQLop virtual products under `pyspedas/MMS/`:

- FPI ions / electrons, HPCA H+ / He+ / He++ / O+
- energy, pitch angle and gyrophase spectrograms
- knobs: probe (1-4) and data rate (FPI fast|brst, HPCA srvy|brst)

Computation runs in SciQLop's remote worker process. Downloaded CDFs go to
`<workspace>/spedas_data/` (a global `MMS_DATA_DIR` still wins). Requests
longer than 6 h (fast/srvy) or 30 min (brst) are refused — zoom in.
```

`sciqlop_pyspedas/sciqlop_pyspedas/tests/conftest.py`:
```python
"""Isolate Speasy's disk cache per run and stub SciQLop so registration
never pulls Qt global state into the test process."""
import os
import sys
import tempfile
from unittest.mock import MagicMock

# Must precede any speasy import: the cache singleton reads SPEASY_CACHE_PATH at import time.
os.environ.setdefault("SPEASY_CACHE_PATH", tempfile.mkdtemp(prefix="sciqlop_pyspedas_cache_"))

import pytest

for _name in ("SciQLop", "SciQLop.user_api", "SciQLop.user_api.virtual_products",
              "SciQLop.components", "SciQLop.components.plotting",
              "SciQLop.components.plotting.backend",
              "SciQLop.components.plotting.backend.easy_provider",
              "SciQLop.core", "SciQLop.core.plot_hints"):
    sys.modules.setdefault(_name, MagicMock())


@pytest.fixture(autouse=True)
def _isolate_caches():
    import re

    from speasy.core.cache import drop_matching_entries

    from sciqlop_pyspedas import worker

    drop_matching_entries(re.compile(".*"))
    worker.compute_all.cache_clear()
    yield
```
Note: this conftest imports `sciqlop_pyspedas.worker`, created in Task 3. Until then, guard it: in Task 1 write the fixture body without the two `worker` lines; Task 3 Step 1 adds them.

- [ ] **Step 2: Write the failing catalog test**

`sciqlop_pyspedas/sciqlop_pyspedas/tests/test_catalog.py`:
```python
from sciqlop_pyspedas.catalog import (OUTPUTS, PROBES, SOURCES, Source, cache_key,
                                      product_path, tplot_name)

FPI_I = Source("fpi", "i", "FPI ions", ("fast", "brst"))
HPCA_H = Source("hpca", "hplus", "HPCA H+", ("srvy", "brst"))


def test_eighteen_products_with_unique_paths():
    paths = {product_path(s, o) for s in SOURCES for o in OUTPUTS}
    assert len(paths) == 18


def test_outputs_are_pyspedas_names():
    assert set(OUTPUTS) == {"energy", "pa", "gyro"}
    assert OUTPUTS["energy"].bin_log is True
    assert OUTPUTS["pa"].bin_log is False


def test_probes():
    assert PROBES == ("1", "2", "3", "4")


def test_fpi_tplot_name_matches_pyspedas():
    assert tplot_name(FPI_I, "1", "fast", "energy") == "mms1_dis_dist_fast_energy"


def test_hpca_tplot_name_matches_pyspedas():
    assert tplot_name(HPCA_H, "2", "brst", "pa") == "mms2_hpca_hplus_phase_space_density_pa"


def test_product_path():
    assert product_path(FPI_I, "pa") == "pyspedas/MMS/FPI ions/pitch angle"


def test_hpca_rates_have_distinct_cache_keys():
    assert cache_key(HPCA_H, "1", "srvy", "energy") != cache_key(HPCA_H, "1", "brst", "energy")
```

- [ ] **Step 3: Run it, expect FAIL** (`ModuleNotFoundError: sciqlop_pyspedas.catalog`)

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_pyspedas/sciqlop_pyspedas/tests/test_catalog.py -v`

- [ ] **Step 4: Implement `catalog.py`**

```python
"""What the plugin exposes: MMS particle sources × spectra, and the names
pyspedas 2.2 gives them."""
from dataclasses import dataclass
from typing import NamedTuple


class Output(NamedTuple):
    label: str
    bin_label: str
    bin_units: str
    bin_log: bool


OUTPUTS = {
    "energy": Output("energy", "energy", "eV", True),
    "pa": Output("pitch angle", "pitch angle", "deg", False),
    "gyro": Output("gyrophase", "gyrophase", "deg", False),
}


@dataclass(frozen=True)
class Source:
    instrument: str
    species: str
    label: str
    data_rates: tuple


_FPI_RATES = ("fast", "brst")
_HPCA_RATES = ("srvy", "brst")

SOURCES = (
    Source("fpi", "i", "FPI ions", _FPI_RATES),
    Source("fpi", "e", "FPI electrons", _FPI_RATES),
    Source("hpca", "hplus", "HPCA H+", _HPCA_RATES),
    Source("hpca", "heplus", "HPCA He+", _HPCA_RATES),
    Source("hpca", "heplusplus", "HPCA He++", _HPCA_RATES),
    Source("hpca", "oplus", "HPCA O+", _HPCA_RATES),
)

PROBES = ("1", "2", "3", "4")


def tplot_name(source: Source, probe: str, data_rate: str, output: str) -> str:
    """Output name built by pyspedas mms_part_getspec/mms_part_products."""
    if source.instrument == "fpi":
        base = f"mms{probe}_d{source.species}s_dist_{data_rate}"
    else:
        base = f"mms{probe}_hpca_{source.species}_phase_space_density"
    return f"{base}_{output}"


def cache_key(source: Source, probe: str, data_rate: str, output: str) -> str:
    # Not tplot_name: HPCA names carry no data rate, so srvy and brst would collide.
    return f"mms{probe}/{source.instrument}/{source.species}/{data_rate}/{output}"


def product_path(source: Source, output: str) -> str:
    return f"pyspedas/MMS/{source.label}/{OUTPUTS[output].label}"
```

- [ ] **Step 5: Run it, expect PASS (7 passed)**

Same command as Step 3.

- [ ] **Step 6: Commit**

```bash
git add sciqlop_pyspedas/pyproject.toml sciqlop_pyspedas/README.md sciqlop_pyspedas/sciqlop_pyspedas/__init__.py sciqlop_pyspedas/sciqlop_pyspedas/plugin.json sciqlop_pyspedas/sciqlop_pyspedas/catalog.py sciqlop_pyspedas/sciqlop_pyspedas/tests/__init__.py sciqlop_pyspedas/sciqlop_pyspedas/tests/conftest.py sciqlop_pyspedas/sciqlop_pyspedas/tests/test_catalog.py
git commit -m "feat(sciqlop_pyspedas): package skeleton and MMS spectra catalog"
```

---

### Task 2: tplot arrays → SpeasyVariable

**Files:**
- Create: `sciqlop_pyspedas/sciqlop_pyspedas/convert.py`
- Test: `sciqlop_pyspedas/sciqlop_pyspedas/tests/test_convert.py`

**Interfaces:**
- Consumes: `catalog.OUTPUTS`.
- Produces: `EFLUX_UNITS: str`; `spectrum_variable(times, values, bins, output: str, name: str) -> SpeasyVariable` (times: datetime64 array; values: (n_times, n_bins); bins: (n_bins,) or (n_times, n_bins)); `empty_spectrum(output: str, name: str) -> SpeasyVariable` (zero rows).

- [ ] **Step 1: Write the failing test**

`sciqlop_pyspedas/sciqlop_pyspedas/tests/test_convert.py`:
```python
import numpy as np

from sciqlop_pyspedas.convert import EFLUX_UNITS, empty_spectrum, spectrum_variable


def _times(n):
    return np.datetime64("2020-01-01T00:00:00", "ns") + np.arange(n) * np.timedelta64(10, "s")


def test_energy_spectrum_with_fixed_bins():
    v = spectrum_variable(_times(3), np.ones((3, 4)), np.array([10., 100., 1e3, 1e4]),
                          "energy", "mms1_dis_dist_fast_energy")
    assert v.values.shape == (3, 4)
    assert v.time.dtype == np.dtype("datetime64[ns]")
    assert v.axes[1].values.shape == (4,)
    assert v.axes[1].meta["UNITS"] == "eV"
    assert v.axes[1].meta["SCALETYP"] == "log"
    assert v.meta["UNITS"] == EFLUX_UNITS


def test_time_varying_bins_are_kept_2d():
    bins = np.tile(np.array([10., 100., 1e3, 1e4]), (3, 1))
    v = spectrum_variable(_times(3), np.ones((3, 4)), bins, "energy", "x")
    assert v.axes[1].values.shape == (3, 4)


def test_pitch_angle_axis_is_linear_degrees():
    v = spectrum_variable(_times(2), np.ones((2, 3)), np.array([15., 90., 165.]), "pa", "x")
    assert v.axes[1].meta["UNITS"] == "deg"
    assert v.axes[1].meta["SCALETYP"] == "linear"


def test_empty_spectrum_has_no_rows():
    v = empty_spectrum("gyro", "x")
    assert len(v.time) == 0
```

- [ ] **Step 2: Run it, expect FAIL** (`ModuleNotFoundError: sciqlop_pyspedas.convert`)

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_pyspedas/sciqlop_pyspedas/tests/test_convert.py -v`

- [ ] **Step 3: Implement `convert.py`**

```python
"""pyspedas spectrogram arrays (get_data) → SpeasyVariable."""
import numpy as np
from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
from speasy.products.variable import SpeasyVariable

from .catalog import OUTPUTS

EFLUX_UNITS = "eV/(cm^2 s sr eV)"


def _bin_axis(bins: np.ndarray, output: str) -> VariableAxis:
    out = OUTPUTS[output]
    return VariableAxis(
        values=bins,
        meta={"FIELDNAM": out.bin_label, "UNITS": out.bin_units,
              "SCALETYP": "log" if out.bin_log else "linear"},
        name=out.bin_label,
        is_time_dependent=bins.ndim == 2,
    )


def spectrum_variable(times, values, bins, output: str, name: str) -> SpeasyVariable:
    data = DataContainer(
        values=np.asarray(values, dtype=np.float64),
        meta={"FIELDNAM": name, "UNITS": EFLUX_UNITS, "SCALETYP": "log",
              "DISPLAY_TYPE": "spectrogram"},
        name=name,
    )
    time_axis = VariableTimeAxis(values=np.asarray(times).astype("datetime64[ns]"))
    return SpeasyVariable(axes=[time_axis, _bin_axis(np.asarray(bins, dtype=np.float64), output)],
                          values=data)


def empty_spectrum(output: str, name: str) -> SpeasyVariable:
    """Zero rows: the "sure there is no data" answer Speasy's cache stores."""
    return spectrum_variable(np.array([], dtype="datetime64[ns]"), np.empty((0, 1)),
                             np.zeros(1), output, name)
```

- [ ] **Step 4: Run it, expect PASS (4 passed)**

If Speasy rejects a constructor argument (e.g. `columns` required), read `speasy/products/variable.py` `SpeasyVariable.__init__` in the dev venv and match its signature; do not change the tests' expectations.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_pyspedas/sciqlop_pyspedas/convert.py sciqlop_pyspedas/sciqlop_pyspedas/tests/test_convert.py
git commit -m "feat(sciqlop_pyspedas): convert pyspedas spectrograms to SpeasyVariable"
```

---

### Task 3: Worker — range cap, data dir, compute, cache

**Files:**
- Create: `sciqlop_pyspedas/sciqlop_pyspedas/worker.py`
- Modify: `sciqlop_pyspedas/sciqlop_pyspedas/tests/conftest.py` (add `worker.compute_all.cache_clear()` to the fixture, as shown in Task 1)
- Test: `sciqlop_pyspedas/sciqlop_pyspedas/tests/test_worker.py`

**Interfaces:**
- Consumes: `catalog.OUTPUTS`, `catalog.Source`, `catalog.tplot_name`, `catalog.cache_key`; `convert.spectrum_variable`, `convert.empty_spectrum`.
- Produces: `MAX_HOURS: dict[str, float]`; `class RangeTooLong(ValueError)`; `check_range(start: datetime, stop: datetime, data_rate: str) -> None`; `configure_data_dir(environ=os.environ) -> None`; `_pyspedas_api() -> SimpleNamespace(getspec, get_data, del_data)` (test seam); `compute_all(source, probe, data_rate, start, stop) -> dict[str, SpeasyVariable]` (lru_cache maxsize=1, has `.cache_clear()`); `worker_callback(start: float, stop: float, *, source: Source, output: str, probe: str, data_rate: str) -> SpeasyVariable | None`.

- [ ] **Step 1: Update conftest fixture** to clear `worker.compute_all` (exact code in Task 1's conftest block).

- [ ] **Step 2: Write the failing tests**

`sciqlop_pyspedas/sciqlop_pyspedas/tests/test_worker.py`:
```python
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from sciqlop_pyspedas import worker
from sciqlop_pyspedas.catalog import Source, tplot_name

FPI_I = Source("fpi", "i", "FPI ions", ("fast", "brst"))
HPCA_H = Source("hpca", "hplus", "HPCA H+", ("srvy", "brst"))
T0 = datetime(2020, 1, 1, tzinfo=timezone.utc)


class FakePyspedas:
    """Stands in for pyspedas: records getspec calls, serves a tplot-like store."""

    def __init__(self, has_data=True, fail_get_data=False):
        self.has_data = has_data
        self.fail_get_data = fail_get_data
        self.calls = []
        self.store = {}
        self.cleared = 0

    def getspec(self, *, instrument, probe, species, data_rate, trange, output):
        self.calls.append(dict(instrument=instrument, probe=probe, species=species,
                               data_rate=data_rate, trange=trange))
        if not self.has_data:
            return []
        t0, t1 = (np.datetime64(t.replace("/", "T"), "ns") for t in trange)
        times = np.arange(t0, t1, np.timedelta64(60, "s"))
        source = Source(instrument, species, "", ())
        names = []
        for out in output:
            name = tplot_name(source, probe, data_rate, out)
            self.store[name] = SimpleNamespace(times=times, y=np.ones((len(times), 4)),
                                               v=np.array([10., 100., 1e3, 1e4]))
            names.append(name)
        return names

    def get_data(self, name, dt=False):
        if self.fail_get_data:
            raise RuntimeError("boom")
        return self.store[name]

    def del_data(self, pattern):
        self.cleared += 1
        self.store.clear()


@pytest.fixture
def fake(monkeypatch):
    f = FakePyspedas()
    monkeypatch.setattr(worker, "_pyspedas_api", lambda: f)
    return f


def _call(output, start, stop, source=FPI_I, data_rate="fast"):
    return worker.worker_callback(start.timestamp(), stop.timestamp(), source=source,
                                  output=output, probe="1", data_rate=data_rate)


def test_returns_requested_spectrum(fake):
    v = _call("energy", T0, T0 + timedelta(minutes=30))
    assert v is not None and len(v.time) > 0
    assert v.values.shape[1] == 4
    assert fake.calls[0]["instrument"] == "fpi" and fake.calls[0]["species"] == "i"


def test_sibling_spectra_share_one_compute(fake):
    _call("energy", T0, T0 + timedelta(minutes=30))
    _call("pa", T0, T0 + timedelta(minutes=30))
    _call("gyro", T0, T0 + timedelta(minutes=30))
    assert len(fake.calls) == 1


def test_repeat_request_served_from_disk_cache(fake):
    _call("energy", T0, T0 + timedelta(minutes=30))
    worker.compute_all.cache_clear()
    _call("energy", T0, T0 + timedelta(minutes=30))
    assert len(fake.calls) == 1


def test_no_data_is_cached_not_refetched(fake):
    fake.has_data = False
    first = _call("energy", T0, T0 + timedelta(minutes=30))
    worker.compute_all.cache_clear()
    second = _call("energy", T0, T0 + timedelta(minutes=30))
    assert first is None or len(first.time) == 0
    assert second is None or len(second.time) == 0
    assert len(fake.calls) == 1


def test_cache_key_distinguishes_hpca_rates(fake):
    _call("energy", T0, T0 + timedelta(minutes=10), source=HPCA_H, data_rate="srvy")
    _call("energy", T0, T0 + timedelta(minutes=10), source=HPCA_H, data_rate="brst")
    assert [c["data_rate"] for c in fake.calls] == ["srvy", "brst"]


def test_range_cap_boundary(fake):
    _call("energy", T0, T0 + timedelta(hours=6))
    with pytest.raises(worker.RangeTooLong, match="Zoom in"):
        _call("energy", T0, T0 + timedelta(hours=6, seconds=1))
    with pytest.raises(worker.RangeTooLong):
        _call("energy", T0, T0 + timedelta(minutes=31), data_rate="brst")


def test_refused_range_downloads_nothing(fake):
    with pytest.raises(worker.RangeTooLong):
        _call("energy", T0, T0 + timedelta(days=1))
    assert fake.calls == []


def test_store_cleared_after_compute(fake):
    _call("energy", T0, T0 + timedelta(minutes=30))
    assert fake.cleared == 1 and fake.store == {}


def test_store_cleared_even_on_error(fake):
    fake.fail_get_data = True
    with pytest.raises(RuntimeError):
        _call("energy", T0, T0 + timedelta(minutes=30))
    assert fake.cleared == 1


def test_data_dir_is_inside_workspace():
    env = {"SCIQLOP_WORKSPACE_DIR": "/ws"}
    worker.configure_data_dir(env)
    assert env["SPEDAS_DATA_DIR"] == "/ws/spedas_data"


def test_data_dir_untouched_without_workspace():
    env = {}
    worker.configure_data_dir(env)
    assert "SPEDAS_DATA_DIR" not in env
```

- [ ] **Step 3: Run them, expect FAIL** (`ModuleNotFoundError: sciqlop_pyspedas.worker`)

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_pyspedas/sciqlop_pyspedas/tests/test_worker.py -v`

- [ ] **Step 4: Implement `worker.py`**

```python
"""Worker-side MMS particle spectra: range cap → hour-fragment cache →
one mms_part_getspec call for all spectra.

Runs in SciQLop's per-plugin remote worker: single-threaded, so pyspedas's
global tplot store is never shared between concurrent requests."""
import os
from datetime import datetime, timezone
from functools import lru_cache
from types import SimpleNamespace

from speasy.core.cache import Cacheable

from .catalog import OUTPUTS, Source, cache_key, tplot_name
from .convert import empty_spectrum, spectrum_variable

# simplify: fixed caps tuned by hand during the experiment; burst requests
# still compute whole hour fragments (burst data is sparse, so that stays small).
# Upgrade path: a settings entry snapshotted into the callback at registration.
MAX_HOURS = {"fast": 6.0, "srvy": 6.0, "brst": 0.5}


class RangeTooLong(ValueError):
    pass


def check_range(start: datetime, stop: datetime, data_rate: str) -> None:
    hours = (stop - start).total_seconds() / 3600
    cap = MAX_HOURS[data_rate]
    if hours > cap:
        raise RangeTooLong(
            f"MMS {data_rate} particle spectra: {hours:.1f} h requested, "
            f"at most {cap:g} h per request. Zoom in."
        )


def configure_data_dir(environ=os.environ) -> None:
    workspace = environ.get("SCIQLOP_WORKSPACE_DIR")
    if workspace:
        environ["SPEDAS_DATA_DIR"] = os.path.join(workspace, "spedas_data")


def _pyspedas_api() -> SimpleNamespace:
    """The only place pyspedas is imported; tests replace this function."""
    configure_data_dir()
    from pyspedas import del_data, get_data
    from pyspedas.projects.mms import mms_part_getspec

    return SimpleNamespace(getspec=mms_part_getspec, get_data=get_data, del_data=del_data)


def _trange(start: datetime, stop: datetime) -> list:
    return [t.strftime("%Y-%m-%d/%H:%M:%S") for t in (start, stop)]


def _read_output(api, name: str, output: str, produced: list):
    if name not in produced:
        return empty_spectrum(output, name)
    data = api.get_data(name, dt=True)
    return spectrum_variable(data.times, data.y, data.v, output, name)


@lru_cache(maxsize=1)
def compute_all(source: Source, probe: str, data_rate: str, start: datetime, stop: datetime) -> dict:
    """All spectra for one window from a single getspec call; memoized so the
    sibling spectra requested next for the same fragment cost nothing."""
    api = _pyspedas_api()
    try:
        produced = api.getspec(instrument=source.instrument, probe=probe, species=source.species,
                               data_rate=data_rate, trange=_trange(start, stop),
                               output=list(OUTPUTS)) or []
        return {out: _read_output(api, tplot_name(source, probe, data_rate, out), out, produced)
                for out in OUTPUTS}
    finally:
        api.del_data("*")


class _SpectrumCache:
    """Method-style holder: speasy's Cacheable wraps (self, product, start, stop, ...)."""

    @Cacheable(prefix="pyspedas_mms", fragment_hours=lambda product: 1)
    def spectrum(self, product, start_time, stop_time, *, source, probe, data_rate, output):
        return compute_all(source, probe, data_rate, start_time, stop_time)[output]


_CACHE = _SpectrumCache()


def worker_callback(start: float, stop: float, *, source: Source, output: str,
                    probe: str, data_rate: str):
    t0 = datetime.fromtimestamp(float(start), tz=timezone.utc)
    t1 = datetime.fromtimestamp(float(stop), tz=timezone.utc)
    check_range(t0, t1, data_rate)
    return _CACHE.spectrum(cache_key(source, probe, data_rate, output), t0, t1,
                           source=source, probe=probe, data_rate=data_rate, output=output)
```

- [ ] **Step 5: Run them, expect PASS (11 passed)**

If `test_no_data_is_cached_not_refetched` fails because Speasy discards empty fragments on read, do NOT weaken the test: read `speasy/core/cache/_providers_caches.py` (`_is_empty`, `DISCARD_RULES`) in the dev venv, then report the finding to the user before changing anything — an empty window refetching on every pan is a real cost for MMS.

- [ ] **Step 6: Run the whole plugin suite, expect all PASS**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_pyspedas/sciqlop_pyspedas/tests -v`

- [ ] **Step 7: Commit**

```bash
git add sciqlop_pyspedas/sciqlop_pyspedas/worker.py sciqlop_pyspedas/sciqlop_pyspedas/tests/test_worker.py sciqlop_pyspedas/sciqlop_pyspedas/tests/conftest.py
git commit -m "feat(sciqlop_pyspedas): worker computing MMS spectra with range cap and hourly cache"
```

---

### Task 4: Virtual products + plugin `load()`

**Files:**
- Create: `sciqlop_pyspedas/sciqlop_pyspedas/virtual_products.py`
- Modify: `sciqlop_pyspedas/sciqlop_pyspedas/__init__.py`
- Test: `sciqlop_pyspedas/sciqlop_pyspedas/tests/test_virtual_products.py`

**Interfaces:**
- Consumes: `catalog.SOURCES`, `catalog.OUTPUTS`, `catalog.product_path`, `catalog.Source`; `convert.EFLUX_UNITS`; `worker.worker_callback`.
- Produces: `build_callback(source, output) -> Callable[(start, stop, probe="1", data_rate=<default>), ...]`; `hint_spec(output) -> dict` (PlotHints-shaped); `register_all(vp_factory=None) -> dict[str, object]`; `load(main_window) -> None`.

Why a subclass: on the out-of-process path SciQLop only gets arrays back, so `plot_hints_from_variable` never sees our variable's metadata; log axes must come from `plot_hints(node)`. Per SciQLopPlots colormap convention, the bin axis is `y2` and the data is `z`.

- [ ] **Step 1: Write the failing tests**

`sciqlop_pyspedas/sciqlop_pyspedas/tests/test_virtual_products.py`:
```python
import inspect
import typing

import cloudpickle

from sciqlop_pyspedas import virtual_products as vp
from sciqlop_pyspedas.catalog import SOURCES


def _fpi_ions():
    return next(s for s in SOURCES if s.label == "FPI ions")


def _hpca_h():
    return next(s for s in SOURCES if s.label == "HPCA H+")


def test_registers_eighteen_spectrograms():
    calls = []
    registered = vp.register_all(vp_factory=lambda path, cb, **kw: calls.append((path, kw)) or path)
    assert len(registered) == 18
    path, kw = calls[0]
    assert path.startswith("pyspedas/MMS/")
    assert kw["metadata"]["DISPLAY_TYPE"] == "spectrogram"


def test_one_bad_product_does_not_block_the_others():
    def factory(path, cb, **kw):
        if path.endswith("FPI ions/energy"):
            raise RuntimeError("boom")
        return path

    assert len(vp.register_all(vp_factory=factory)) == 17


def test_fpi_knobs():
    hints = typing.get_type_hints(vp.build_callback(_fpi_ions(), "energy"))
    assert typing.get_args(hints["probe"]) == ("1", "2", "3", "4")
    assert typing.get_args(hints["data_rate"]) == ("fast", "brst")


def test_hpca_knobs_default_to_srvy():
    cb = vp.build_callback(_hpca_h(), "pa")
    assert typing.get_args(typing.get_type_hints(cb)["data_rate"]) == ("srvy", "brst")
    assert inspect.signature(cb).parameters["data_rate"].default == "srvy"


def test_callback_forwards_to_worker(monkeypatch):
    seen = {}
    monkeypatch.setattr(vp, "worker_callback", lambda start, stop, **kw: seen.update(kw) or "ok")
    assert vp.build_callback(_fpi_ions(), "gyro")(1.0, 2.0, probe="3", data_rate="brst") == "ok"
    assert seen == dict(source=_fpi_ions(), output="gyro", probe="3", data_rate="brst")


def test_callback_survives_cloudpickle():
    cb = cloudpickle.loads(cloudpickle.dumps(vp.build_callback(_fpi_ions(), "energy")))
    assert list(inspect.signature(cb).parameters) == ["start", "stop", "probe", "data_rate"]


def test_callback_module_groups_into_plugin_worker():
    assert vp.build_callback(_fpi_ions(), "energy").__module__.split(".")[0] == "sciqlop_pyspedas"


def test_hint_spec_log_energy_linear_angles():
    assert vp.hint_spec("energy")["y2"]["scale"] == "log"
    assert vp.hint_spec("pa")["y2"]["scale"] == "linear"
    assert vp.hint_spec("pa")["z"]["scale"] == "log"


def test_load_registers_once(monkeypatch):
    import sciqlop_pyspedas

    calls = []
    monkeypatch.setattr(vp, "register_all", lambda: calls.append(1) or {"p": object()})
    monkeypatch.setattr(sciqlop_pyspedas, "_REGISTERED", {})
    sciqlop_pyspedas.load(object())
    sciqlop_pyspedas.load(object())
    assert calls == [1]
```

- [ ] **Step 2: Run them, expect FAIL** (`ImportError: cannot import name 'virtual_products'`)

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_pyspedas/sciqlop_pyspedas/tests/test_virtual_products.py -v`

- [ ] **Step 3: Implement `virtual_products.py`** (no `from __future__ import annotations` — see Global Constraints)

```python
"""One live, out-of-process spectrogram product per (source, spectrum).

Probe and data rate are Literal knobs read off the callback signature.
Callbacks capture only the frozen Source and the output name, so they
cloudpickle into SciQLop's worker; their module groups them under one
per-plugin worker process."""
import logging
from typing import Literal

from .catalog import OUTPUTS, SOURCES, Source, product_path
from .convert import EFLUX_UNITS
from .worker import worker_callback

log = logging.getLogger(__name__)

Probe = Literal["1", "2", "3", "4"]
FpiRate = Literal["fast", "brst"]
HpcaRate = Literal["srvy", "brst"]


def build_callback(source: Source, output: str):
    if source.instrument == "fpi":
        def mms_spectrum(start: float, stop: float, probe: Probe = "1", data_rate: FpiRate = "fast"):
            return worker_callback(start, stop, source=source, output=output,
                                   probe=probe, data_rate=data_rate)
    else:
        def mms_spectrum(start: float, stop: float, probe: Probe = "1", data_rate: HpcaRate = "srvy"):
            return worker_callback(start, stop, source=source, output=output,
                                   probe=probe, data_rate=data_rate)
    return mms_spectrum


def hint_spec(output: str) -> dict:
    out = OUTPUTS[output]
    return {
        "display_type": "spectrogram",
        "y2": {"label": out.bin_label, "unit": out.bin_units,
               "scale": "log" if out.bin_log else "linear"},
        "z": {"label": "eflux", "unit": EFLUX_UNITS, "scale": "log"},
    }


def _metadata(source: Source, output: str) -> dict:
    return {
        "DISPLAY_TYPE": "spectrogram",
        "description": f"MMS {source.label} {OUTPUTS[output].label} spectrogram "
                       f"(pyspedas mms_part_getspec)",
    }


def _default_vp_factory(path, callback, *, hints, metadata):
    from SciQLop.components.plotting.backend.easy_provider import EasySpectrogram
    from SciQLop.core.plot_hints import PlotHints

    plot_hints = PlotHints.model_validate(hints)

    class MmsSpectrogram(EasySpectrogram):
        def plot_hints(self, node):
            return plot_hints

    return MmsSpectrogram(path, callback, metadata=metadata, out_of_process=True)


def register_all(vp_factory=None) -> dict:
    vp_factory = vp_factory or _default_vp_factory
    registered = {}
    for source in SOURCES:
        for output in OUTPUTS:
            path = product_path(source, output)
            try:
                registered[path] = vp_factory(path, build_callback(source, output),
                                              hints=hint_spec(output),
                                              metadata=_metadata(source, output))
            except Exception:  # noqa: BLE001
                log.exception("pyspedas: registration failed for %s", path)
    return registered
```

`__init__.py` becomes:
```python
"""sciqlop_pyspedas — experimental MMS particle spectra from pyspedas."""

__version__ = "0.1.0"

_REGISTERED: dict = {}


def load(main_window):
    """SciQLop entry point: register the MMS spectra products once."""
    from . import virtual_products

    if not _REGISTERED:
        _REGISTERED.update(virtual_products.register_all())
```

- [ ] **Step 4: Run them, expect PASS (9 passed)**

- [ ] **Step 5: Run the whole plugin suite, expect all PASS**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_pyspedas/sciqlop_pyspedas/tests -v`

- [ ] **Step 6: Commit**

```bash
git add sciqlop_pyspedas/sciqlop_pyspedas/virtual_products.py sciqlop_pyspedas/sciqlop_pyspedas/__init__.py sciqlop_pyspedas/sciqlop_pyspedas/tests/test_virtual_products.py
git commit -m "feat(sciqlop_pyspedas): register MMS spectra as out-of-process virtual products"
```

---

### Task 5: Live check against real MMS data + visual check

**Files:**
- Test: `sciqlop_pyspedas/sciqlop_pyspedas/tests/test_live.py`

**Precondition:** pyspedas must be importable from the SciQLop dev venv. Check with
`/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -c "import pyspedas; print(pyspedas.__version__)"`.
If it fails, STOP and ask the user to install it (e.g. by enabling the plugin in SciQLop dev mode, which installs plugin dependencies). Do not install it yourself.

- [ ] **Step 1: Write the live test**

`sciqlop_pyspedas/sciqlop_pyspedas/tests/test_live.py`:
```python
"""Real MMS SDC download + mms_part_getspec. Run with: -m live"""
from datetime import datetime, timezone

import numpy as np
import pytest

pytest.importorskip("pyspedas")

from sciqlop_pyspedas import worker  # noqa: E402
from sciqlop_pyspedas.catalog import SOURCES  # noqa: E402

pytestmark = pytest.mark.live

# 2015-10-16 13:00-13:10: MMS1 magnetopause crossing (Burch et al. 2016 EDR day).
START = datetime(2015, 10, 16, 13, 0, tzinfo=timezone.utc).timestamp()
STOP = datetime(2015, 10, 16, 13, 10, tzinfo=timezone.utc).timestamp()


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIQLOP_WORKSPACE_DIR", str(tmp_path))


def test_fpi_ion_energy_and_pitch_angle():
    ions = next(s for s in SOURCES if s.label == "FPI ions")
    energy = worker.worker_callback(START, STOP, source=ions, output="energy", probe="1", data_rate="fast")
    pa = worker.worker_callback(START, STOP, source=ions, output="pa", probe="1", data_rate="fast")
    assert len(energy.time) > 0 and len(pa.time) > 0
    assert np.nanmax(energy.values) > 0
    assert 0 <= np.nanmin(pa.axes[1].values) and np.nanmax(pa.axes[1].values) <= 180
```

- [ ] **Step 2: Run it**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_pyspedas/sciqlop_pyspedas/tests/test_live.py -m live -v`
Expected: PASS (first run downloads FPI, FGM, MEC and EDP files — several minutes).

- [ ] **Step 3: Visual check in real SciQLop**

1. Add `/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_pyspedas` to `extra_plugins_folders` in `~/.config/sciqlop/sciqloppluginssettings.yaml` and enable `sciqlop_pyspedas` there (ask the user before editing their config).
2. Start SciQLop, open a panel, drag `pyspedas/MMS/FPI ions/energy` and `.../pitch angle`, set the panel to 2015-10-16 13:00–13:10.
3. Grab the panel to PNG (`panel.grab().save(...)` from the embedded console, or a screenshot) and LOOK at it: energy y2 axis log in eV, pitch angle 0–180°, z log, data visible across the window, GUI stayed responsive while loading.
4. Check `<workspace>/spedas_data/mms/` exists.

If the energy axis is linear or the colormap is blank, the hints path is wrong: revisit `_default_vp_factory` against `SciQLop/components/plotting/backend/easy_provider.py` before claiming success.

- [ ] **Step 4: Full suite, then commit**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_pyspedas/sciqlop_pyspedas/tests -v`
Expected: all non-live tests pass, live test deselected. Read the real pass count and exit code.

```bash
git add sciqlop_pyspedas/sciqlop_pyspedas/tests/test_live.py
git commit -m "test(sciqlop_pyspedas): live MMS FPI spectra check"
```

- [ ] **Step 5: Update project memory** `pyspedas_plugin_design.md` with what the live/visual check showed (download sizes, compute time per hour of FPI fast, whether the caps need tuning).
