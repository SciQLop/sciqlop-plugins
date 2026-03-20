# CDF Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a multi-function CDF file explorer plugin for SciQLop that lets power users inspect structure, quality, and data of CDF files.

**Architecture:** Monolithic QWidget panel registered as a dock widget in SciQLop's central area. One tab per open file, each tab containing a splitter with a variable tree (left) and inspector+preview (right). Pure-function quality analysis module. Data pushed directly to SciQLopPlots as numpy arrays.

**Tech Stack:** PySide6, pycdfpp, matplotlib (FigureCanvas), httpx, numpy

**Spec:** `cdf_workbench/docs/2026-03-20-cdf-workbench-design.md`

---

## File Structure

```
cdf_workbench/
├── __init__.py          # exports load()
├── plugin.json          # plugin metadata and dependencies
├── workbench.py         # CdfWorkbenchPanel — QWidget with QTabWidget + file open logic
├── file_view.py         # CdfFileView — per-tab widget: splitter, wires tree/inspector/preview
├── tree_model.py        # CdfTreeModel (QAbstractItemModel) + CdfItemDelegate (sparklines, health)
├── inspector.py         # CdfInspectorWidget — attributes grid, dep links, quality bar, plot buttons
├── preview.py           # CdfPreviewWidget — matplotlib FigureCanvas for inline plot
├── quality.py           # analyze_quality(var) → QualityReport (pure function, no Qt)
├── loader.py            # load_cdf(path_or_url) → pycdfpp.CDF, CdfLoadError
└── tests/
    ├── __init__.py
    ├── conftest.py      # shared fixtures: sample CDF bytes, mock CDF objects
    ├── test_quality.py
    ├── test_loader.py
    ├── test_tree_model.py
    └── test_inspector.py
```

## Verified SciQLop APIs

These were verified against the SciQLop source at `/var/home/jeandet/Documents/prog/SciQLop/`:

| API | Signature | Location |
|-----|-----------|----------|
| `main_window.toolsMenu` | `QMenu` | `mainwindow.py:95` |
| `main_window.toolsMenu.addAction(label, callback)` | adds menu item | `mainwindow.py:120` |
| `main_window.new_plot_panel(name=...)` | returns `TimeSyncPanel` | `mainwindow.py:323` |
| `main_window.push_variables_to_console(dict)` | pushes to Jupyter | `mainwindow.py:390` |
| `main_window.add_side_pan(widget, location, icon)` | adds dock panel | `mainwindow.py:258` |
| `PlotPanel.plot_data(x, y, z=None)` | returns `(plot, graph)` | `user_api/plot/_panel.py:147` |

For static data plotting:
```python
from SciQLop.user_api.plot import create_plot_panel
panel = create_plot_panel()
plot, graph = panel.plot_data(x_array, y_array)
```

---

## Task 1: Project scaffold + plugin.json + load()

**Files:**
- Create: `cdf_workbench/__init__.py`
- Create: `cdf_workbench/plugin.json`
- Create: `cdf_workbench/workbench.py`

- [ ] **Step 1: Create plugin.json**

```json
{
  "name": "CDF Workbench",
  "version": "0.1.0",
  "description": "Multi-function CDF file explorer for SciQLop",
  "authors": [
    {
      "name": "Alexis Jeandet",
      "email": "alexis.jeandet@member.fsf.org",
      "organization": "LPP"
    }
  ],
  "license": "MIT",
  "python_dependencies": ["pycdfpp", "httpx", "matplotlib"],
  "dependencies": [],
  "disabled": false
}
```

- [ ] **Step 2: Create minimal workbench.py**

```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QLabel


class CdfWorkbenchPanel(QWidget):
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self.setWindowTitle("CDF Workbench")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        layout.addWidget(self._tabs)

        # Placeholder for empty state
        self._empty_label = QLabel("Drop a CDF file here or use File → Open")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._tabs.addTab(self._empty_label, "+")

    def _close_tab(self, index: int):
        widget = self._tabs.widget(index)
        if widget is not self._empty_label:
            self._tabs.removeTab(index)
            widget.deleteLater()
```

- [ ] **Step 3: Create __init__.py with load()**

The panel is registered as a dock widget in SciQLop's central area via `addWidgetIntoDock`, not just shown as a floating window. The menu action toggles its visibility.

```python
import PySide6QtAds as QtAds
from .workbench import CdfWorkbenchPanel


def load(main_window):
    panel = CdfWorkbenchPanel(main_window=main_window)
    # Register as a dock widget in SciQLop's central area
    main_window.addWidgetIntoDock(
        QtAds.DockWidgetArea.TopDockWidgetArea, panel
    )
    main_window.toolsMenu.addAction("CDF Workbench", panel.show)
    return panel
```

Note: The exact dock area enum and registration method should be verified against `SciQLopMainWindow` at implementation time. SciQLop uses `PySide6QtAds` for its dock system.

- [ ] **Step 4: Commit**

```bash
git add cdf_workbench/__init__.py cdf_workbench/plugin.json cdf_workbench/workbench.py
git commit -m "feat: scaffold CDF workbench plugin with minimal panel"
```

---

## Task 2: CDF loader module with error handling

**Files:**
- Create: `cdf_workbench/loader.py`
- Create: `cdf_workbench/tests/__init__.py`
- Create: `cdf_workbench/tests/conftest.py`
- Create: `cdf_workbench/tests/test_loader.py`

- [ ] **Step 1: Create conftest.py with CDF fixtures**

