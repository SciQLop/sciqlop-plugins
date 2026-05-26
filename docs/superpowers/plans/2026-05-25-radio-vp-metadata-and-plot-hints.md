# radio plugin: ISTP metadata + plot-hints parity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `sciqlop_radio` virtual products to behavioural parity with the bundled `SciQLop.plugins.speasy_provider` — rich ISTP metadata on every product-tree node and pre/post-fetch plot hints applied through the same translators (`istp_metadata_to_hints`, `variable_as_istp_meta`).

**Architecture:** One new module `sciqlop_radio/hints.py` with (a) an `extract_speasy_index_meta(index)` extractor that mirrors `SciQLop.plugins.speasy_provider.get_node_meta`, (b) four `RichEasy*` subclasses of `SciQLop.components.plotting.backend.easy_provider.Easy*` overriding `plot_hints` + `plot_hints_from_variable`, and (c) a `make_rich_vp(...)` factory. `catalog.py` is updated so `_resolves` returns the inventory index (renamed `_resolve_index`) and `_register_entries` extracts ISTP metadata then plumbs it through the new factory. `continuous.py` adds a `static_meta: dict` field on `ContinuousSource` and uses the same factory. Test-injection points preserved.

**Tech Stack:** Python 3.12+, pydantic v2, pytest, speasy (live import — test-injectable), SciQLop\'s `components.plotting.backend.easy_provider` + `core.istp_hints` + `core.speasy_hints` + `core.plot_hints` + `core.enums` (all stubbed via conftest `MagicMock` in headless tests, real-imported under SciQLop).

**Spec:** `docs/superpowers/specs/2026-05-25-radio-vp-metadata-and-plot-hints-design.md` (commit `d3f343f`)

**Branch state:** `feat/radio-speasy-catalog` — 14 commits ahead of `main` after the design-doc commit. 74 passing / 1 skipped / 5 pre-existing failures (`test_settings.py`, do NOT touch).

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `sciqlop_radio/sciqlop_radio/hints.py` | **Create** | Extractor + RichEasy* subclasses + factory. The whole new surface lives here. |
| `sciqlop_radio/sciqlop_radio/catalog.py` | **Modify** | `_resolves` → `_resolve_index` (returns index, not bool). `_register_entries` extracts metadata via `extract_speasy_index_meta` and passes through `vp_factory` kwarg-style `(path, cb, vptype, *, metadata, labels=None)`. `register_catalog_products` defaults `vp_factory=hints.make_rich_vp`. |
| `sciqlop_radio/sciqlop_radio/continuous.py` | **Modify** | `ContinuousSource` gains `static_meta: dict = field(default_factory=dict)`. The two existing sources get minimal hand-written meta. `register_continuous_products` accepts `vp_factory=None` defaulting to `hints.make_rich_vp` and passes `metadata=src.static_meta`. |
| `sciqlop_radio/sciqlop_radio/tests/test_hints.py` | **Create** | Tests for extractor, two hooks, factory dispatch. |
| `sciqlop_radio/sciqlop_radio/tests/test_catalog.py` | **Modify** | Update `_resolves` tests → `_resolve_index`; update `_register_entries` test signatures (kw-only `metadata=`, `labels=`); add metadata-on-node test; add metadata-extraction-failure-fallback test. |
| `sciqlop_radio/sciqlop_radio/tests/test_continuous.py` | **Modify** | Add `static_meta` field assertion; add factory-passes-metadata test. |
| `sciqlop_radio/sciqlop_radio/tests/conftest.py` | **Modify** | Stub `SciQLop.core.istp_hints`, `SciQLop.core.speasy_hints`, `SciQLop.core.enums`, `SciQLop.components.plotting.backend.easy_provider` so `hints.py` is importable headlessly. |

---

## Task 1: Headless conftest stubs for the new SciQLop modules `hints.py` will import

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/tests/conftest.py`

Background: today's conftest stubs only the SciQLop modules already imported by `catalog.py`/`continuous.py`. `hints.py` will import `SciQLop.core.istp_hints`, `SciQLop.core.speasy_hints`, `SciQLop.core.enums`, `SciQLop.components.plotting.backend.easy_provider`. Without stubs the new test module won't import. We must let real imports win when SciQLop is installed (cf. `feedback_radio_plugin_not_a_template` — the radio plugin IS used under real SciQLop too), and fall back to MagicMock otherwise — the existing pattern.

- [ ] **Step 1: Extend the `_OPTIONAL` list in conftest.py**

Open `sciqlop_radio/sciqlop_radio/tests/conftest.py`. Find the `_OPTIONAL` list (lines ~19-29). Replace with:

```python
_OPTIONAL = [
    "PySide6QtAds",
    "SciQLop",
    "SciQLop.components",
    "SciQLop.components.settings",
    "SciQLop.components.settings.backend",
    "SciQLop.components.theming",
    "SciQLop.components.plotting",
    "SciQLop.components.plotting.backend",
    "SciQLop.components.plotting.backend.easy_provider",
    "SciQLop.core",
    "SciQLop.core.plot_hints",
    "SciQLop.core.istp_hints",
    "SciQLop.core.speasy_hints",
    "SciQLop.core.enums",
    "SciQLopPlots",
]
```

- [ ] **Step 2: Verify the existing test baseline still passes**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/ -x --ignore=sciqlop_radio/tests/test_fetch_live.py 2>&1 | tail -20`

Expected: 74 passed, 1 skipped, 5 failed (test_settings.py — pre-existing, NOT touched by this change).

- [ ] **Step 3: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/tests/conftest.py
git commit -m "test(sciqlop_radio): stub SciQLop modules hints.py will import

