# SciQLop Plugins

A collection of plugins for [SciQLop](https://github.com/SciQLop/SciQLop).

## CDF Workbench

A multi-function CDF file explorer plugin — a Swiss army knife for inspecting, understanding, and plotting data from CDF files. Targets power users familiar with ISTP/CDF conventions.

### Features

- **Structure tree** — variables grouped by VAR_TYPE (data / support_data / metadata) with sparkline thumbnails, display type tags (TS/SP), and color-coded health badges
- **Variable inspector** — shape, type, compression, all ISTP attributes; DEPEND_0/1/2 and LABL_PTR_1 rendered as clickable navigation links
- **Global attributes panel** — shown when no variable is selected
- **Data preview** — matplotlib inline plot respecting DISPLAY_TYPE (time_series / spectrogram) and SCALETYP
- **Data quality** — per-variable fill value %, VALIDMIN/MAX out-of-range %, epoch gap count
- **ISTP conformance** — [AstraLint](https://github.com/SciQLop/AstraLint) integration for ISTP standard validation with per-variable and file-level issue reporting
- **Search/filter** — filter variables by name
- **Plot to SciQLop** — push data directly to SciQLopPlots panels (new or existing) via Speasy's CDF codec, with automatic time range adjustment
- **Multi-file tabs** — open multiple CDF files side by side
- **Drag-and-drop** — drop local files or URLs onto the workbench

### Dependencies

`pycdfpp`, `pyistp`, `speasy`, `httpx`, `matplotlib`, `astralint`

Install from the SciQLop AppStore.