```python
import pytest
import pycdfpp
import numpy as np


@pytest.fixture
def sample_cdf_bytes():
    """Create a minimal valid CDF file in memory."""
    cdf = pycdfpp.CDF()
    epochs = np.arange(
        np.datetime64("2020-01-01"),
        np.datetime64("2020-01-01T00:00:10"),
        np.timedelta64(1, "s"),
    ).astype("datetime64[ns]")
    cdf.add_variable("Epoch", values=epochs, is_nrv=False)
    cdf.add_variable(
        "Bt",
        values=np.random.rand(10).astype(np.float32),
        is_nrv=False,
    )
    # pycdfpp uses add_attribute, not set_attribute
    cdf["Bt"].add_attribute("VAR_TYPE", "data")
    cdf["Bt"].add_attribute("DEPEND_0", "Epoch")
    cdf["Bt"].add_attribute("UNITS", "nT")
    cdf["Bt"].add_attribute("FILLVAL", np.float32(-1e31))
    cdf["Bt"].add_attribute("VALIDMIN", np.float32(0.0))
    cdf["Bt"].add_attribute("VALIDMAX", np.float32(100.0))
    cdf["Epoch"].add_attribute("VAR_TYPE", "support_data")
    # pycdfpp.save() returns _cdf_bytes; cast to bytes for compatibility
    return bytes(pycdfpp.save(cdf))
```

Note: The exact pycdfpp API for creating CDF files in memory should be verified at implementation time. If `pycdfpp.CDF()` constructor or `add_variable`/`add_attribute` signatures differ, adjust accordingly. The key contract: produce valid CDF bytes that `pycdfpp.load()` can round-trip.

- [ ] **Step 2: Write failing tests for loader**

```python
import pytest
from cdf_workbench.loader import load_cdf, CdfLoadError


def test_load_local_file(tmp_path, sample_cdf_bytes):
    path = tmp_path / "test.cdf"
    path.write_bytes(sample_cdf_bytes)
    cdf = load_cdf(str(path))
    assert cdf is not None
    assert "Bt" in cdf


def test_load_corrupted_file_raises(tmp_path):
    path = tmp_path / "bad.cdf"
    path.write_bytes(b"not a cdf file")
    with pytest.raises(CdfLoadError, match="Failed to parse"):
        load_cdf(str(path))


def test_load_missing_file_raises():
    with pytest.raises(CdfLoadError):
        load_cdf("/nonexistent/path.cdf")


def test_load_from_bytes(sample_cdf_bytes):
    cdf = load_cdf(sample_cdf_bytes)
    assert "Bt" in cdf
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd cdf_workbench && python -m pytest tests/test_loader.py -v`
Expected: FAIL — `loader` module does not exist yet

- [ ] **Step 4: Implement loader.py**

```python
from pathlib import Path
import pycdfpp


class CdfLoadError(Exception):
    pass


def load_cdf(source: str | bytes) -> pycdfpp.CDF:
    """Load a CDF from a local path, URL, or raw bytes.

    Raises CdfLoadError on any failure.
    """
    if isinstance(source, bytes):
        return _load_bytes(source)

    if source.startswith(("http://", "https://")):
        return _load_url(source)

    return _load_file(source)


def _load_bytes(data: bytes) -> pycdfpp.CDF:
    cdf = pycdfpp.load(data)
    if cdf is None:
        raise CdfLoadError("Failed to parse CDF data")
    return cdf


def _load_file(path: str) -> pycdfpp.CDF:
    if not Path(path).exists():
        raise CdfLoadError(f"File not found: {path}")
    try:
        cdf = pycdfpp.load(path)
    except Exception as e:
        raise CdfLoadError(f"Failed to load {path}: {e}") from e
    if cdf is None:
        raise CdfLoadError(f"Failed to parse CDF file: {path}")
    return cdf


def _load_url(url: str) -> pycdfpp.CDF:
    import httpx

    try:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise CdfLoadError(f"Failed to download {url}: {e}") from e
    return _load_bytes(response.content)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd cdf_workbench && python -m pytest tests/test_loader.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 6: Commit**

```bash
git add cdf_workbench/loader.py cdf_workbench/tests/
git commit -m "feat: add CDF loader with local file, URL, and bytes support"
```

---

## Task 3: Quality analysis module (pure functions)

**Files:**
- Create: `cdf_workbench/quality.py`
- Create: `cdf_workbench/tests/test_quality.py`

- [ ] **Step 1: Write failing tests for quality analysis**

```python
import numpy as np
import pytest
from cdf_workbench.quality import analyze_quality, QualityReport


def test_quality_report_perfect_data():
    """No fill values, no out-of-range, no gaps."""
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    epochs = np.arange(
        np.datetime64("2020-01-01"),
        np.datetime64("2020-01-01T00:00:05"),
        np.timedelta64(1, "s"),
    )
    report = analyze_quality(
        values=values,
        epochs=epochs,
        fill_value=-1e31,
        valid_min=0.0,
        valid_max=100.0,
    )
    assert report.fill_percentage == 0.0
    assert report.out_of_range_percentage == 0.0
    assert report.epoch_gaps == 0
    assert report.valid_percentage == 100.0


def test_quality_report_with_fill_values():
    values = np.array([1.0, -1e31, 3.0, -1e31, 5.0])
    report = analyze_quality(
        values=values, fill_value=-1e31,
    )
    assert report.fill_percentage == pytest.approx(40.0)


def test_quality_report_with_out_of_range():
    values = np.array([1.0, 2.0, 150.0, 4.0, -5.0])
    report = analyze_quality(
        values=values,
        fill_value=-1e31,
        valid_min=0.0,
        valid_max=100.0,
    )
    assert report.out_of_range_percentage == pytest.approx(40.0)


def test_quality_report_epoch_gaps():
    # Regular 1-second cadence with a 10-second gap in the middle
    epochs = np.array([0, 1, 2, 3, 13, 14, 15], dtype="datetime64[s]")
    report = analyze_quality(
        values=np.ones(7),
        epochs=epochs,
    )
    assert report.epoch_gaps == 1


def test_quality_report_no_metadata():
    """When no fill/valid range provided, only basic stats."""
    values = np.array([1.0, 2.0, 3.0])
    report = analyze_quality(values=values)
    assert report.fill_percentage == 0.0
    assert report.out_of_range_percentage == 0.0


def test_quality_report_multidimensional():
    """2D array (e.g. vector field) — quality computed over all elements."""
    values = np.array([[1.0, 2.0], [-1e31, 3.0], [4.0, -1e31]])
    report = analyze_quality(values=values, fill_value=-1e31)
    assert report.fill_percentage == pytest.approx(100.0 * 2 / 6)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cdf_workbench && python -m pytest tests/test_quality.py -v`
Expected: FAIL — `quality` module does not exist

- [ ] **Step 3: Implement quality.py**

```python
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class QualityReport:
    fill_percentage: float
    out_of_range_percentage: float
    epoch_gaps: int
    total_points: int

    @property
    def valid_percentage(self) -> float:
        bad = self.fill_percentage + self.out_of_range_percentage
        return max(0.0, 100.0 - bad)