Lets the upcoming sciqlop_radio.hints module import cleanly in headless
unit tests. No behaviour change; existing 74-passed baseline holds.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `extract_speasy_index_meta` — write the failing tests

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/tests/test_hints.py`

The extractor mirrors `SciQLop.plugins.speasy_provider.get_node_meta` + `make_product` metadata block. Test it in isolation with fake Speasy `ParameterIndex` objects. Per spec §"Tests" #1–#3.

- [ ] **Step 1: Write the failing test file**

Create `sciqlop_radio/sciqlop_radio/tests/test_hints.py` with the following content:

```python
"""Tests for sciqlop_radio.hints — Speasy-index metadata extraction,
RichEasy* plot-hints overrides, and the make_rich_vp factory."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _fake_index(attrs: dict, *, provider="amda", uid="some_uid"):
    """Build a fake Speasy ParameterIndex: attrs land in __dict__, plus
    spz_uid() / spz_provider() methods returning the supplied strings."""
    ns = SimpleNamespace(**attrs)
    ns.spz_uid = lambda: uid
    ns.spz_provider = lambda: provider
    return ns


def test_extract_keeps_primitive_attributes():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({
        "UNITS": "dB",
        "LABLAXIS": "PSD",
        "SCALETYP": "log",
        "FILLVAL": -1e31,
        "DEPEND_0": "Epoch",
        "DEPEND_1": "frequency",
        "VAR_NOTES": "Calibrated L3 power spectral density",
    })
    meta = extract_speasy_index_meta(idx)
    assert meta["UNITS"] == "dB"
    assert meta["LABLAXIS"] == "PSD"
    assert meta["SCALETYP"] == "log"
    assert meta["FILLVAL"] == -1e31
    assert meta["DEPEND_0"] == "Epoch"
    assert meta["DEPEND_1"] == "frequency"
    assert meta["VAR_NOTES"].startswith("Calibrated")


def test_extract_keeps_lists_of_primitives():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({
        "LABL_PTR_1": ["x", "y", "z"],
        "VALIDMIN": [-100.0, -100.0, -100.0],
    })
    meta = extract_speasy_index_meta(idx)
    assert meta["LABL_PTR_1"] == ["x", "y", "z"]
    assert meta["VALIDMIN"] == [-100.0, -100.0, -100.0]


def test_extract_drops_dicts_callables_and_underscored():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({
        "UNITS": "dB",
        "nested_dict": {"a": 1},          # filtered (dict)
        "method_attr": lambda: None,      # filtered (callable)
        "_private": "hidden",             # filtered (underscore)
    })
    meta = extract_speasy_index_meta(idx)
    assert "UNITS" in meta
    assert "nested_dict" not in meta
    assert "method_attr" not in meta
    assert "_private" not in meta


def test_extract_adds_canonical_speasy_keys():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({"UNITS": "dB"}, provider="cda", uid="WI_L2/PSD")
    meta = extract_speasy_index_meta(idx)
    assert meta["uid"] == "WI_L2/PSD"
    assert meta["provider"] == "cda"
    assert meta["speasy_id"] == "cda/WI_L2/PSD"
    assert meta["stable_id"] == "cda/WI_L2/PSD"


def test_extract_uses_explicit_components_when_supplied():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({"UNITS": "nT"})
    meta = extract_speasy_index_meta(idx, components=["Bx", "By", "Bz"])
    assert meta["components"] == ["Bx", "By", "Bz"]


def test_extract_components_fallback_from_LABL_PTR_1_list():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({"LABL_PTR_1": ["a", "b", "c"]})
    meta = extract_speasy_index_meta(idx)
    assert meta["components"] == ["a", "b", "c"]


def test_extract_components_fallback_to_uid_when_unknown():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({"UNITS": "K"}, uid="my_param")
    meta = extract_speasy_index_meta(idx)
    assert meta["components"] == ["my_param"]


def test_extract_propagates_missing_spz_uid_as_attributeerror():
    """Per spec, the extractor lets it raise; _register_entries catches."""
    from sciqlop_radio.hints import extract_speasy_index_meta
    # No spz_uid attribute at all
    idx = SimpleNamespace(UNITS="dB", spz_provider=lambda: "amda")
    with pytest.raises(AttributeError):
        extract_speasy_index_meta(idx)
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_hints.py -v 2>&1 | tail -20`

Expected: `ModuleNotFoundError: No module named 'sciqlop_radio.hints'` (all 8 tests error out).

---

## Task 3: `extract_speasy_index_meta` — implement and pass

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/hints.py`

- [ ] **Step 1: Write the minimal implementation**

Create `sciqlop_radio/sciqlop_radio/hints.py` with:

```python
"""ISTP metadata + plot-hints parity helpers for sciqlop_radio.

Mirrors what `SciQLop.plugins.speasy_provider` does for native Speasy
products, so our 40 virtual products (38 catalog + 2 continuous) carry
the same rich product-tree metadata and apply the same pre/post-fetch
plot hints as their `speasy/...` siblings.

The three public-ish exports:

- `extract_speasy_index_meta(index, *, components=None) -> dict[str, Any]`
  Mines a Speasy ParameterIndex into a flat primitives-only metadata
  dict suitable for `ProductsModelNode`. Mirrors
  `SciQLop.plugins.speasy_provider.get_node_meta + make_product`.

- `RichEasyScalar / RichEasyVector / RichEasyMultiComponent /
  RichEasySpectrogram` — `EasyProvider` subclasses that override
  `plot_hints` and `plot_hints_from_variable` using SciQLop's
  ISTP translators (same logic as the bundled Speasy plugin).

- `make_rich_vp(path, callback, vp_type, *, metadata, labels=None)
  -> EasyProvider` — internal factory used by catalog.py and
  continuous.py. Replaces the call site of user_api
  `create_virtual_product` (which does not take metadata).
