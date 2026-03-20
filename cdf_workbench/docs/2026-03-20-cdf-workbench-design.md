# CDF Workbench — SciQLop Plugin Design

**Date:** 2026-03-20
**Status:** Draft

## Goal

A multi-function CDF file explorer plugin for SciQLop — a Swiss army knife for inspecting, understanding, and plotting data from CDF files. Targets power users familiar with ISTP/CDF conventions.

## Capabilities

1. **Structure tree** — variables grouped by VAR_TYPE (data / support_data / metadata) with sparkline thumbnails and color-coded health badges. VAR_TYPE is read from each variable's attributes; variables missing VAR_TYPE are placed in an "Uncategorized" group.
2. **Variable inspector** — shape, type, compression, all ISTP attributes in a grid; DEPEND_0/1/2 and LABL_PTR_1 rendered as clickable navigation links
3. **Global attributes panel** — collapsible section at the top of the inspector; shown alone when no variable is selected
4. **Quick data preview** — sparklines in the tree for at-a-glance shape; larger matplotlib plot in the inspector preview area
5. **Data quality summary** — per-variable: fill value %, VALIDMIN/MAX out-of-range %, epoch gap count; displayed as health badge in tree + quality bar in inspector
6. **Search/filter** — filter variables by name, type, or attribute content
7. **Plot to SciQLop** — push data directly to SciQLopPlots (new panel or existing), no DataProvider needed since CDF data is static

## Non-Goals