def analyze_quality(
    values: np.ndarray,
    epochs: np.ndarray | None = None,
    fill_value: float | None = None,
    valid_min: float | None = None,
    valid_max: float | None = None,
) -> QualityReport:
    total = values.size
    if total == 0:
        return QualityReport(0.0, 0.0, 0, 0)

    flat = values.ravel()

    fill_count = 0
    if fill_value is not None:
        fill_count = int(np.sum(flat == fill_value))

    oor_count = 0
    if valid_min is not None or valid_max is not None:
        non_fill = flat if fill_value is None else flat[flat != fill_value]
        if valid_min is not None:
            oor_count += int(np.sum(non_fill < valid_min))
        if valid_max is not None:
            oor_count += int(np.sum(non_fill > valid_max))

    gap_count = _count_epoch_gaps(epochs) if epochs is not None else 0

    return QualityReport(
        fill_percentage=100.0 * fill_count / total,
        out_of_range_percentage=100.0 * oor_count / total,
        epoch_gaps=gap_count,
        total_points=total,
    )


def _count_epoch_gaps(epochs: np.ndarray) -> int:
    if len(epochs) < 3:
        return 0
    diffs = np.diff(epochs.astype("int64"))
    median_diff = np.median(diffs)
    if median_diff == 0:
        return 0
    # A gap is any interval > 3x the median cadence
    return int(np.sum(diffs > 3 * median_diff))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cdf_workbench && python -m pytest tests/test_quality.py -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add cdf_workbench/quality.py cdf_workbench/tests/test_quality.py
git commit -m "feat: add pure-function quality analysis module"
```

---

## Task 4: Tree model with VAR_TYPE grouping

**Files:**
- Create: `cdf_workbench/tree_model.py`
- Create: `cdf_workbench/tests/test_tree_model.py`

- [ ] **Step 1: Write failing tests for tree model**

```python
import pytest
from PySide6.QtCore import Qt
from cdf_workbench.tree_model import CdfTreeModel, VariableInfo


def test_model_groups_by_var_type(sample_cdf_bytes):
    """Variables are grouped under Data/Support/Metadata/Uncategorized."""
    import pycdfpp
    cdf = pycdfpp.load(sample_cdf_bytes)
    model = CdfTreeModel(cdf)

    # Root should have group items
    root_count = model.rowCount()
    assert root_count >= 2  # at least Data and Support

    # Find group names
    group_names = []
    for i in range(root_count):
        idx = model.index(i, 0)
        group_names.append(model.data(idx, Qt.DisplayRole))
    assert "Data" in group_names
    assert "Support Data" in group_names


def test_model_variable_info(sample_cdf_bytes):
    """VariableInfo extracts shape, type, and key attributes."""
    import pycdfpp
    cdf = pycdfpp.load(sample_cdf_bytes)
    model = CdfTreeModel(cdf)

    # Find Bt variable
    info = model.variable_info("Bt")
    assert info is not None
    assert info.name == "Bt"
    assert info.units == "nT"
    assert info.depend_0 == "Epoch"


def test_model_uncategorized_group(sample_cdf_bytes):
    """Variables without VAR_TYPE go to Uncategorized."""
    import pycdfpp
    cdf = pycdfpp.load(sample_cdf_bytes)
    # Remove VAR_TYPE from Bt to simulate missing attribute
    # This test may need adjustment based on pycdfpp mutation API
    model = CdfTreeModel(cdf)
    # At minimum, model should not crash on missing VAR_TYPE
    assert model.rowCount() >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd cdf_workbench && python -m pytest tests/test_tree_model.py -v`
Expected: FAIL — `tree_model` module does not exist

- [ ] **Step 3: Implement tree_model.py**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt
import pycdfpp


VAR_TYPE_GROUPS = {
    "data": "Data",
    "support_data": "Support Data",
    "metadata": "Metadata",
}
UNCATEGORIZED = "Uncategorized"


@dataclass
class VariableInfo:
    name: str
    shape: tuple
    cdf_type: str
    var_type: str
    units: str = ""
    depend_0: str = ""
    display_type: str = ""
    fill_value: Optional[float] = None
    valid_min: Optional[float] = None
    valid_max: Optional[float] = None
    scale_type: str = "linear"
    catdesc: str = ""
    compression: str = ""
    all_attributes: dict = field(default_factory=dict)


@dataclass
class TreeNode:
    name: str
    parent: Optional[TreeNode] = None
    children: list[TreeNode] = field(default_factory=list)
    variable_info: Optional[VariableInfo] = None
    row: int = 0


def _get_attr(var, name, default=""):
    try:
        return str(var.attributes[name][0])
    except (KeyError, IndexError):
        return default


def _get_numeric_attr(var, name):
    try:
        val = var.attributes[name][0]
        return float(val)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _build_variable_info(name: str, var) -> VariableInfo:
    all_attrs = {}
    for attr_name, attr in var.attributes.items():
        try:
            all_attrs[attr_name] = [v for v in attr]
        except Exception:
            all_attrs[attr_name] = []

    return VariableInfo(
        name=name,
        shape=var.shape,
        cdf_type=str(var.type),
        var_type=_get_attr(var, "VAR_TYPE", ""),
        units=_get_attr(var, "UNITS"),
        depend_0=_get_attr(var, "DEPEND_0"),
        display_type=_get_attr(var, "DISPLAY_TYPE"),
        fill_value=_get_numeric_attr(var, "FILLVAL"),
        valid_min=_get_numeric_attr(var, "VALIDMIN"),
        valid_max=_get_numeric_attr(var, "VALIDMAX"),
        scale_type=_get_attr(var, "SCALETYP", "linear"),
        catdesc=_get_attr(var, "CATDESC"),
        compression=str(var.compression) if hasattr(var, "compression") else "",
        all_attributes=all_attrs,
    )


class CdfTreeModel(QAbstractItemModel):
    def __init__(self, cdf: pycdfpp.CDF, parent=None):
        super().__init__(parent)
        self._root = TreeNode(name="root")
        self._variable_map: dict[str, VariableInfo] = {}
        self._build_tree(cdf)

    def _build_tree(self, cdf: pycdfpp.CDF):
        groups: dict[str, TreeNode] = {}

        for var_name, var in cdf.items():
            info = _build_variable_info(var_name, var)
            self._variable_map[var_name] = info

            group_label = VAR_TYPE_GROUPS.get(info.var_type.lower(), UNCATEGORIZED)
            if group_label not in groups:
                group_node = TreeNode(
                    name=group_label,
                    parent=self._root,
                    row=len(self._root.children),
                )
                self._root.children.append(group_node)
                groups[group_label] = group_node

            group_node = groups[group_label]
            child = TreeNode(
                name=var_name,
                parent=group_node,
                variable_info=info,
                row=len(group_node.children),
            )
            group_node.children.append(child)

    def variable_info(self, name: str) -> Optional[VariableInfo]:
        return self._variable_map.get(name)

    def variable_infos(self) -> dict[str, VariableInfo]:
        return dict(self._variable_map)

    # --- QAbstractItemModel interface ---

    def rowCount(self, parent=QModelIndex()):
        node = self._node_from_index(parent)
        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        return 1

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if role == Qt.DisplayRole:
            return node.name
        return None

    def index(self, row, column, parent=QModelIndex()):
        parent_node = self._node_from_index(parent)
        if row < 0 or row >= len(parent_node.children):
            return QModelIndex()
        child = parent_node.children[row]
        return self.createIndex(row, column, child)

    def parent(self, index: QModelIndex):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        parent_node = node.parent
        if parent_node is None or parent_node is self._root:
            return QModelIndex()
        return self.createIndex(parent_node.row, 0, parent_node)

    def _node_from_index(self, index: QModelIndex) -> TreeNode:
        if index.isValid():
            return index.internalPointer()
        return self._root
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd cdf_workbench && python -m pytest tests/test_tree_model.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cdf_workbench/tree_model.py cdf_workbench/tests/test_tree_model.py
git commit -m "feat: add tree model with VAR_TYPE grouping and variable info extraction"
```