"""
from __future__ import annotations

import ast
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


def _components_from_index(index: Any) -> Optional[list[str]]:
    """Mirror of `SciQLop.plugins.speasy_provider.get_components` reduced
    to the cases the radio catalog actually hits (AMDA + CDA spectrograms).
    Returns None when nothing usable is found — caller falls back to
    `[spz_uid()]`."""
    provider = ""
    try:
        provider = index.spz_provider() or ""
    except Exception:
        pass
    if provider == "amda":
        display = getattr(index, "display_type", "")
        if isinstance(display, str) and display.lower() == "timeseries":
            try:
                return [index.spz_name()]
            except Exception:
                return None
    labl = getattr(index, "LABL_PTR_1", None)
    if isinstance(labl, list):
        return [str(v) for v in labl]
    if isinstance(labl, str):
        try:
            value = ast.literal_eval(labl)
            if isinstance(value, (list, tuple)):
                return [str(v) for v in value]
        except (ValueError, SyntaxError):
            return [s.strip() for s in labl.split(",") if s.strip()]
    lablaxis = getattr(index, "LABLAXIS", None)
    if isinstance(lablaxis, str):
        if lablaxis.startswith("["):
            return [s.strip() for s in lablaxis.strip("[]").split(",") if s.strip()]
        return [lablaxis]
    return None


def extract_speasy_index_meta(
    index: Any, *, components: Optional[list[str]] = None
) -> dict[str, Any]:
    """Mine a Speasy `ParameterIndex` into a flat metadata dict.

    Walks `index.__dict__` keeping primitive values (str/int/float/bool)
    and list-of-primitives. Drops underscored keys, dicts, callables,
    exotic objects (Qt QVariant won't round-trip them). Adds the four
    canonical Speasy keys (`uid`, `provider`, `speasy_id`, `stable_id`)
    and a `components` list.

    Raises whatever `index.spz_uid()` / `index.spz_provider()` raise —
    the caller in catalog.py is responsible for falling back to minimal
    metadata.
    """
    uid = index.spz_uid()
    provider = index.spz_provider()
    speasy_id = f"{provider}/{uid}"

    meta: dict[str, Any] = {}
    for name, value in vars(index).items():
        if name.startswith("_"):
            continue
        if isinstance(value, bool):
            meta[name] = value
        elif isinstance(value, (str, int, float)):
            meta[name] = value
        elif isinstance(value, (list, tuple)) and value and all(
            isinstance(v, (str, int, float, bool)) for v in value
        ):
            meta[name] = list(value)

    meta["uid"] = uid
    meta["provider"] = provider
    meta["speasy_id"] = speasy_id
    meta["stable_id"] = speasy_id
    meta["components"] = components or _components_from_index(index) or [uid]
    return meta
```

- [ ] **Step 2: Run the test, verify all 8 pass**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_hints.py -v 2>&1 | tail -20`

Expected: 8 passed.

- [ ] **Step 3: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/hints.py sciqlop_radio/sciqlop_radio/tests/test_hints.py
git commit -m "feat(sciqlop_radio): extract_speasy_index_meta - mine ParameterIndex into flat dict

Mirrors SciQLop.plugins.speasy_provider.get_node_meta + make_product:
keeps primitives + list-of-primitives off index.__dict__, adds the four
canonical Speasy keys (uid, provider, speasy_id, stable_id) and a
components list. 8 tests cover the extraction, the filtering rules,
and the missing-spz_uid propagation contract.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: `RichEasySpectrogram` hooks — write the failing tests

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/tests/test_hints.py`

Per spec §"Tests" #4–#6.

- [ ] **Step 1: Append the tests**

Append to `sciqlop_radio/sciqlop_radio/tests/test_hints.py`:

```python
# ---------------------------------------------------------------------------
# RichEasySpectrogram overrides
# ---------------------------------------------------------------------------

import sys
from unittest.mock import MagicMock

_SCIQLOP_REAL = not isinstance(
    sys.modules.get("SciQLop.core.plot_hints"), MagicMock
)


def _fake_node_with_meta(meta):
    """Mimic the bits of ProductsModelNode the hooks actually call."""
    return SimpleNamespace(metadata=lambda: meta)


def test_plot_hints_translates_node_metadata_to_z_axis():
    if not _SCIQLOP_REAL:
        pytest.skip("requires real SciQLop install - PlotHints is a MagicMock under headless conftest")
    from sciqlop_radio.hints import RichEasySpectrogram
    from SciQLop.core.plot_hints import PlotHints

    spec = RichEasySpectrogram.__new__(RichEasySpectrogram)
    node = _fake_node_with_meta({
        "DISPLAY_TYPE": "spectrogram",
        "UNITS": "dB/Hz",
        "LABLAXIS": "PSD",
        "SCALETYP": "log",
    })
    hints = spec.plot_hints(node)
    assert isinstance(hints, PlotHints)
    assert hints.display_type == "spectrogram"
    assert hints.z.unit == "dB/Hz"
    assert hints.z.label == "PSD"
    assert hints.z.scale == "log"


def test_plot_hints_returns_empty_on_metadata_exception():
    if not _SCIQLOP_REAL:
        pytest.skip("requires real SciQLop install")
    from sciqlop_radio.hints import RichEasySpectrogram
    from SciQLop.core.plot_hints import PlotHints

    spec = RichEasySpectrogram.__new__(RichEasySpectrogram)

    def broken_metadata():
        raise RuntimeError("node gone")

    node = SimpleNamespace(metadata=broken_metadata)
    hints = spec.plot_hints(node)
    assert isinstance(hints, PlotHints)
    # Empty PlotHints - no axis info populated
    assert hints.z.label is None and hints.z.unit is None


def _fake_speasy_variable(z_meta, freq_meta, freq=None):
    """Mimic the bits of SpeasyVariable variable_as_istp_meta touches."""
    from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
    from speasy.products.variable import SpeasyVariable
    import numpy as np

    if freq is None:
        freq = np.array([10.0, 20.0, 30.0], dtype=np.float64)
    times = np.array(["2024-01-01T00:00:00", "2024-01-01T00:00:01"],
                     dtype="datetime64[ns]")
    time_axis = VariableTimeAxis(values=times)
    freq_axis = VariableAxis(name=freq_meta.get("LABLAXIS", ""),
                             values=freq, meta=freq_meta)
    data = np.zeros((2, 3), dtype=np.float64)
    values = DataContainer(values=data, meta=z_meta,
                           name=z_meta.get("LABLAXIS", "test"))
    return SpeasyVariable(axes=[time_axis, freq_axis], values=values,
                          columns=["test"])


def test_plot_hints_from_variable_populates_y2_from_freq_axis():
    if not _SCIQLOP_REAL:
        pytest.skip("requires real SciQLop install")
    from sciqlop_radio.hints import RichEasySpectrogram
    from SciQLop.core.enums import GraphType
    from SciQLop.core.plot_hints import PlotHints

    spec = RichEasySpectrogram.__new__(RichEasySpectrogram)
    # graph_type returns ColorMap -> variable_as_istp_meta sets DISPLAY_TYPE
    spec.graph_type = lambda node: GraphType.ColorMap
    node = _fake_node_with_meta({})
    var = _fake_speasy_variable(
        z_meta={"UNITS": "dB", "LABLAXIS": "PSD", "SCALETYP": "log"},
        freq_meta={"UNITS": "Hz", "LABLAXIS": "Frequency", "SCALETYP": "log"},
    )
    hints = spec.plot_hints_from_variable(node, var)
    assert isinstance(hints, PlotHints)
    assert hints.y2.unit == "Hz"
    assert hints.y2.label == "Frequency"
    assert hints.y2.scale == "log"


def test_plot_hints_from_variable_returns_empty_on_exception():
    if not _SCIQLOP_REAL:
        pytest.skip("requires real SciQLop install")
    from sciqlop_radio.hints import RichEasySpectrogram
    from SciQLop.core.plot_hints import PlotHints

    spec = RichEasySpectrogram.__new__(RichEasySpectrogram)
    spec.graph_type = lambda node: None
    node = _fake_node_with_meta({})
    # not a SpeasyVariable -> variable_as_istp_meta raises
    hints = spec.plot_hints_from_variable(node, "not a variable")
    assert isinstance(hints, PlotHints)
```

Note: `RichEasySpectrogram.__new__(RichEasySpectrogram)` sidesteps `EasyProvider.__init__` (which would try to register on `ProductsModel`). We only need the methods, not a real init — these are unit tests of pure overrides.

- [ ] **Step 2: Run the new tests**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_hints.py -v 2>&1 | tail -25`

Expected (headless): 8 passed (Task 3) + 4 skipped (the new shape-asserting hook tests).
Expected (with SciQLop): 8 passed + 4 errors `AttributeError: module 'sciqlop_radio.hints' has no attribute 'RichEasySpectrogram'`.

---

## Task 5: `RichEasy*` subclasses — implement and pass

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/hints.py`

- [ ] **Step 1: Add the subclasses**

Append to `sciqlop_radio/sciqlop_radio/hints.py`:

```python
# ---------------------------------------------------------------------------
# RichEasy* subclasses - override plot_hints + plot_hints_from_variable
# exactly as SciQLop.plugins.speasy_provider.SpeasyPlugin does.
# ---------------------------------------------------------------------------

from SciQLop.components.plotting.backend.easy_provider import (  # noqa: E402
    EasyScalar as _EasyScalar,
    EasyVector as _EasyVector,
    EasyMultiComponent as _EasyMultiComponent,
    EasySpectrogram as _EasySpectrogram,
)
from SciQLop.core.plot_hints import PlotHints  # noqa: E402
from SciQLop.core.istp_hints import istp_metadata_to_hints  # noqa: E402
from SciQLop.core.speasy_hints import variable_as_istp_meta  # noqa: E402
from SciQLop.core.enums import GraphType  # noqa: E402


def _plot_hints_from_node(node) -> PlotHints:
    try:
        return istp_metadata_to_hints(node.metadata())
    except Exception:
        log.debug("plot_hints failed for %s", node, exc_info=True)
        return PlotHints()


def _plot_hints_from_variable(self, node, variable) -> PlotHints:
    try:
        meta = variable_as_istp_meta(variable)
        if self.graph_type(node) == GraphType.ColorMap:
            meta.setdefault("DISPLAY_TYPE", "spectrogram")
        return istp_metadata_to_hints(meta)
    except Exception:
        log.debug("plot_hints_from_variable failed for %s", node, exc_info=True)
        return PlotHints()


class RichEasyScalar(_EasyScalar):
    def plot_hints(self, node) -> PlotHints:
        return _plot_hints_from_node(node)

    def plot_hints_from_variable(self, node, variable) -> PlotHints:
        return _plot_hints_from_variable(self, node, variable)


class RichEasyVector(_EasyVector):
    def plot_hints(self, node) -> PlotHints:
        return _plot_hints_from_node(node)

    def plot_hints_from_variable(self, node, variable) -> PlotHints:
        return _plot_hints_from_variable(self, node, variable)


class RichEasyMultiComponent(_EasyMultiComponent):
    def plot_hints(self, node) -> PlotHints:
        return _plot_hints_from_node(node)

    def plot_hints_from_variable(self, node, variable) -> PlotHints:
        return _plot_hints_from_variable(self, node, variable)


class RichEasySpectrogram(_EasySpectrogram):
    def plot_hints(self, node) -> PlotHints:
        return _plot_hints_from_node(node)

    def plot_hints_from_variable(self, node, variable) -> PlotHints:
        return _plot_hints_from_variable(self, node, variable)
```

- [ ] **Step 2: Run the test**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_hints.py -v 2>&1 | tail -20`

Expected (headless): 8 passed + 4 skipped.
Expected (with SciQLop): 12 passed.

- [ ] **Step 3: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/hints.py sciqlop_radio/sciqlop_radio/tests/test_hints.py
git commit -m "feat(sciqlop_radio): RichEasy* subclasses with plot-hints overrides

Mirror SciQLop.plugins.speasy_provider.SpeasyPlugin: plot_hints reads
the node metadata through istp_metadata_to_hints (pre-fetch - sets z
and y axes), plot_hints_from_variable extracts ISTP meta from the live
SpeasyVariable through variable_as_istp_meta (post-fetch - sets y2,
which cant live on the node because Qt QVariant rejects nested dicts).

Four 7-line subclasses cover Scalar/Vector/MultiComponent/Spectrogram -
catalog is 100%% spectrogram today but the cost of future-proofing the
other three is trivial vs. discovering later that a vector entry has
no hints.

Tests for the two hooks are headless-skip-guarded (shape-asserting on
real PlotHints; MagicMocks dont have a usable shape).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: `make_rich_vp` factory — write failing tests then implement

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/tests/test_hints.py`
- Modify: `sciqlop_radio/sciqlop_radio/hints.py`

Per spec §"Tests" #7.

- [ ] **Step 1: Append the factory tests**

Append to `sciqlop_radio/sciqlop_radio/tests/test_hints.py`:

```python
# ---------------------------------------------------------------------------
# make_rich_vp dispatch
# ---------------------------------------------------------------------------


def _no_op_callback(start: float, stop: float):
    return None


@pytest.mark.skipif(not _SCIQLOP_REAL,
                    reason="requires real SciQLop install - EasyProvider subclasses cant init under MagicMock parents")
def test_make_rich_vp_dispatches_to_spectrogram():
    from sciqlop_radio.hints import make_rich_vp, RichEasySpectrogram
    from SciQLop.user_api.virtual_products import VirtualProductType
    vp = make_rich_vp("radio/test/spec", _no_op_callback,
                       VirtualProductType.Spectrogram,
                       metadata={"DISPLAY_TYPE": "spectrogram"})
    assert isinstance(vp, RichEasySpectrogram)


@pytest.mark.skipif(not _SCIQLOP_REAL,
                    reason="requires real SciQLop install")
def test_make_rich_vp_dispatches_to_scalar_with_label():
    from sciqlop_radio.hints import make_rich_vp, RichEasyScalar
    from SciQLop.user_api.virtual_products import VirtualProductType
    vp = make_rich_vp("radio/test/sca", _no_op_callback,
                       VirtualProductType.Scalar,
                       metadata={"UNITS": "K"}, labels=["temp"])
    assert isinstance(vp, RichEasyScalar)


@pytest.mark.skipif(not _SCIQLOP_REAL,
                    reason="requires real SciQLop install")
def test_make_rich_vp_dispatches_to_vector_with_labels():
    from sciqlop_radio.hints import make_rich_vp, RichEasyVector
    from SciQLop.user_api.virtual_products import VirtualProductType
    vp = make_rich_vp("radio/test/vec", _no_op_callback,
                       VirtualProductType.Vector,
                       metadata={"UNITS": "nT"}, labels=["Bx", "By", "Bz"])
    assert isinstance(vp, RichEasyVector)


@pytest.mark.skipif(not _SCIQLOP_REAL,
                    reason="requires real SciQLop install")
def test_make_rich_vp_dispatches_to_multicomponent_with_labels():
    from sciqlop_radio.hints import make_rich_vp, RichEasyMultiComponent
    from SciQLop.user_api.virtual_products import VirtualProductType
    vp = make_rich_vp("radio/test/mc", _no_op_callback,
                       VirtualProductType.MultiComponent,
                       metadata={"UNITS": "1"}, labels=["a", "b", "c", "d", "e"])
    assert isinstance(vp, RichEasyMultiComponent)
```

- [ ] **Step 2: Verify the tests fail (or skip headless)**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_hints.py -v 2>&1 | tail -10`

Expected (headless): 8 passed + 8 skipped (the four hook tests + four factory tests).
Expected (with SciQLop): 12 passed + 4 failed `ImportError: cannot import name 'make_rich_vp' from 'sciqlop_radio.hints'`.

- [ ] **Step 3: Implement `make_rich_vp`**

Append to `sciqlop_radio/sciqlop_radio/hints.py`:

```python
# ---------------------------------------------------------------------------
# make_rich_vp - internal factory that replaces the create_virtual_product
# call site in catalog.py / continuous.py (which doesnt take metadata).
# ---------------------------------------------------------------------------


def make_rich_vp(path: str, callback, vp_type, *, metadata: dict,
                 labels: Optional[list[str]] = None):
    """Construct the right RichEasy* subclass for `vp_type` with the
    supplied metadata pre-populated on the underlying ProductsModelNode.

    `vp_type` is a member of `SciQLop.user_api.virtual_products.VirtualProductType`.
    `labels` is required for Scalar (1 label), Vector (3 labels), and
    MultiComponent (any non-empty list); ignored for Spectrogram.
    """
    from SciQLop.user_api.virtual_products import VirtualProductType

    if vp_type == VirtualProductType.Spectrogram:
        return RichEasySpectrogram(path, callback, metadata=metadata)
    if vp_type == VirtualProductType.Scalar:
        if not labels:
            raise ValueError("Scalar requires labels=[<one_label>]")
        return RichEasyScalar(path, callback, component_name=labels[0],
                               metadata=metadata)
    if vp_type == VirtualProductType.Vector:
        if not labels or len(labels) != 3:
            raise ValueError("Vector requires labels=[x, y, z]")
        return RichEasyVector(path, callback, components_names=labels,
                               metadata=metadata)
    if vp_type == VirtualProductType.MultiComponent:
        if not labels:
            raise ValueError("MultiComponent requires non-empty labels")
        return RichEasyMultiComponent(path, callback, components_names=labels,
                                       metadata=metadata)
    raise ValueError(f"unknown VirtualProductType: {vp_type!r}")
```

- [ ] **Step 4: Run the test**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_hints.py -v 2>&1 | tail -10`

Expected (headless): 8 passed + 8 skipped.
Expected (with SciQLop): 16 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/hints.py sciqlop_radio/sciqlop_radio/tests/test_hints.py
git commit -m "feat(sciqlop_radio): make_rich_vp - factory dispatching by VirtualProductType

Internal factory used by catalog.py + continuous.py to construct the
right RichEasy* subclass with pre-populated metadata. Replaces the
user_api create_virtual_product call (which forces metadata={}).

Four dispatch tests, skip-guarded under headless conftest because the
EasyProvider parent classes cant instantiate against MagicMock bases.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: catalog.py — `_resolves` → `_resolve_index` rename

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/catalog.py`
- Modify: `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`

- [ ] **Step 1: Update the two existing `_resolves` tests to test `_resolve_index`**

In `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`, find:

```python
def test_resolves_true_when_uid_in_inventory():
    from sciqlop_radio.catalog import _resolves
    sp = _fake_speasy({"amda": {"wnd_swaves_rad1": object()}})
    assert _resolves("amda/wnd_swaves_rad1", sp) is True


def test_resolves_false_when_uid_missing_or_provider_absent():
    from sciqlop_radio.catalog import _resolves
    sp = _fake_speasy({"amda": {"other": object()}})
    assert _resolves("amda/wnd_swaves_rad1", sp) is False
    assert _resolves("cda/anything", sp) is False
```

Replace with:

```python
def test_resolve_index_returns_index_when_found():
    from sciqlop_radio.catalog import _resolve_index
    sentinel = object()
    sp = _fake_speasy({"amda": {"wnd_swaves_rad1": sentinel}})
    assert _resolve_index("amda/wnd_swaves_rad1", sp) is sentinel


def test_resolve_index_returns_none_when_uid_missing_or_provider_absent():
    from sciqlop_radio.catalog import _resolve_index
    sp = _fake_speasy({"amda": {"other": object()}})
    assert _resolve_index("amda/wnd_swaves_rad1", sp) is None
    assert _resolve_index("cda/anything", sp) is None
```

- [ ] **Step 2: Run, verify they fail**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_catalog.py::test_resolve_index_returns_index_when_found sciqlop_radio/tests/test_catalog.py::test_resolve_index_returns_none_when_uid_missing_or_provider_absent -v 2>&1 | tail -10`

Expected: 2 errors `ImportError: cannot import name '_resolve_index' from 'sciqlop_radio.catalog'`.

- [ ] **Step 3: Update `catalog.py` — `_resolves` → `_resolve_index`**

In `sciqlop_radio/sciqlop_radio/catalog.py`, find the existing function (lines ~95-105):

```python
def _resolves(speasy_id: str, speasy_module) -> bool:
    """True if `<provider>/<uid>` is present in the in-memory Speasy inventory.

    SciQLop's speasy_provider builds the inventories at startup (before our
    load() runs), so this is a dict lookup, not a network call."""
    provider, _, uid = speasy_id.partition("/")
    flat = getattr(speasy_module.inventories.flat_inventories, provider, None)
    if flat is None:
        return False
    params = getattr(flat, "parameters", None) or {}
    return uid in params
```

Replace with:

```python
def _resolve_index(speasy_id: str, speasy_module):
    """Return the Speasy `ParameterIndex` for `<provider>/<uid>` if present
    in the in-memory inventory, else None.

    SciQLop's speasy_provider builds the inventories at startup (before our
    load() runs), so this is a dict lookup, not a network call."""
    provider, _, uid = speasy_id.partition("/")
    flat = getattr(speasy_module.inventories.flat_inventories, provider, None)
    if flat is None:
        return None
    params = getattr(flat, "parameters", None) or {}
    return params.get(uid)
```

- [ ] **Step 4: Update the single call site in `_register_entries`**

In `sciqlop_radio/sciqlop_radio/catalog.py`, find inside `_register_entries`:

```python
        if not _resolves(e.speasy_id, speasy_module):
            log.info("catalog: skip %s — %s not in Speasy inventory", e.path, e.speasy_id)
            continue
```

Replace with:

```python
        index = _resolve_index(e.speasy_id, speasy_module)
        if index is None:
            log.info("catalog: skip %s — %s not in Speasy inventory", e.path, e.speasy_id)
            continue
```

- [ ] **Step 5: Run all catalog tests**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_catalog.py -v 2>&1 | tail -30`

Expected: all 24 catalog tests pass (the two renamed tests + the original 22, unchanged — `_register_entries` still calls `create_vp(path, cb, vptype, **kw)`).

- [ ] **Step 6: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/catalog.py sciqlop_radio/sciqlop_radio/tests/test_catalog.py
git commit -m "refactor(sciqlop_radio): _resolves -> _resolve_index returning the index

Mechanical rename. Function now returns the Speasy ParameterIndex (or
None) instead of a bool so the upcoming metadata-enrichment step can
reuse the same lookup. Single call site in _register_entries adjusted.
Two tests renamed accordingly. Behaviour unchanged.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: catalog.py — `_register_entries` extracts metadata and passes via `vp_factory`

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`
- Modify: `sciqlop_radio/sciqlop_radio/catalog.py`

Per spec §"Tests" #8–#9.

- [ ] **Step 1: Add `_fake_index` helper to test_catalog.py**

In `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`, find the existing `_fake_speasy` helper (lines ~93-113). Add this helper ABOVE it:

```python
def _fake_index(uid: str, provider: str, attrs: dict | None = None):
    """Mimic the bits of a Speasy ParameterIndex extract_speasy_index_meta
    touches: attrs land in __dict__, plus spz_uid() / spz_provider()."""
    ns = SimpleNamespace(**(attrs or {}))
    ns.spz_uid = lambda: uid
    ns.spz_provider = lambda: provider
    return ns
```

(The existing `_fake_speasy` body works unchanged — its values are passed through as-is, so either a plain `object()` or a `_fake_index(...)` instance is fine.)

- [ ] **Step 2: Update the three existing `_register_entries` tests for the new factory signature**

Replace `test_register_entries_registers_resolvable_skips_unresolvable`:

```python
def test_register_entries_registers_resolvable_skips_unresolvable():
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {"ok": _fake_index("ok", "amda",
                                                   {"UNITS": "dB"})}})
    entries = [
        CuratedRadioProduct(path="Wind/WAVES/RAD1", speasy_id="amda/ok"),
        CuratedRadioProduct(path="Gone/Product", speasy_id="amda/missing"),
    ]
    created = []

    def vp_factory(path, cb, vptype, *, metadata, labels=None):
        created.append((path, vptype, metadata, labels))
        return f"VP[{path}]"

    reg = _register_entries(entries, vp_factory, _fake_vp_types(), sp)
    assert [c[0] for c in created] == ["radio/Wind/WAVES/RAD1"]
    assert created[0][1] == "SPEC"
    assert created[0][2]["speasy_id"] == "amda/ok"
    assert created[0][2]["UNITS"] == "dB"
    assert reg.vps == {"radio/Wind/WAVES/RAD1": "VP[radio/Wind/WAVES/RAD1]"}
```

Replace `test_register_entries_passes_labels_for_non_spectrogram`:

```python
def test_register_entries_passes_labels_for_non_spectrogram():
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {"v": _fake_index("v", "amda", {"UNITS": "nT"})}})
    entries = [
        CuratedRadioProduct(
            path="X/Vec", speasy_id="amda/v", type="vector", labels=["a", "b", "c"]
        )
    ]
    created = []

    def vp_factory(path, cb, vptype, *, metadata, labels=None):
        created.append((path, vptype, metadata, labels))
        return path

    _register_entries(entries, vp_factory, _fake_vp_types(), sp)
    assert created[0][1] == "VEC"
    assert created[0][3] == ["a", "b", "c"]
    # explicit labels override the index-derived components
    assert created[0][2]["components"] == ["a", "b", "c"]
```

Replace `test_register_entries_continues_when_create_vp_raises`:

```python
def test_register_entries_continues_when_create_vp_raises():
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {
        "a": _fake_index("a", "amda"),
        "b": _fake_index("b", "amda"),
    }})
    entries = [
        CuratedRadioProduct(path="One", speasy_id="amda/a"),
        CuratedRadioProduct(path="Two", speasy_id="amda/b"),
    ]

    def vp_factory(path, cb, vptype, *, metadata, labels=None):
        if path == "radio/One":
            raise RuntimeError("boom")
        return path

    reg = _register_entries(entries, vp_factory, _fake_vp_types(), sp)
    assert list(reg.vps) == ["radio/Two"]
```

- [ ] **Step 3: Add the metadata-fallback test**

Append after `test_register_entries_continues_when_create_vp_raises`:

```python
def test_register_entries_falls_back_to_minimal_meta_when_extraction_raises(caplog):
    """When extract_speasy_index_meta raises (e.g. index missing spz_uid),
    the entry still registers - just with minimal metadata."""
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    # Index without spz_uid -> extract_speasy_index_meta will AttributeError
    bad = SimpleNamespace(UNITS="dB", spz_provider=lambda: "amda")
    sp = _fake_speasy({"amda": {"bad": bad}})
    entries = [CuratedRadioProduct(path="Bad/One", speasy_id="amda/bad")]
    created = []

    def vp_factory(path, cb, vptype, *, metadata, labels=None):
        created.append((path, metadata))
        return path

    with caplog.at_level("WARNING"):
        _register_entries(entries, vp_factory, _fake_vp_types(), sp)
    assert created and created[0][0] == "radio/Bad/One"
    # minimal fallback: speasy_id + stable_id + provider
    meta = created[0][1]
    assert meta["speasy_id"] == "amda/bad"
    assert meta["stable_id"] == "amda/bad"
    assert meta["provider"] == "amda"
    assert any("metadata extraction failed" in r.message for r in caplog.records)
```

- [ ] **Step 4: Run the four updated/new tests, verify they fail**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_catalog.py -k "register_entries" -v 2>&1 | tail -20`

Expected: 4 failures (signature mismatch — `_register_entries` still calls `create_vp(path, cb, vptype, **kw)`).

- [ ] **Step 5: Update `_register_entries` in catalog.py**

In `sciqlop_radio/sciqlop_radio/catalog.py`, replace `_register_entries` (lines ~142-165):

```python
def _register_entries(
    entries: list["CuratedRadioProduct"],
    vp_factory: Callable[..., Any],
    vp_types,
    speasy_module,
) -> CatalogRegistration:
    from .hints import extract_speasy_index_meta

    reg = CatalogRegistration()
    for e in entries:
        index = _resolve_index(e.speasy_id, speasy_module)
        if index is None:
            log.info("catalog: skip %s — %s not in Speasy inventory", e.path, e.speasy_id)
            continue
        try:
            meta = extract_speasy_index_meta(index, components=e.labels)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "catalog: metadata extraction failed for %s: %s — falling back to minimal meta",
                e.path, exc,
            )
            provider, _, uid = e.speasy_id.partition("/")
            meta = {"speasy_id": e.speasy_id, "stable_id": e.speasy_id,
                    "provider": provider,
                    "components": e.labels or [uid]}
        vptype = _vp_type_for(e.type, vp_types)
        cb = _build_callback(e, speasy_module)
        path = f"radio/{e.path}"
        try:
            vp = vp_factory(path, cb, vptype, metadata=meta, labels=e.labels)
        except Exception as exc:  # noqa: BLE001
            log.exception("catalog: vp_factory failed for %s: %s", path, exc)
            continue
        reg.vps[path] = vp
    return reg
```

- [ ] **Step 6: Update `register_catalog_products` to default `vp_factory`**

In the same file, replace `register_catalog_products` (lines ~168-189):

```python
def register_catalog_products(
    catalog_path: Union[str, Path], *, speasy_module=None,
    vp_factory: Optional[Callable[..., Any]] = None,
) -> Optional[CatalogRegistration]:
    """Read the catalog and register one virtual product per resolvable entry.

    Returns an empty `CatalogRegistration` when the catalog is empty/missing,
    and `None` when SciQLop's virtual-products API isn't importable (headless
    tests) — mirroring `continuous.register_continuous_products`."""
    entries = load_catalog(catalog_path)
    if not entries:
        return CatalogRegistration()
    try:
        from SciQLop.user_api.virtual_products import VirtualProductType
    except ImportError as exc:
        log.warning("catalog: SciQLop user_api unavailable: %s", exc)
        return None
    if speasy_module is None:
        import speasy as speasy_module  # noqa: PLW0127
    if vp_factory is None:
        from .hints import make_rich_vp
        vp_factory = make_rich_vp
    return _register_entries(entries, vp_factory, VirtualProductType, speasy_module)
```

- [ ] **Step 7: Run all catalog tests, verify all pass**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_catalog.py -v 2>&1 | tail -30`

Expected: 25 passed (24 original + 1 new fallback test).

- [ ] **Step 8: Run the full suite baseline check**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/ --ignore=sciqlop_radio/tests/test_fetch_live.py 2>&1 | tail -5`

Expected: at least 75 passed (the 74 baseline + the new fallback test). The 5 pre-existing `test_settings.py` failures unchanged.

- [ ] **Step 9: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/catalog.py sciqlop_radio/sciqlop_radio/tests/test_catalog.py
git commit -m "feat(sciqlop_radio): _register_entries extracts ISTP metadata, defaults vp_factory to make_rich_vp

_register_entries reuses the resolved ParameterIndex to call
extract_speasy_index_meta, then passes the resulting metadata to
vp_factory (new kw-only signature: (path, cb, vptype, *, metadata,
labels=None)). On extraction failure it warns and falls back to a
minimal {speasy_id, stable_id, provider, components} so the entry
still registers.

register_catalog_products defaults vp_factory to hints.make_rich_vp;
test-injection point preserved. Three _register_entries tests updated
for the new signature + a fourth test pins the fallback path.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: continuous.py — `static_meta` field + factory swap

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/tests/test_continuous.py`
- Modify: `sciqlop_radio/sciqlop_radio/continuous.py`

Per spec §"Tests" #11.

- [ ] **Step 1: Append new tests**

Append to `sciqlop_radio/sciqlop_radio/tests/test_continuous.py`:

```python
# ---------------------------------------------------------------------------
# static_meta + vp_factory injection
# ---------------------------------------------------------------------------


def test_continuous_sources_have_minimal_static_meta():
    """Both continuous sources must carry the minimum needed for plot hints:
    DISPLAY_TYPE=spectrogram, SCALETYP=log, a description, a provider tag."""
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES
    for src in CONTINUOUS_SOURCES:
        meta = src.static_meta
        assert meta.get("DISPLAY_TYPE") == "spectrogram", src.vp_path
        assert meta.get("SCALETYP") == "log", src.vp_path
        assert "description" in meta, src.vp_path
        assert meta.get("provider") == "radiospectra", src.vp_path


def test_register_continuous_products_passes_static_meta_to_factory(tmp_path, monkeypatch):
    """register_continuous_products must forward each source's static_meta
    through the injected vp_factory."""
    import sys
    from types import SimpleNamespace
    fake_vp_module = SimpleNamespace(
        VirtualProductType=SimpleNamespace(Spectrogram="SPEC"),
    )
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.virtual_products", fake_vp_module)

    from sciqlop_radio.continuous import register_continuous_products, CONTINUOUS_SOURCES
    captured = []

    def vp_factory(path, cb, vptype, *, metadata, labels=None):
        captured.append((path, vptype, metadata))
        return path

    out = register_continuous_products(
        cache_dir=tmp_path,
        open_and_convert=lambda p: None,
        vp_factory=vp_factory,
    )
    assert out is not None
    assert len(captured) == len(CONTINUOUS_SOURCES)
    for (path, vptype, metadata), src in zip(captured, CONTINUOUS_SOURCES):
        assert path == src.vp_path
        assert vptype == "SPEC"
        assert metadata is src.static_meta
```

- [ ] **Step 2: Run the new tests, verify they fail**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_continuous.py -k "static_meta or factory" -v 2>&1 | tail -15`

Expected: 2 failures — `AttributeError: 'ContinuousSource' object has no attribute 'static_meta'` and signature mismatch on the factory call.

- [ ] **Step 3: Update `ContinuousSource` dataclass in `continuous.py`**

In `sciqlop_radio/sciqlop_radio/continuous.py`, find the `ContinuousSource` dataclass (lines ~39-53). Replace with:

```python
@dataclass(frozen=True)
class ContinuousSource:
    """One entry in the continuous-source registry.

    `attrs_factory` returns the `sunpy.net.attrs` list (excluding `a.Time`,
    which we add per call) — lazy because sunpy/radiospectra imports are
    slow and should only fire when SciQLop actually drags a product onto
    a panel.

    `static_meta` is the ISTP-ish metadata dict surfaced on the product-
    tree node and used by RichEasySpectrogram.plot_hints (pre-fetch).
    Frequency-axis and color-axis units typically come from the parsed
    SpeasyVariable via plot_hints_from_variable (post-fetch), so this is
    intentionally minimal: just DISPLAY_TYPE, SCALETYP, description, and
    a provider tag for tooltips.
    """

    vp_path: str
    label: str
    attrs_factory: Callable[[], list]
    max_files: int = MAX_FILES_PER_CALL
    static_meta: dict = field(default_factory=dict)
```

- [ ] **Step 4: Replace the `CONTINUOUS_SOURCES` list block**

In the same file, find the `CONTINUOUS_SOURCES` list and the preceding comment (lines ~71-87). Replace with:

```python
# PSP/FIELDS RFS L3 (LFR + HFR) is served via the curated catalog
# (radio/PSP/FIELDS/RFS_*/...) sourced from CDAWeb — calibrated PSD flux
# with a real frequency axis, strictly better than the raw radiospectra
# files we'd fetch here. Don't add a continuous PSP RFS VP back without
# also dropping the catalog entry.

_EOVSA_META = {
    "DISPLAY_TYPE": "spectrogram",
    "SCALETYP": "log",
    "description": "EOVSA solar microwave dynamic spectrum (1-18 GHz)",
    "provider": "radiospectra",
}

_ILOFAR_META = {
    "DISPLAY_TYPE": "spectrogram",
    "SCALETYP": "log",
    "description": "ILOFAR mode 357 BST dynamic spectrum (10-240 MHz)",
    "provider": "radiospectra",
}

CONTINUOUS_SOURCES: list[ContinuousSource] = [
    ContinuousSource(
        vp_path="radio/eovsa",
        label="EOVSA",
        attrs_factory=_attrs_eovsa,
        static_meta=_EOVSA_META,
    ),
    ContinuousSource(
        vp_path="radio/ilofar",
        label="ILOFAR (mode 357 BST)",
        attrs_factory=_attrs_ilofar,
        static_meta=_ILOFAR_META,
    ),
]
```

- [ ] **Step 5: Update `register_continuous_products`**

In the same file, replace `register_continuous_products` (last function, lines ~262-286):

```python
def register_continuous_products(
    cache_dir: Path,
    open_and_convert: Callable[[Path], Any],
    *,
    vp_factory: Optional[Callable[..., Any]] = None,
) -> Optional[ContinuousRegistration]:
    """Register one VP per `ContinuousSource`. Returns None when SciQLop's
    virtual-products API isn't importable (headless tests).

    `vp_factory` defaults to `sciqlop_radio.hints.make_rich_vp` so the VPs
    carry the same plot-hints overrides as the catalog. Tests can inject
    a fake."""
    try:
        from SciQLop.user_api.virtual_products import VirtualProductType
    except ImportError as exc:
        log.warning("continuous: SciQLop user_api unavailable: %s", exc)
        return None

    if vp_factory is None:
        from .hints import make_rich_vp
        vp_factory = make_rich_vp

    reg = ContinuousRegistration()
    for src in CONTINUOUS_SOURCES:
        cb = _build_callback(src, cache_dir, open_and_convert)
        try:
            vp = vp_factory(src.vp_path, cb, VirtualProductType.Spectrogram,
                             metadata=src.static_meta)
        except Exception as exc:  # noqa: BLE001
            log.exception("continuous: vp_factory failed for %s: %s",
                          src.vp_path, exc)
            continue
        reg.vps[src.vp_path] = vp
    return reg
```

- [ ] **Step 6: Run all continuous tests, verify all pass**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/test_continuous.py -v 2>&1 | tail -20`

Expected: all continuous tests pass (8 original + 2 new = 10 minimum).

- [ ] **Step 7: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/continuous.py sciqlop_radio/sciqlop_radio/tests/test_continuous.py
git commit -m "feat(sciqlop_radio): continuous VPs carry static_meta + use rich vp_factory

ContinuousSource gains a static_meta dict; both sources (eovsa, ilofar)
get minimal pre-fetch metadata (DISPLAY_TYPE=spectrogram, SCALETYP=log,
description, provider=radiospectra). Frequency-axis + color-axis units
come from the parsed SpeasyVariable via the post-fetch hook.

register_continuous_products grows an optional vp_factory kwarg
defaulting to hints.make_rich_vp - same factory the catalog uses, so
both sets of VPs apply identical plot hints.

Two new tests pin the static_meta + factory pass-through.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: full-suite verification + handover doc

**Files:**
- Modify: `docs/handover-radio-speasy-catalog-2026-05-25.md`

- [ ] **Step 1: Run the full test suite (radio plugin)**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && python -m pytest sciqlop_radio/tests/ --ignore=sciqlop_radio/tests/test_fetch_live.py 2>&1 | tail -10`

Expected: ≥83 passed, 1 skipped (existing), 4 skipped (new headless-only) — total ≥ 88, plus the 5 pre-existing `test_settings.py` failures (unchanged from baseline).

If failures appear OUTSIDE `test_settings.py`, stop and diagnose — they're regressions introduced by this branch.

- [ ] **Step 2: Run the full test suite from the plugins_sciqlop root**

Run: `python -m pytest --ignore=sciqlop_radio/sciqlop_radio/tests/test_fetch_live.py 2>&1 | tail -10`

Expected: no NEW failures outside the pre-existing `test_settings.py` set.

- [ ] **Step 3: Capture the new branch tip**

Run: `cd /var/home/jeandet/Documents/prog/plugins_sciqlop && git rev-parse --short HEAD`

Copy the output (e.g. `a1b2c3d`) — used in Step 4.

- [ ] **Step 4: Append handover-doc update**

Open `docs/handover-radio-speasy-catalog-2026-05-25.md` and append a new section at the bottom (replace `<new-tip-sha>` with the SHA from Step 3):

```markdown
## Update 2026-05-25 — metadata + plot-hints parity

Branch advanced from `b9e5082` to <new-tip-sha> with parity work:

- New `sciqlop_radio/sciqlop_radio/hints.py` (~150 LOC): `extract_speasy_index_meta` (Speasy ParameterIndex -> flat metadata dict), four `RichEasy*` subclasses overriding `plot_hints` + `plot_hints_from_variable` exactly as `SciQLop.plugins.speasy_provider.SpeasyPlugin` does, `make_rich_vp` factory.
- `catalog.py`: `_resolves` -> `_resolve_index` (returns the index); `_register_entries` extracts ISTP metadata and passes through `vp_factory` (kw-only signature: `(path, cb, vptype, *, metadata, labels=None)`); `register_catalog_products` defaults `vp_factory=hints.make_rich_vp`.
- `continuous.py`: `ContinuousSource.static_meta` field + minimal hand-written meta per source; `register_continuous_products` uses the same factory.

Net behaviour: every radio VP node carries the same ISTP-flavoured metadata its `speasy/...` sibling would (when one exists); on plot, the z (colour) axis label/unit/log-scale appear immediately from the node's metadata; the y2 (frequency) axis appears on first fetch from the SpeasyVariable's axes meta. Identical UX to native Speasy products.

Tests: 74 -> ≥84 passed; 4 headless-skipped (the shape-asserting hooks tests can't run against MagicMock SciQLop). The 5 pre-existing `test_settings.py` failures unchanged.

Spec: `docs/superpowers/specs/2026-05-25-radio-vp-metadata-and-plot-hints-design.md` (d3f343f). Plan: `docs/superpowers/plans/2026-05-25-radio-vp-metadata-and-plot-hints.md`.
```

- [ ] **Step 5: Commit the handover update**

```bash
git add docs/handover-radio-speasy-catalog-2026-05-25.md
git commit -m "docs(sciqlop_radio): handover update for metadata+plot-hints parity work

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Plan self-review

**Spec coverage:** every requirement in `docs/superpowers/specs/2026-05-25-radio-vp-metadata-and-plot-hints-design.md` maps to a task:
- "Goals" #1 (rich metadata on tree) → Tasks 2-3, 8.
- "Goals" #2 (pre/post-fetch hints via the same translators) → Tasks 4-5.
- "Architecture / hints.py" → Tasks 2-6.
- "catalog.py changes" → Tasks 7-8.
- "continuous.py changes" → Task 9.
- "Error handling" → covered inline in Tasks 5 (try/except in hooks), 8 (extraction fallback).
- "Tests" #1-#11 → Tasks 2, 4, 6, 8, 9.
- "Acceptance" baseline check → Task 10.

**Placeholder scan:** no TODOs, no "fill in later" — every step shows the exact code/command to run.

**Type/signature consistency:**
- `vp_factory(path, cb, vptype, *, metadata, labels=None)` — consistent across Tasks 6 (factory), 8 (catalog), 9 (continuous).
- `_resolve_index(speasy_id, speasy_module) -> ParameterIndex | None` — consistent across Tasks 7 (definition) and 8 (call site).
- `extract_speasy_index_meta(index, *, components=None) -> dict` — consistent across Tasks 3 (definition) and 8 (call site).
- `static_meta: dict = field(default_factory=dict)` on `ContinuousSource` — Task 9 only, consistent.
- `RichEasySpectrogram / RichEasyVector / RichEasyScalar / RichEasyMultiComponent` — consistent naming across Tasks 4, 5, 6.

**Headless-test guard:** the four shape-asserting `plot_hints` tests and the four `make_rich_vp` dispatch tests skip under MagicMock SciQLop via the shared `_SCIQLOP_REAL` module constant. Pattern matches the existing `feedback_radio_plugin_not_a_template` precedent.

**Risk:** Task 5 introduces the `_SCIQLOP_REAL` guard — straightforward but the only "infrastructure" we add. The simpler alternative (real-import everything, never run on real SciQLop) would break headless CI; the chosen split is defensible.

---