- Raw data table view (doesn't scale for space physics data volumes)
- Multi-file comparison mode (architecture supports adding it later, but not in v1)
- DataProvider registration in the product tree

## Architecture

### Approach: Monolithic QWidget Panel

A single `CdfWorkbenchPanel` widget registered as a central panel in SciQLop. Contains a `QTabWidget` (one tab per open file), where each tab holds a `QSplitter`-based layout.

### Panel Layout

```
┌─────────────────────────────────────────────────────────┐
│  [mms1_fgm_brst.cdf]  [ace_swepam_h0.cdf]  [+]        │  ← Tab bar
├───────────────────────┬─────────────────────────────────┤
│  🔍 Filter variables  │  Variable: Bt                   │
│                       │  "Magnetic field magnitude"     │
│  📊 Data Variables    │  [📈 New Panel] [📌 Add to ▾]  │
│    Bt     ~~~ 98%     │                                 │
│    Bvec   ~~~ 97%     │  Shape: (14400,)  Type: FLOAT   │
│    pos    ~~~ 100%    │  Units: nT        FILLVAL: -1e31│
│    flag   ~~~ 42%     │  DEPEND_0: Epoch →              │
│                       │  DISPLAY_TYPE: time_series      │
│  📐 Support Data      │                                 │
│    Epoch              │  ┌─ Data Quality ─────────────┐ │
│    label_bvec         │  │ ████████████████████░ 98.2% │ │
│                       │  │ Fill:1.5% OOR:0.3% Gaps:2  │ │
│  🏷️ Metadata          │  └───────────────────────────┘ │
│    mms1_fgm_mode      ├─────────────────────────────────┤
│                       │  PREVIEW                        │
│                       │  ┌─────────────────────────────┐│
│                       │  │  ╱╲  ╱╲    ╱╲              ││
│                       │  │ ╱  ╲╱  ╲╱╲╱  ╲╱╲           ││
│                       │  └─────────────────────────────┘│
└───────────────────────┴─────────────────────────────────┘
       Left pane                    Right pane
     (resizable via QSplitter, both horizontally and vertically)
```

### Module Structure

```
cdf_workbench/
├── __init__.py          # exports load()
├── plugin.json          # metadata, declares pycdfpp/httpx/matplotlib deps
├── workbench.py         # CdfWorkbenchPanel — top-level QWidget with QTabWidget
├── file_view.py         # CdfFileView — per-file widget (splitter + sub-widgets)
├── tree_model.py        # CdfTreeModel (QAbstractItemModel) + CdfItemDelegate
├── inspector.py         # CdfInspectorWidget — attributes grid, dep links, quality bar
├── preview.py           # CdfPreviewWidget — matplotlib FigureCanvas inline plot
├── quality.py           # analyze_quality(var) → QualityReport dataclass (pure, no Qt)
└── loader.py            # load_cdf(path_or_url) → pycdfpp.CDF
```

### Data Flow

```
User opens file
  → loader.load_cdf(path_or_url) → pycdfpp.CDF
  → CdfWorkbenchPanel creates new CdfFileView tab
  → CdfFileView builds CdfTreeModel from CDF
    → quality.analyze_quality() per variable (background QThread)
    → sparklines from first/last N samples (background QThread)
    → tree populates progressively as analysis completes

User clicks variable in tree
  → CdfFileView.variable_selected signal
  → InspectorWidget updates attributes grid + quality bar
  → PreviewWidget loads full data, renders matplotlib plot

User clicks dependency link (e.g. "Epoch →")
  → tree selection jumps to that variable → same signal chain

User clicks "New Panel"
  → var.values → numpy array
  → resolves DEPEND_0 for x-axis
  → main_window.new_plot_panel() + push to SciQLopPlots

User clicks "Add to Panel ▾"
  → dropdown lists existing panels → push data to selected

User right-clicks → "Send to Console"
  → main_window.push_variables_to_console({name: array})
```

### Key Design Decisions

- **Lazy loading** — pycdfpp defaults to `lazy_load=True`; variable data is loaded on first access of `var.values`. Note: pycdfpp loads the entire variable at once (no partial reads). Sparkline generation triggers a full load, so variables above a size threshold (e.g. >100 MB) should skip sparklines and show a placeholder.
- **Background threading** — quality analysis and sparkline computation run in QThread workers to keep UI responsive
- **Memory management** — closing a tab releases the `CDF` object and all loaded variable data. Consider tracking approximate memory per tab and warning the user when total exceeds a configurable threshold.
- **Signals as only coupling** — tree emits selection signal, inspector and preview react independently
- **Pure quality module** — `quality.py` has no Qt dependency, takes pycdfpp variable, returns dataclass; easily testable
- **No DataProvider** — CDF data is static/finite; numpy arrays pushed directly to SciQLopPlots
- **ISTP-aware plotting** — respects DISPLAY_TYPE (time_series → line, spectrogram → colormap), UNITS, FIELDNAM, SCALETYP for axis configuration

### File Loading

| Method | Implementation |
|--------|---------------|
| Local file | `pycdfpp.load(path)` |
| URL | `httpx.get(url).content` → `pycdfpp.load(bytes)` |
| Drag-and-drop | Accept `QMimeData` with file paths or URL text |
| "+" tab button | `QFileDialog` with `*.cdf` filter |

Error handling: `pycdfpp.load()` returns `None` on corrupted CDF data (does not raise). `loader.py` raises a `CdfLoadError` in that case. Network/file errors are caught as standard exceptions. Both cases show an error state in the tab with message + "Retry" button for URLs.

### SciQLop Integration

- **Menu:** "CDF Workbench" action in `main_window.toolsMenu`
- **Toolbar:** optional quick-access button
- **Plotting:** direct numpy push to SciQLopPlots, respecting CDF display hints
- **Console:** right-click "Send to Console" via `main_window.push_variables_to_console()`

**Note:** The exact main_window API (`toolsMenu`, `new_plot_panel()`, `push_variables_to_console()`) must be verified against the SciQLop main window class before implementation begins.

### Dependencies

```json
{
  "name": "CDF Workbench",
  "version": "0.1.0",
  "description": "Multi-function CDF file explorer for SciQLop",
  "authors": [{"name": "TBD", "email": "TBD", "organization": "TBD"}],
  "license": "MIT",
  "python_dependencies": ["pycdfpp", "httpx", "matplotlib"],
  "dependencies": [],
  "disabled": false
}
```

httpx is chosen over `urllib.request` for better timeout defaults and potential future async support.

### Future Extensions (Not in v1)

- Multi-file comparison mode (overlay same variable from two files)
- Export to other formats (CSV, netCDF)
- CDF file validation against ISTP standards
- Integration with CDAWeb for browsing remote datasets