---

## Task 5: Inspector widget

**Files:**
- Create: `cdf_workbench/inspector.py`

- [ ] **Step 1: Implement inspector widget**

The inspector shows: variable header (name + description), attributes grid, clickable dependency links, quality bar, and plot action buttons. It emits signals when a dependency link is clicked or a plot action is requested.

```python
from __future__ import annotations
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QProgressBar, QPushButton, QFrame, QScrollArea, QMenu,
)
from .tree_model import VariableInfo
from .quality import QualityReport


ISTP_DISPLAY_ATTRS = [
    "Shape", "Type", "Units", "FILLVAL", "VALIDMIN", "VALIDMAX",
    "DEPEND_0", "DEPEND_1", "DEPEND_2", "DISPLAY_TYPE", "SCALETYP",
    "Compression",
]


class CdfInspectorWidget(QWidget):
    dependency_clicked = Signal(str)  # variable name
    plot_new_panel = Signal(str)      # variable name
    plot_to_panel = Signal(str, str)  # variable name, panel name
    send_to_console = Signal(str)     # variable name

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        self._header = QLabel("Select a variable")
        self._header.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._description = QLabel("")
        layout.addWidget(self._header)
        layout.addWidget(self._description)

        # Plot buttons
        btn_layout = QHBoxLayout()
        self._btn_new_panel = QPushButton("New Panel")
        self._btn_new_panel.clicked.connect(self._on_new_panel)
        self._btn_add_panel = QPushButton("Add to Panel ▾")
        self._btn_add_panel.clicked.connect(self._on_add_to_panel)
        btn_layout.addWidget(self._btn_new_panel)
        btn_layout.addWidget(self._btn_add_panel)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Attributes grid (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._attrs_container = QWidget()
        self._attrs_grid = QGridLayout(self._attrs_container)
        scroll.setWidget(self._attrs_container)
        layout.addWidget(scroll, stretch=1)

        # Quality bar
        self._quality_frame = QFrame()
        q_layout = QVBoxLayout(self._quality_frame)
        self._quality_label = QLabel("Data Quality")
        self._quality_bar = QProgressBar()
        self._quality_bar.setRange(0, 100)
        self._quality_detail = QLabel("")
        q_layout.addWidget(self._quality_label)
        q_layout.addWidget(self._quality_bar)
        q_layout.addWidget(self._quality_detail)
        layout.addWidget(self._quality_frame)

        self._current_var = None
        self._panel_names: list[str] = []
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool):
        self._btn_new_panel.setEnabled(enabled)
        self._btn_add_panel.setEnabled(enabled)
        self._quality_frame.setVisible(enabled)

    def update_variable(self, info: VariableInfo, quality: QualityReport | None = None):
        self._current_var = info.name
        self._header.setText(info.name)
        self._description.setText(info.catdesc)
        self._set_enabled(True)
        self._populate_attributes(info)
        if quality:
            self._update_quality(quality)

    def _populate_attributes(self, info: VariableInfo):
        # Clear existing
        while self._attrs_grid.count():
            item = self._attrs_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        row = 0
        fixed_attrs = {
            "Shape": str(info.shape),
            "Type": info.cdf_type,
            "Compression": info.compression,
        }
        for key, val in fixed_attrs.items():
            self._add_attr_row(row, key, val)
            row += 1

        for key, values in info.all_attributes.items():
            display_val = ", ".join(str(v) for v in values) if values else ""
            is_dep = key.startswith("DEPEND_") or key == "LABL_PTR_1"
            self._add_attr_row(row, key, display_val, clickable=is_dep)
            row += 1

    def _add_attr_row(self, row: int, key: str, value: str, clickable: bool = False):
        key_label = QLabel(f"{key}:")
        key_label.setStyleSheet("color: gray;")
        self._attrs_grid.addWidget(key_label, row, 0)

        if clickable and value:
            link = QPushButton(f"{value} →")
            link.setFlat(True)
            link.setStyleSheet("color: teal; text-align: left;")
            link.clicked.connect(lambda _, v=value: self.dependency_clicked.emit(v))
            self._attrs_grid.addWidget(link, row, 1)
        else:
            val_label = QLabel(value)
            self._attrs_grid.addWidget(val_label, row, 1)

    def _update_quality(self, report: QualityReport):
        self._quality_bar.setValue(int(report.valid_percentage))
        self._quality_detail.setText(
            f"Fill: {report.fill_percentage:.1f}%  "
            f"Out of range: {report.out_of_range_percentage:.1f}%  "
            f"Epoch gaps: {report.epoch_gaps}"
        )

    def _on_new_panel(self):
        if self._current_var:
            self.plot_new_panel.emit(self._current_var)

    def _on_add_to_panel(self):
        """Show dropdown of existing plot panels. Emits plot_to_panel(var_name, panel_name)."""
        if not self._current_var:
            return
        # Build menu of existing panels dynamically
        menu = QMenu(self)
        # Panels will be populated by the file_view via set_panel_names()
        if not self._panel_names:
            menu.addAction("No panels open").setEnabled(False)
        else:
            for name in self._panel_names:
                menu.addAction(name, lambda n=name: self.plot_to_panel.emit(self._current_var, n))
        menu.exec(self._btn_add_panel.mapToGlobal(self._btn_add_panel.rect().bottomLeft()))

    def set_panel_names(self, names: list[str]):
        """Called by file_view to update the list of available plot panels."""
        self._panel_names = names

    def show_global_attributes(self, attrs: dict):
        """Show global attributes when no variable is selected."""
        self._header.setText("Global Attributes")
        self._description.setText("")
        self._set_enabled(False)

        while self._attrs_grid.count():
            item = self._attrs_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for row, (key, values) in enumerate(attrs.items()):
            display_val = ", ".join(str(v) for v in values)
            self._add_attr_row(row, key, display_val)
```

