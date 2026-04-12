# MSA Live Smoothing Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Live Smoothing Demo" entry to the `sciqlop_msa` plugin that registers four virtual spectrogram products (Gaussian-smoothed L1 corrected count spectrograms) and exposes a dock widget with two sigma sliders + a log-space toggle that re-smooth the spectrograms in real time as the user drags.

**Architecture:** A pure smoothing function (`realtime.smooth_spectrogram`) that operates on `SpeasyVariable` and is fully unit-testable in isolation; a `QDockWidget` (`realtime_dock.RealtimeSmoothingDock`) holding a shared mutable `params` dict; and wiring in `plugin.py` that registers four virtual spectrograms via `SciQLop.user_api.virtual_products.create_virtual_product`, each closing over the same params dict, plus a menu entry that opens a panel pre-loaded with the smoothed products and connects the dock to it. Slider changes mutate the dict and force a panel refresh by re-assigning `panel.time_range`.

**Tech Stack:** Python 3.10+, numpy, scipy (`scipy.ndimage.gaussian_filter`), speasy, PySide6, SciQLop user_api (`virtual_products`, `plot`, `gui`).

**Spec:** [`docs/superpowers/specs/2026-04-12-msa-live-smoothing-design.md`](../specs/2026-04-12-msa-live-smoothing-design.md)

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `sciqlop_msa/sciqlop_msa/realtime.py` | Create | Pure `smooth_spectrogram(var, sigma_t, sigma_e, log_space)` function. No Qt, no SciQLop imports. |
| `sciqlop_msa/sciqlop_msa/realtime_dock.py` | Create | `RealtimeSmoothingDock` QDockWidget holding the shared params dict and the sliders. |
| `sciqlop_msa/sciqlop_msa/plugin.py` | Modify | Register virtual spectrograms, instantiate the dock, add a "Live Smoothing Demo" menu entry. |
| `sciqlop_msa/pyproject.toml` | Modify | Add `scipy` to dependencies. |
| `sciqlop_msa/sciqlop_msa/tests/__init__.py` | Create | Empty file to make tests a package. |
| `sciqlop_msa/sciqlop_msa/tests/test_realtime.py` | Create | Unit tests for `smooth_spectrogram`. |

The unit tests live at the package level (`sciqlop_msa/sciqlop_msa/tests/`) to mirror the existing `cdf_workbench/cdf_workbench/tests/` layout.

---

## Task 1: Add scipy dependency and bootstrap test package

**Files:**
- Modify: `sciqlop_msa/pyproject.toml`
- Create: `sciqlop_msa/sciqlop_msa/tests/__init__.py`

- [ ] **Step 1: Add scipy to pyproject dependencies**

Current `[project]` block in `sciqlop_msa/pyproject.toml`:

```toml
[project]
name = "sciqlop-msa"
version = "0.2.0"
description = "SciQLop plugin for BepiColombo MSA instrument data"
requires-python = ">=3.10"
dependencies = ["speasy"]
```

Replace the `dependencies` line with:

```toml
dependencies = ["speasy", "scipy"]
```

- [ ] **Step 2: Create the empty test package init**

Create `sciqlop_msa/sciqlop_msa/tests/__init__.py` as an empty file (zero bytes).

- [ ] **Step 3: Verify the plugin still imports and the test package is importable**

Run:
```bash
python -c "import sciqlop_msa; import sciqlop_msa.tests; print('ok')"
```
Expected: `ok`