- [ ] **Step 2: Commit**

```bash
git add cdf_workbench/inspector.py
git commit -m "feat: add inspector widget with attributes grid, dep links, quality bar"
```

---

## Task 6: Preview widget (matplotlib)

**Files:**
- Create: `cdf_workbench/preview.py`

- [ ] **Step 1: Implement preview widget**

```python
from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class CdfPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._figure = Figure(figsize=(5, 2), dpi=100)
        self._figure.set_facecolor("none")
        self._canvas = FigureCanvasQTAgg(self._figure)
        layout.addWidget(self._canvas)

        self._ax = self._figure.add_subplot(111)

    def plot_variable(
        self,
        values: np.ndarray,
        epochs: np.ndarray | None = None,
        label: str = "",
        units: str = "",
        scale_type: str = "linear",
        display_type: str = "",
    ):
        self._ax.clear()

        x = epochs if epochs is not None else np.arange(len(values))
        is_spectrogram = display_type.lower() == "spectrogram"

        if values.ndim == 1:
            self._ax.plot(x, values, linewidth=0.8)
        elif values.ndim == 2 and is_spectrogram:
            # 2D spectrogram (time x energy) → colormap
            self._ax.pcolormesh(x, np.arange(values.shape[1]), values.T, shading="auto")
        elif values.ndim == 2:
            # 2D multi-component → overlaid line plots
            for i in range(values.shape[1]):
                self._ax.plot(x, values[:, i], linewidth=0.8)
        else:
            self._ax.pcolormesh(values, shading="auto")

        if units:
            self._ax.set_ylabel(units)
        if label:
            self._ax.set_title(label, fontsize=10)
        if scale_type == "log":
            self._ax.set_yscale("log")

        self._figure.tight_layout()
        self._canvas.draw()

    def clear(self):
        self._ax.clear()
        self._canvas.draw()
```

- [ ] **Step 2: Commit**

```bash
git add cdf_workbench/preview.py
git commit -m "feat: add matplotlib preview widget for inline variable plots"
```

---

## Task 7: File view (per-tab composition widget)

**Files:**
- Create: `cdf_workbench/file_view.py`

- [ ] **Step 1: Implement CdfFileView**

This is the composition root for each tab. It wires tree, inspector, and preview together via signals. It also runs quality analysis in a background thread.

```python
from __future__ import annotations
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeView,
    QLineEdit,
)
from PySide6.QtCore import QSortFilterProxyModel
import pycdfpp

from .tree_model import CdfTreeModel, VariableInfo
from .inspector import CdfInspectorWidget
from .preview import CdfPreviewWidget
from .quality import analyze_quality, QualityReport


# Size threshold for skipping sparklines (100 MB)
SPARKLINE_SIZE_LIMIT = 100 * 1024 * 1024


class AnalysisWorker(QObject):
    """Runs quality analysis and sparkline extraction in a background thread."""
    # Use Signal(str, object) for cross-thread safety with custom types
    quality_ready = Signal(str, object)   # var_name, QualityReport
    sparkline_ready = Signal(str, object) # var_name, list[float]

    def __init__(self, cdf: pycdfpp.CDF, variable_infos: dict[str, VariableInfo]):
        super().__init__()
        self._cdf = cdf
        self._infos = variable_infos
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for name, info in self._infos.items():
            if self._cancelled:
                return
            try:
                var = self._cdf[name]
                # Skip sparklines for large variables (>100 MB estimated)
                estimated_size = np.prod(var.shape) * 8  # rough estimate
                values = var.values

                # Quality analysis
                epochs = None
                if info.depend_0 and info.depend_0 in self._cdf:
                    epochs = self._cdf[info.depend_0].values.astype("datetime64[ns]")
                report = analyze_quality(
                    values=values,
                    epochs=epochs,
                    fill_value=info.fill_value,
                    valid_min=info.valid_min,
                    valid_max=info.valid_max,
                )
                self.quality_ready.emit(name, report)

                # Sparkline: downsample to ~60 points
                if estimated_size < SPARKLINE_SIZE_LIMIT:
                    flat = values.ravel().astype(float)
                    if info.fill_value is not None:
                        flat = flat[flat != info.fill_value]
                    if len(flat) > 60:
                        indices = np.linspace(0, len(flat) - 1, 60, dtype=int)
                        flat = flat[indices]
                    samples = [float(v) for v in flat if np.isfinite(v)]
                    if samples:
                        self.sparkline_ready.emit(name, samples)
            except Exception:
                import logging
                logging.getLogger(__name__).debug(
                    "Analysis failed for %s", name, exc_info=True
                )


class CdfFileView(QWidget):
    def __init__(self, cdf: pycdfpp.CDF, main_window=None, parent=None):
        super().__init__(parent)
        self._cdf = cdf
        self._main_window = main_window
        self._quality_reports: dict[str, QualityReport] = {}
        self._setup_ui()
        self._start_quality_analysis()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main horizontal splitter
        splitter = QSplitter(Qt.Horizontal)

        # Left pane: search + tree
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter variables...")
        self._search.textChanged.connect(self._on_filter_changed)
        left_layout.addWidget(self._search)

        self._tree_model = CdfTreeModel(self._cdf)
        self._proxy_model = QSortFilterProxyModel()
        self._proxy_model.setSourceModel(self._tree_model)
        self._proxy_model.setRecursiveFilteringEnabled(True)
        self._proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)

        self._tree_view = QTreeView()
        self._tree_view.setModel(self._proxy_model)
        self._tree_view.setHeaderHidden(True)
        self._tree_view.expandAll()
        self._tree_view.selectionModel().currentChanged.connect(self._on_variable_selected)
        left_layout.addWidget(self._tree_view)

        splitter.addWidget(left)

        # Right pane: inspector + preview
        right_splitter = QSplitter(Qt.Vertical)

        self._inspector = CdfInspectorWidget()
        self._inspector.dependency_clicked.connect(self._navigate_to_variable)
        self._inspector.plot_new_panel.connect(self._plot_new_panel)
        right_splitter.addWidget(self._inspector)

        self._preview = CdfPreviewWidget()
        right_splitter.addWidget(self._preview)

        right_splitter.setStretchFactor(0, 2)
        right_splitter.setStretchFactor(1, 1)

        splitter.addWidget(right_splitter)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)

        # Show global attributes initially
        self._show_global_attributes()

    def _show_global_attributes(self):
        attrs = {}
        for name, attr in self._cdf.attributes.items():
            try:
                attrs[name] = [v for v in attr]
            except Exception:
                attrs[name] = []
        self._inspector.show_global_attributes(attrs)

    def _on_filter_changed(self, text: str):
        self._proxy_model.setFilterFixedString(text)

    def _on_variable_selected(self, current, previous):
        source_index = self._proxy_model.mapToSource(current)
        node = source_index.internalPointer()
        if node is None or node.variable_info is None:
            self._show_global_attributes()
            self._preview.clear()
            return

        info = node.variable_info
        quality = self._quality_reports.get(info.name)
        self._inspector.update_variable(info, quality)
        self._update_preview(info)

    def _update_preview(self, info: VariableInfo):
        try:
            var = self._cdf[info.name]
            values = var.values
            epochs = None
            if info.depend_0 and info.depend_0 in self._cdf:
                epoch_var = self._cdf[info.depend_0]
                epochs = epoch_var.values.astype("datetime64[ns]")

            # Mask fill values
            if info.fill_value is not None:
                values = np.where(values == info.fill_value, np.nan, values.astype(float))

            self._preview.plot_variable(
                values=values,
                epochs=epochs,
                label=info.name,
                units=info.units,
                scale_type=info.scale_type,
                display_type=info.display_type,
            )
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                "Preview failed for %s", info.name, exc_info=True
            )
            self._preview.clear()

    def _navigate_to_variable(self, var_name: str):
        """Select a variable in the tree by name."""
        for group_row in range(self._tree_model.rowCount()):
            group_idx = self._tree_model.index(group_row, 0)
            for var_row in range(self._tree_model.rowCount(group_idx)):
                var_idx = self._tree_model.index(var_row, 0, group_idx)
                node = var_idx.internalPointer()
                if node and node.name == var_name:
                    proxy_idx = self._proxy_model.mapFromSource(var_idx)
                    self._tree_view.setCurrentIndex(proxy_idx)
                    return

    def _plot_new_panel(self, var_name: str):
        if self._main_window is None:
            return
        try:
            from SciQLop.user_api.plot import create_plot_panel

            info = self._tree_model.variable_info(var_name)
            var = self._cdf[var_name]
            values = var.values.astype(float)

            if info.fill_value is not None:
                values = np.where(values == info.fill_value, np.nan, values)

            x = None
            if info.depend_0 and info.depend_0 in self._cdf:
                x = self._cdf[info.depend_0].values

            panel = create_plot_panel()
            if x is not None:
                panel.plot_data(x, values)
            else:
                panel.plot_data(np.arange(len(values)), values)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to plot %s", var_name, exc_info=True
            )

    def _start_quality_analysis(self):
        infos = {
            name: info
            for name, info in self._tree_model.variable_infos().items()
            if info.var_type.lower() == "data"
        }
        if not infos:
            return

        self._analysis_thread = QThread()
        self._analysis_worker = AnalysisWorker(self._cdf, infos)
        self._analysis_worker.moveToThread(self._analysis_thread)
        self._analysis_thread.started.connect(self._analysis_worker.run)
        self._analysis_worker.quality_ready.connect(self._on_quality_result)
        self._analysis_worker.sparkline_ready.connect(self._on_sparkline_result)
        # Clean up thread when worker finishes
        self._analysis_thread.finished.connect(self._analysis_thread.deleteLater)
        self._analysis_thread.start()

    def _on_quality_result(self, var_name: str, report: QualityReport):
        self._quality_reports[var_name] = report
        if hasattr(self, "_delegate"):
            self._delegate.set_quality(var_name, report.valid_percentage)
            self._tree_view.viewport().update()

    def _on_sparkline_result(self, var_name: str, samples: list):
        if hasattr(self, "_delegate"):
            self._delegate.set_sparkline(var_name, samples)
            self._tree_view.viewport().update()

    def release(self):
        """Release CDF data when tab is closed."""
        if hasattr(self, "_analysis_worker"):
            self._analysis_worker.cancel()
        if hasattr(self, "_analysis_thread") and self._analysis_thread.isRunning():
            self._analysis_thread.quit()
            self._analysis_thread.wait(5000)
        self._cdf = None
```