If `sciqlop_msa` is not on the Python path (it's a workspace package, not pip-installed in this repo), the import will fail with `ModuleNotFoundError`. In that case skip this verification and rely on pytest's rootdir discovery in later tasks.

- [ ] **Step 4: Commit**

```bash
git add sciqlop_msa/pyproject.toml sciqlop_msa/sciqlop_msa/tests/__init__.py
git commit -m "chore(sciqlop_msa): add scipy dep and bootstrap tests package"
```

---

## Task 2: `smooth_spectrogram` — write the failing identity test

**Files:**
- Create: `sciqlop_msa/sciqlop_msa/tests/test_realtime.py`

- [ ] **Step 1: Write the identity test (sigma=0 returns input values unchanged)**

Create `sciqlop_msa/sciqlop_msa/tests/test_realtime.py` with:

```python
"""Unit tests for sciqlop_msa.realtime.smooth_spectrogram."""
import numpy as np
import pytest

from speasy.products import SpeasyVariable
from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis

from sciqlop_msa.realtime import smooth_spectrogram


def _make_spectrogram(values: np.ndarray) -> SpeasyVariable:
    """Build a minimal SpeasyVariable spectrogram with synthetic time + energy axes."""
    n_time, n_energy = values.shape
    time = np.arange(
        np.datetime64("2025-01-08T01:38:50", "ns"),
        np.datetime64("2025-01-08T01:38:50", "ns") + n_time * np.timedelta64(4, "s"),
        np.timedelta64(4, "s"),
    )[:n_time]
    energy = np.linspace(10.0, 30000.0, n_energy)
    return SpeasyVariable(
        axes=[
            VariableTimeAxis(values=time),
            VariableAxis(values=energy, name="energy", is_time_dependent=False),
        ],
        values=DataContainer(values=values, name="counts"),
    )


def test_zero_sigma_is_identity():
    raw = np.random.default_rng(0).poisson(5.0, size=(50, 32)).astype(np.float64)
    var = _make_spectrogram(raw)

    out = smooth_spectrogram(var, sigma_t=0.0, sigma_e=0.0, log_space=False)

    assert out.values.shape == var.values.shape
    np.testing.assert_array_equal(out.values, var.values)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd sciqlop_msa && python -m pytest sciqlop_msa/tests/test_realtime.py::test_zero_sigma_is_identity -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'sciqlop_msa.realtime'`.

- [ ] **Step 3: Commit the failing test**

```bash
git add sciqlop_msa/sciqlop_msa/tests/test_realtime.py
git commit -m "test(sciqlop_msa): failing identity test for smooth_spectrogram"
```

---

## Task 3: `smooth_spectrogram` — minimal implementation (identity case)

**Files:**
- Create: `sciqlop_msa/sciqlop_msa/realtime.py`

- [ ] **Step 1: Write the minimal module to make the identity test pass**

Create `sciqlop_msa/sciqlop_msa/realtime.py` with:

```python
"""Real-time processing primitives for the MSA Live Smoothing Demo.

This module is intentionally pure (no Qt, no SciQLop imports) so it can be
unit-tested in isolation against synthetic SpeasyVariables.
"""
from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter
from speasy.products import SpeasyVariable


def smooth_spectrogram(
    var: SpeasyVariable,
    sigma_t: float,
    sigma_e: float,
    log_space: bool,
) -> SpeasyVariable:
    """Return a copy of `var` with values 2D-Gaussian-smoothed.

    Smoothing is applied along (time, energy) axes. With ``log_space=True``,
    smoothing is performed on ``log10(values + 1)`` and then exponentiated
    back, which gives visually nicer results on Poisson-distributed counts.

    A zero sigma along both axes returns an unmodified copy.
    """
    out = var.copy()
    if sigma_t == 0.0 and sigma_e == 0.0:
        return out
    raise NotImplementedError("non-zero sigma not implemented yet")
```

- [ ] **Step 2: Run the test to verify it passes**

Run:
```bash
cd sciqlop_msa && python -m pytest sciqlop_msa/tests/test_realtime.py::test_zero_sigma_is_identity -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add sciqlop_msa/sciqlop_msa/realtime.py
git commit -m "feat(sciqlop_msa): smooth_spectrogram identity case"
```

---

## Task 4: `smooth_spectrogram` — variance-reduction test for non-zero sigma

**Files:**
- Modify: `sciqlop_msa/sciqlop_msa/tests/test_realtime.py`

- [ ] **Step 1: Add the variance-reduction test**

Append to `sciqlop_msa/sciqlop_msa/tests/test_realtime.py`:

```python
def test_time_smoothing_reduces_variance_along_time():
    rng = np.random.default_rng(1)
    raw = rng.poisson(5.0, size=(200, 32)).astype(np.float64)
    var = _make_spectrogram(raw)

    out = smooth_spectrogram(var, sigma_t=3.0, sigma_e=0.0, log_space=False)

    raw_var = np.var(raw, axis=0).mean()
    smoothed_var = np.var(out.values, axis=0).mean()
    assert smoothed_var < raw_var * 0.6
    assert out.values.shape == raw.shape
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd sciqlop_msa && python -m pytest sciqlop_msa/tests/test_realtime.py::test_time_smoothing_reduces_variance_along_time -v
```
Expected: FAIL with `NotImplementedError: non-zero sigma not implemented yet`.

- [ ] **Step 3: Commit the failing test**

```bash
git add sciqlop_msa/sciqlop_msa/tests/test_realtime.py
git commit -m "test(sciqlop_msa): variance-reduction test for smooth_spectrogram"
```

---

## Task 5: `smooth_spectrogram` — implement non-zero sigma (linear space)

**Files:**
- Modify: `sciqlop_msa/sciqlop_msa/realtime.py`

- [ ] **Step 1: Replace the NotImplementedError with the gaussian_filter call**

Replace the body of `smooth_spectrogram` in `sciqlop_msa/sciqlop_msa/realtime.py` with:

```python
def smooth_spectrogram(
    var: SpeasyVariable,
    sigma_t: float,
    sigma_e: float,
    log_space: bool,
) -> SpeasyVariable:
    """Return a copy of `var` with values 2D-Gaussian-smoothed.

    Smoothing is applied along (time, energy) axes. With ``log_space=True``,
    smoothing is performed on ``log10(values + 1)`` and then exponentiated
    back, which gives visually nicer results on Poisson-distributed counts.

    A zero sigma along both axes returns an unmodified copy.
    NaNs in the input are preserved in the output.
    """
    out = var.copy()
    if sigma_t == 0.0 and sigma_e == 0.0:
        return out

    raw = np.asarray(var.values, dtype=np.float64)
    nan_mask = np.isnan(raw)
    work = np.where(nan_mask, 0.0, raw)
    if log_space:
        work = np.log10(work + 1.0)

    smoothed = gaussian_filter(work, sigma=(sigma_t, sigma_e), mode="nearest")

    if log_space:
        smoothed = np.power(10.0, smoothed) - 1.0

    smoothed[nan_mask] = np.nan
    out.values[...] = smoothed
    return out
```

- [ ] **Step 2: Run both tests to verify they pass**

Run:
```bash
cd sciqlop_msa && python -m pytest sciqlop_msa/tests/test_realtime.py -v
```
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add sciqlop_msa/sciqlop_msa/realtime.py
git commit -m "feat(sciqlop_msa): implement smooth_spectrogram non-zero sigma"
```

---

## Task 6: `smooth_spectrogram` — log-space smoothing test

**Files:**
- Modify: `sciqlop_msa/sciqlop_msa/tests/test_realtime.py`

- [ ] **Step 1: Add the log-space test**

Append to `sciqlop_msa/sciqlop_msa/tests/test_realtime.py`:

```python
def test_log_space_smoothing_matches_hand_computed():
    raw = np.array(
        [
            [1.0, 10.0, 100.0],
            [2.0, 20.0, 200.0],
            [3.0, 30.0, 300.0],
            [4.0, 40.0, 400.0],
        ],
        dtype=np.float64,
    )
    var = _make_spectrogram(raw)

    out = smooth_spectrogram(var, sigma_t=1.0, sigma_e=0.0, log_space=True)

    from scipy.ndimage import gaussian_filter
    expected = np.power(10.0, gaussian_filter(np.log10(raw + 1.0), sigma=(1.0, 0.0), mode="nearest")) - 1.0

    assert out.values.shape == raw.shape
    np.testing.assert_allclose(out.values, expected, rtol=1e-12)
    assert (out.values >= 0.0).all()
```

- [ ] **Step 2: Run the test to verify it passes**

The implementation already supports log-space, so this test should pass on first run.

Run:
```bash
cd sciqlop_msa && python -m pytest sciqlop_msa/tests/test_realtime.py::test_log_space_smoothing_matches_hand_computed -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add sciqlop_msa/sciqlop_msa/tests/test_realtime.py
git commit -m "test(sciqlop_msa): log-space smoothing matches hand-computed"
```

---

## Task 7: `smooth_spectrogram` — NaN preservation test

**Files:**
- Modify: `sciqlop_msa/sciqlop_msa/tests/test_realtime.py`

- [ ] **Step 1: Add the NaN preservation test**

Append to `sciqlop_msa/sciqlop_msa/tests/test_realtime.py`:

```python
def test_nan_preserved_outside_nan_region():
    raw = np.ones((20, 16), dtype=np.float64) * 5.0
    raw[5, 8] = np.nan
    var = _make_spectrogram(raw)

    out = smooth_spectrogram(var, sigma_t=1.0, sigma_e=1.0, log_space=False)

    assert np.isnan(out.values[5, 8])
    assert not np.isnan(out.values[0, 0])
    assert not np.isnan(out.values[-1, -1])
```

- [ ] **Step 2: Run the test to verify it passes**

Run:
```bash
cd sciqlop_msa && python -m pytest sciqlop_msa/tests/test_realtime.py::test_nan_preserved_outside_nan_region -v
```
Expected: PASS.

- [ ] **Step 3: Run the full test file to confirm everything is green**

Run:
```bash
cd sciqlop_msa && python -m pytest sciqlop_msa/tests/test_realtime.py -v
```
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add sciqlop_msa/sciqlop_msa/tests/test_realtime.py
git commit -m "test(sciqlop_msa): NaN preservation in smooth_spectrogram"
```

---

## Task 8: `RealtimeSmoothingDock` widget

**Files:**
- Create: `sciqlop_msa/sciqlop_msa/realtime_dock.py`

This dock is not unit-tested — it requires a running Qt event loop and is validated by the smoke test in Task 11. We commit it as a single self-contained file.

- [ ] **Step 1: Create the dock module**

Create `sciqlop_msa/sciqlop_msa/realtime_dock.py` with:

```python
"""Dock widget for the MSA Live Smoothing Demo.

Owns the shared parameters dict that the virtual product callbacks read from
via closure. Slider changes mutate the dict and call the registered refresh
callback to force the active plot panel to re-fetch its data.
"""
from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFormLayout,
    QLabel,
    QSlider,
    QWidget,
)


_DEFAULT_PARAMS = {"sigma_t": 0.0, "sigma_e": 0.0, "log_space": False}


class RealtimeSmoothingDock(QDockWidget):
    """A dock with two sigma sliders and a log-space toggle.

    The :attr:`params` dict is the single source of truth shared with the
    virtual product callbacks. Mutating it from outside is supported but
    won't trigger a refresh; use the sliders for that.
    """

    def __init__(self, parent=None):
        super().__init__("MSA Live Smoothing", parent)
        self.setObjectName("MSALiveSmoothingDock")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)

        self.params: dict = dict(_DEFAULT_PARAMS)
        self._refresh_callback: Optional[Callable[[], None]] = None

        body = QWidget(self)
        layout = QFormLayout(body)

        self._sigma_t_slider = QSlider(Qt.Horizontal, body)
        self._sigma_t_slider.setRange(0, 10)
        self._sigma_t_slider.setValue(0)
        self._sigma_t_label = QLabel("0", body)
        self._sigma_t_slider.valueChanged.connect(self._on_sigma_t_changed)
        layout.addRow("σ time", self._row(self._sigma_t_slider, self._sigma_t_label))

        self._sigma_e_slider = QSlider(Qt.Horizontal, body)
        self._sigma_e_slider.setRange(0, 5)
        self._sigma_e_slider.setValue(0)
        self._sigma_e_label = QLabel("0", body)
        self._sigma_e_slider.valueChanged.connect(self._on_sigma_e_changed)
        layout.addRow("σ energy", self._row(self._sigma_e_slider, self._sigma_e_label))

        self._log_space_checkbox = QCheckBox("Smooth in log10 space", body)
        self._log_space_checkbox.toggled.connect(self._on_log_space_toggled)
        layout.addRow("", self._log_space_checkbox)

        self.setWidget(body)

    @staticmethod
    def _row(slider: QSlider, label: QLabel) -> QWidget:
        from PySide6.QtWidgets import QHBoxLayout
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(slider, stretch=1)
        h.addWidget(label)
        return row

    def set_refresh_callback(self, callback: Callable[[], None]) -> None:
        self._refresh_callback = callback

    def _trigger_refresh(self) -> None:
        if self._refresh_callback is not None:
            try:
                self._refresh_callback()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Refresh callback failed")

    def _on_sigma_t_changed(self, value: int) -> None:
        self.params["sigma_t"] = float(value)
        self._sigma_t_label.setText(str(value))
        self._trigger_refresh()

    def _on_sigma_e_changed(self, value: int) -> None:
        self.params["sigma_e"] = float(value)
        self._sigma_e_label.setText(str(value))
        self._trigger_refresh()

    def _on_log_space_toggled(self, checked: bool) -> None:
        self.params["log_space"] = bool(checked)
        self._trigger_refresh()
```

- [ ] **Step 2: Sanity-import the new module under the Qt-stub conftest**

Run:
```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop && python -m pytest --collect-only sciqlop_msa/sciqlop_msa/tests/ -q
```
Expected: collection succeeds (4 tests). The dock module is not imported by the tests but this confirms nothing in the package broke.

- [ ] **Step 3: Commit**

```bash
git add sciqlop_msa/sciqlop_msa/realtime_dock.py
git commit -m "feat(sciqlop_msa): RealtimeSmoothingDock widget"
```

---

## Task 9: Wire virtual products and dock into `plugin.py`

**Files:**
- Modify: `sciqlop_msa/sciqlop_msa/plugin.py`

- [ ] **Step 1: Replace `plugin.py` with the wired version**

Replace the entire contents of `sciqlop_msa/sciqlop_msa/plugin.py` with:

```python
from pathlib import Path
import logging
import shutil

from PySide6.QtCore import Qt, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolButton

log = logging.getLogger(__name__)


_L1_BASE = "speasy/archive/BepiColombo/MSA/L1_Low_ECounts_Moments_TOF/bc_mmo_mppe_msa_l1_l_ecounts_moments_tof"

_SMOOTHED_PRODUCTS = [
    ("h_plus_counts_corrected", "MSA/Smoothed/h_plus_counts"),
    ("alphas_counts_corrected", "MSA/Smoothed/alphas_counts"),
    ("heavies_counts_corrected", "MSA/Smoothed/heavies_counts"),
    ("total_counts_corrected", "MSA/Smoothed/total_counts"),
]


def speasy_archive_dir() -> Path:
    from speasy.data_providers.generic_archive import user_inventory_dir
    return Path(user_inventory_dir())


def install_inventory():
    source = Path(__file__).parent / "inventory.yaml"
    dest = speasy_archive_dir() / "msa_bepi.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def rebuild_speasy_inventory():
    try:
        from speasy.core.dataprovider import PROVIDERS
        if "archive" in PROVIDERS:
            PROVIDERS["archive"].update_inventory()
    except Exception:
        pass


def _make_smoothed_callback(source_path: str, params: dict):
    """Build a virtual-product callback that fetches `source_path` and smooths it
    using the live `params` dict (mutated by the dock sliders)."""
    import speasy
    from .realtime import smooth_spectrogram

    def callback(start: float, stop: float):
        raw = speasy.get_data(source_path, start, stop)
        if raw is None:
            return None
        return smooth_spectrogram(
            raw,
            sigma_t=params["sigma_t"],
            sigma_e=params["sigma_e"],
            log_space=params["log_space"],
        )

    callback.__name__ = f"smoothed_{source_path.rsplit('/', 1)[-1]}"
    callback.__annotations__ = {"start": float, "stop": float}
    return callback


class MSAPlugin(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window
        self._smoothing_dock = None
        self._setup_quicklook_menu()
        self._setup_live_smoothing()

    def _setup_quicklook_menu(self):
        from .quicklooks import TEMPLATES, create_quicklook

        self._menu = QMenu("MSA Quick-Looks", self._main_window)
        for template_name in TEMPLATES:
            action = QAction(template_name, self._menu)
            def _on_quicklook(checked, name=template_name):
                try:
                    create_quicklook(name)
                except Exception:
                    log.exception("Failed to create quick-look '%s'", name)
            action.triggered.connect(_on_quicklook)
            self._menu.addAction(action)

        self._menu.addSeparator()
        live_action = QAction("Live Smoothing Demo", self._menu)
        live_action.triggered.connect(self._on_live_smoothing_demo)
        self._menu.addAction(live_action)

        self._quicklook_button = QToolButton(self._main_window)
        self._quicklook_button.setText("MSA Quick-Looks")
        self._quicklook_button.setMenu(self._menu)
        self._quicklook_button.setPopupMode(QToolButton.InstantPopup)
        self._main_window.toolBar.addWidget(self._quicklook_button)

    def _setup_live_smoothing(self):
        """Create the dock and register the four virtual smoothed spectrograms."""
        from .realtime_dock import RealtimeSmoothingDock
        from SciQLop.user_api.virtual_products import (
            create_virtual_product,
            VirtualProductType,
        )

        self._smoothing_dock = RealtimeSmoothingDock(self._main_window)
        self._main_window.addDockWidget(Qt.RightDockWidgetArea, self._smoothing_dock)
        self._smoothing_dock.hide()

        for source_name, virtual_path in _SMOOTHED_PRODUCTS:
            source_path = f"{_L1_BASE}/{source_name}"
            callback = _make_smoothed_callback(source_path, self._smoothing_dock.params)
            create_virtual_product(
                virtual_path,
                callback,
                VirtualProductType.Spectrogram,
            )

    def _on_live_smoothing_demo(self):
        """Open a panel pre-loaded with the four smoothed spectrograms."""
        from datetime import datetime, timezone
        from SciQLop.user_api.plot import create_plot_panel
        from SciQLop.core import TimeRange

        try:
            panel = create_plot_panel()
            start = datetime(2025, 1, 8, 1, 38, 50, tzinfo=timezone.utc).timestamp()
            stop = datetime(2025, 1, 8, 17, 27, 23, tzinfo=timezone.utc).timestamp()
            panel.time_range = TimeRange(start, stop)

            for _, virtual_path in _SMOOTHED_PRODUCTS:
                panel.plot_product(virtual_path)

            def _refresh():
                tr = panel.time_range
                panel.time_range = TimeRange(tr.start(), tr.stop())

            self._smoothing_dock.set_refresh_callback(_refresh)
            self._smoothing_dock.show()
            self._smoothing_dock.raise_()
        except Exception:
            log.exception("Failed to open Live Smoothing Demo")

    async def close(self):
        pass


def load(main_window):
    install_inventory()
    rebuild_speasy_inventory()
    return MSAPlugin(main_window)
```

- [ ] **Step 2: Re-run the unit tests to confirm nothing in the package broke**

Run:
```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop && python -m pytest sciqlop_msa/sciqlop_msa/tests/ -v
```
Expected: 4 passed.

- [ ] **Step 3: Commit**

```bash
git add sciqlop_msa/sciqlop_msa/plugin.py
git commit -m "feat(sciqlop_msa): wire Live Smoothing Demo into plugin"
```

---

## Task 10: Bump plugin version

**Files:**
- Modify: `sciqlop_msa/pyproject.toml`

- [ ] **Step 1: Bump version**

In `sciqlop_msa/pyproject.toml`, change:

```toml
version = "0.2.0"
```

to:

```toml
version = "0.3.0"
```

- [ ] **Step 2: Commit**

```bash
git add sciqlop_msa/pyproject.toml
git commit -m "chore(sciqlop_msa): bump version to 0.3.0"
```

---

## Task 11: Manual smoke test (the night before the demo)

This task is not automatable — it requires a real SciQLop installation, network access for the initial Speasy fetch, and a human eye on the spectrograms. Run it before the meeting.

- [ ] **Step 1: Install the plugin into the SciQLop environment**

Run:
```bash
pip install -e sciqlop_msa
```

- [ ] **Step 2: Pre-warm the Speasy cache for the demo interval**

Launch SciQLop, open the existing "L1 Count Spectrograms" quick-look from the MSA toolbar menu. Wait for all four spectrograms to render fully. This populates the local Speasy cache for `2025-01-08 01:38:50 — 17:27:23 UTC` so the smoothing demo never has to hit the network during the talk.

- [ ] **Step 3: Open the Live Smoothing Demo**

From the MSA toolbar menu, click "Live Smoothing Demo" (below the separator).

Expected:
- A new plot panel opens with four spectrograms (h⁺, α, heavies, total).
- The "MSA Live Smoothing" dock appears on the right side of the main window.
- All four spectrograms initially look identical to the raw quick-look (sliders at 0).

- [ ] **Step 4: Drag the σ time slider end-to-end**

Drag the σ time slider from 0 to 10 and back.

Expected:
- All four spectrograms re-render within ~100 ms per slider step.
- Visible smoothing along the time axis as σ increases.
- No exceptions in the SciQLop log.

- [ ] **Step 5: Drag the σ energy slider end-to-end**

Drag the σ energy slider from 0 to 5 and back.

Expected: smoothing along the energy axis is visible; no exceptions.

- [ ] **Step 6: Toggle log-space smoothing**

Set σ time to 3, σ energy to 1, then toggle "Smooth in log10 space" on and off a few times.

Expected: visible difference between linear and log smoothing (log space is gentler on bright pixels and pulls up dim features); no exceptions.

- [ ] **Step 7: Pan the time axis**

Pan the time axis by ~30 minutes in either direction with the smoothing sliders set to non-zero values.

Expected: smoothed spectrograms re-fetch and re-smooth on the new window; no flicker beyond normal Speasy refresh.

- [ ] **Step 8: If the refresh-on-time-range-reassign trick fails**

If Step 4 shows that re-assigning `panel.time_range` to its current value does not trigger a refetch, edit `_refresh` in `_on_live_smoothing_demo` to nudge by 1 ns:

```python
def _refresh():
    tr = panel.time_range
    panel.time_range = TimeRange(tr.start() + 1e-9, tr.stop())
```

Re-run Step 4 and confirm the slider now drives a refresh.

If the nudge is needed, commit:
```bash
git add sciqlop_msa/sciqlop_msa/plugin.py
git commit -m "fix(sciqlop_msa): nudge time_range by 1ns to force refresh"
```

- [ ] **Step 9: Check off this task only after all the above pass**

---

## Self-Review Notes

**Spec coverage check:**

| Spec section | Implemented in |
|---|---|
| Goal: register four virtual smoothed spectrograms | Task 9 |
| Goal: dock with σ_t, σ_e, log-space toggle | Task 8 |
| Goal: real-time refresh on slider change | Task 8 (`_trigger_refresh`) + Task 9 (`_refresh`) |
| Architecture: `realtime.py` pure function | Tasks 2–7 |
| Architecture: `realtime_dock.py` QDockWidget | Task 8 |
| Architecture: closure-over-params pattern | Task 9 (`_make_smoothed_callback`) |
| Architecture: `cacheable=False` (default) | Task 9 (omitted, defaults to False) |
| Refresh via `panel.time_range = panel.time_range` | Task 9 with Task 11 fallback |
| Testing: identity, variance, log-space, NaN | Tasks 2, 4, 6, 7 |
| Pre-demo smoke test | Task 11 |
| New scipy dep declared | Task 1 |
| Non-goal: no moments | Confirmed — not referenced anywhere |
| Non-goal: no persistence of slider state | Confirmed — `_DEFAULT_PARAMS` reset per dock instance |
| Additive only — no edits to `quicklooks.py`, `inventory.yaml`, existing menu items | Task 9 only adds a separator + new action below the existing entries |

**Type/name consistency check:**

- `smooth_spectrogram(var, sigma_t, sigma_e, log_space)` — same signature in `realtime.py` (Tasks 3/5) and in `_make_smoothed_callback` (Task 9). ✓
- `RealtimeSmoothingDock.params` keys: `sigma_t`, `sigma_e`, `log_space` — same in `_DEFAULT_PARAMS` (Task 8) and in `_make_smoothed_callback` (Task 9). ✓
- `set_refresh_callback` — defined in Task 8, called in Task 9. ✓
- Virtual product paths: `MSA/Smoothed/{name}_counts` — same in `_SMOOTHED_PRODUCTS` (Task 9) and registered through `create_virtual_product` and re-used in `panel.plot_product`. ✓

**Placeholder scan:** none found.