- [ ] **Step 2: Commit**

```bash
git add cdf_workbench/file_view.py
git commit -m "feat: add file view composing tree, inspector, preview with signal wiring"
```

---

## Task 8: Wire workbench panel with file open + drag-and-drop

**Files:**
- Modify: `cdf_workbench/workbench.py`

- [ ] **Step 1: Update workbench.py with full file-open logic**

Replace the minimal scaffold with the full implementation:

```python
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QLabel, QFileDialog, QMessageBox,
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from .loader import load_cdf, CdfLoadError
from .file_view import CdfFileView


class CdfWorkbenchPanel(QWidget):
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self.setWindowTitle("CDF Workbench")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.tabBarDoubleClicked.connect(self._on_tab_double_clicked)
        layout.addWidget(self._tabs)

        # "+" tab for opening files
        self._add_open_tab()

    def _add_open_tab(self):
        placeholder = QLabel("Drop CDF files here or double-click to open")
        placeholder.setAlignment(Qt.AlignCenter)
        self._tabs.addTab(placeholder, "+")

    def _on_tab_double_clicked(self, index: int):
        # Double-click on "+" tab opens file dialog
        if self._tabs.tabText(index) == "+":
            self.open_file_dialog()

    def open_file_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open CDF Files", "", "CDF Files (*.cdf);;All Files (*)"
        )
        for path in paths:
            self.open_file(path)

    def open_file(self, source: str):
        try:
            cdf = load_cdf(source)
        except CdfLoadError as e:
            QMessageBox.warning(self, "Failed to open CDF", str(e))
            return

        file_view = CdfFileView(cdf, main_window=self._main_window)
        name = Path(source).name if not source.startswith("http") else source.split("/")[-1]

        # Insert before the "+" tab
        insert_idx = max(0, self._tabs.count() - 1)
        self._tabs.insertTab(insert_idx, file_view, name)
        self._tabs.setCurrentIndex(insert_idx)

    def _close_tab(self, index: int):
        if self._tabs.tabText(index) == "+":
            return  # Don't close the "+" tab
        widget = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if isinstance(widget, CdfFileView):
            widget.release()
        widget.deleteLater()

    # --- Drag and drop ---

    def dragEnterEvent(self, event: QDragEnterEvent):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile() or url.toString()
                self.open_file(path)
        elif mime.hasText():
            text = mime.text().strip()
            if text.endswith(".cdf"):
                self.open_file(text)
```

- [ ] **Step 2: Update __init__.py to integrate with SciQLop**

Same as Task 1 Step 3 — the dock registration and menu action. No change needed here; just verify `__init__.py` still matches.

- [ ] **Step 3: Commit**

```bash
git add cdf_workbench/workbench.py cdf_workbench/__init__.py
git commit -m "feat: wire workbench panel with file open, drag-drop, and tab management"
```

---

## Task 9: Tree item delegate (sparklines + health badges)

**Files:**
- Modify: `cdf_workbench/tree_model.py` (add custom roles)
- Modify: `cdf_workbench/file_view.py` (set delegate, update on quality results)

- [ ] **Step 1: Add custom data roles and delegate to tree_model.py**

Add these to `tree_model.py`:

```python
# Custom roles
ROLE_QUALITY = Qt.UserRole + 1
ROLE_SPARKLINE = Qt.UserRole + 2
ROLE_IS_GROUP = Qt.UserRole + 3
```

Update `CdfTreeModel.data()` to return quality/sparkline data for custom roles.

Add `CdfItemDelegate(QStyledItemDelegate)` that:
- For group nodes: renders the group name + variable count
- For variable nodes: renders name + sparkline SVG + health percentage badge
- Uses `QPainter` to draw sparkline as a small polyline
- Colors the health badge green (>80%), yellow (50-80%), red (<50%)

```python
from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtCore import QRect, QSize


class CdfItemDelegate(QStyledItemDelegate):
    SPARKLINE_WIDTH = 60
    SPARKLINE_HEIGHT = 14
    BADGE_WIDTH = 40

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sparklines: dict[str, list[float]] = {}
        self._quality: dict[str, float] = {}

    def set_sparkline(self, var_name: str, samples: list[float]):
        self._sparklines[var_name] = samples

    def set_quality(self, var_name: str, valid_pct: float):
        self._quality[var_name] = valid_pct

    def sizeHint(self, option, index):
        base = super().sizeHint(option, index)
        return QSize(base.width() + self.SPARKLINE_WIDTH + self.BADGE_WIDTH + 20, max(base.height(), 22))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        node = index.model().mapToSource(index).internalPointer() if hasattr(index.model(), "mapToSource") else index.internalPointer()
        if node is None or node.variable_info is None:
            # Group node — default paint
            super().paint(painter, option, index)
            return

        painter.save()

        # Draw selection background
        if option.state & option.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        # Draw variable name
        name_rect = QRect(option.rect)
        name_rect.setWidth(option.rect.width() - self.SPARKLINE_WIDTH - self.BADGE_WIDTH - 16)
        painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, node.name)

        var_name = node.name

        # Draw sparkline
        if var_name in self._sparklines:
            spark_rect = QRect(
                option.rect.right() - self.SPARKLINE_WIDTH - self.BADGE_WIDTH - 12,
                option.rect.top() + (option.rect.height() - self.SPARKLINE_HEIGHT) // 2,
                self.SPARKLINE_WIDTH,
                self.SPARKLINE_HEIGHT,
            )
            self._draw_sparkline(painter, spark_rect, self._sparklines[var_name])

        # Draw health badge
        if var_name in self._quality:
            badge_rect = QRect(
                option.rect.right() - self.BADGE_WIDTH - 4,
                option.rect.top() + (option.rect.height() - 16) // 2,
                self.BADGE_WIDTH,
                16,
            )
            self._draw_badge(painter, badge_rect, self._quality[var_name])

        painter.restore()

    def _draw_sparkline(self, painter: QPainter, rect: QRect, samples: list[float]):
        if not samples:
            return
        mn, mx = min(samples), max(samples)
        rng = mx - mn if mx != mn else 1.0

        pen = QPen(QColor("#4ecca3"), 1.5)
        painter.setPen(pen)

        points = []
        n = len(samples)
        for i, v in enumerate(samples):
            x = rect.left() + i * rect.width() / max(n - 1, 1)
            y = rect.bottom() - ((v - mn) / rng) * rect.height()
            points.append((int(x), int(y)))

        for i in range(len(points) - 1):
            painter.drawLine(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])

    def _draw_badge(self, painter: QPainter, rect: QRect, valid_pct: float):
        if valid_pct > 80:
            color = QColor("#4ecca3")
            text_color = QColor("#000")
        elif valid_pct > 50:
            color = QColor("#e7c94c")
            text_color = QColor("#000")
        else:
            color = QColor("#e94560")
            text_color = QColor("#fff")

        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, 3, 3)

        painter.setPen(text_color)
        font = painter.font()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, f"{valid_pct:.0f}%")
```

- [ ] **Step 2: Wire delegate in file_view.py**

In `CdfFileView._setup_ui()`, after creating the tree view:

```python
self._delegate = CdfItemDelegate()
self._tree_view.setItemDelegate(self._delegate)
```

In `_on_quality_result()`:

```python
def _on_quality_result(self, var_name: str, report: QualityReport):
    self._quality_reports[var_name] = report
    self._delegate.set_quality(var_name, report.valid_percentage)
    # Force tree repaint
    self._tree_view.viewport().update()
```

- [ ] **Step 3: Commit**

```bash
git add cdf_workbench/tree_model.py cdf_workbench/file_view.py
git commit -m "feat: add tree item delegate with sparklines and health badges"
```

---

## Task 10: Console integration + context menu

**Files:**
- Modify: `cdf_workbench/file_view.py`

- [ ] **Step 1: Add context menu to tree view**

In `CdfFileView._setup_ui()`:

```python
self._tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
self._tree_view.customContextMenuRequested.connect(self._show_context_menu)
```

Add method:

```python
def _show_context_menu(self, pos):
    index = self._tree_view.indexAt(pos)
    if not index.isValid():
        return
    source_index = self._proxy_model.mapToSource(index)
    node = source_index.internalPointer()
    if node is None or node.variable_info is None:
        return

    from PySide6.QtWidgets import QMenu

    menu = QMenu(self)
    menu.addAction("Plot in New Panel", lambda: self._plot_new_panel(node.name))
    menu.addAction("Send to Console", lambda: self._send_to_console(node.name))
    menu.exec(self._tree_view.viewport().mapToGlobal(pos))


def _send_to_console(self, var_name: str):
    if self._main_window is None or self._cdf is None:
        return
    try:
        var = self._cdf[var_name]
        data = var.values
        self._main_window.push_variables_to_console({var_name: data})
    except Exception:
        import logging
        logging.getLogger(__name__).warning(
            "Failed to send %s to console", var_name, exc_info=True
        )
```

- [ ] **Step 2: Commit**

```bash
git add cdf_workbench/file_view.py
git commit -m "feat: add context menu with plot and send-to-console actions"
```

---

## Task 11: Integration test with a real CDF file

**Files:**
- Create: `cdf_workbench/tests/test_integration.py`

- [ ] **Step 1: Write integration test**

```python
"""Integration test: load a real CDF file from CDAWeb and verify the full pipeline."""
import pytest
import numpy as np


@pytest.fixture
def real_cdf():
    """Download a small CDF file from CDAWeb for testing."""
    from cdf_workbench.loader import load_cdf, CdfLoadError

    url = "https://cdaweb.gsfc.nasa.gov/pub/software/cdawlib/0MASTERS/ac_h5_swi_00000000_v01.cdf"
    try:
        return load_cdf(url)
    except CdfLoadError:
        pytest.skip("Cannot reach CDAWeb")


def test_full_pipeline(real_cdf):
    from cdf_workbench.tree_model import CdfTreeModel
    from cdf_workbench.quality import analyze_quality

    model = CdfTreeModel(real_cdf)
    assert model.rowCount() > 0

    # Find a data variable and analyze quality
    # variable_info() is the public API; iterate known var names from the CDF
    for name in real_cdf:
        info = model.variable_info(name)
        if info is None:
            continue
        if info.var_type.lower() == "data":
            values = real_cdf[name].values
            report = analyze_quality(
                values=values,
                fill_value=info.fill_value,
                valid_min=info.valid_min,
                valid_max=info.valid_max,
            )
            assert report.total_points > 0
            break
```

- [ ] **Step 2: Run integration test**

Run: `cd cdf_workbench && python -m pytest tests/test_integration.py -v --timeout=30`
Expected: PASS (or skip if network unavailable)

- [ ] **Step 3: Commit**

```bash
git add cdf_workbench/tests/test_integration.py
git commit -m "test: add integration test with real CDAWeb CDF file"
```

---

## Task 12: Final wiring and manual smoke test

- [ ] **Step 1: Verify plugin loads in SciQLop**

Copy/symlink the plugin to SciQLop's user plugin directory:

```bash
ln -s $(pwd)/cdf_workbench ~/.local/share/sciqlop/plugins/cdf_workbench
```

Launch SciQLop and verify:
- "CDF Workbench" appears in Tools menu
- Clicking it opens the workbench panel
- Opening a CDF file shows the variable tree
- Clicking a variable shows inspector + preview
- Clicking "New Panel" creates a SciQLop plot panel
- Right-click → "Send to Console" works
- Drag-and-drop works
- Closing tabs releases memory
- Filter search works

- [ ] **Step 2: Fix any issues found during smoke test**

- [ ] **Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete CDF Workbench v0.1.0"
```
