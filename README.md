# SciQLop Plugins

A bundle of plugins for [SciQLop](https://github.com/SciQLop/SciQLop). Each plugin is built as an independent wheel and published as a GitHub release artifact.

## Plugins

### CDF Workbench

A multi-function CDF file explorer — a Swiss army knife for inspecting, understanding, and plotting data from CDF files.

- Structure tree with sparkline thumbnails and health badges
- Variable inspector with ISTP attributes and clickable DEPEND links
- Data preview (time series / spectrogram) respecting DISPLAY_TYPE and SCALETYP
- Data quality reporting (fill %, out-of-range %, epoch gaps)
- ISTP conformance via [AstraLint](https://github.com/SciQLop/AstraLint)
- Plot to SciQLop panels via Speasy's CDF codec
- Multi-file tabs, drag-and-drop, search/filter

Dependencies: `pycdfpp`, `httpx`, `matplotlib`

### MSA BepiColombo

MSA instrument data access and quick-look panels for the BepiColombo/MMO mission.

- Data access via Speasy inventory
- Quick-look visualization panels

Dependencies: `speasy`

## Installation

Install from the SciQLop AppStore, or manually:

```bash
# from a release
uv pip install https://github.com/SciQLop/sciqlop-plugins/releases/download/v0.1.0/sciqlop_cdf_workbench-0.1.0-py3-none-any.whl
uv pip install https://github.com/SciQLop/sciqlop-plugins/releases/download/v0.1.0/sciqlop_msa-0.1.0-py3-none-any.whl
```

## Development

Each plugin lives in its own directory with a `pyproject.toml`:

```
cdf_workbench/
├── pyproject.toml
└── cdf_workbench/
    ├── __init__.py
    ├── plugin.json
    └── ...
sciqlop_msa/
├── pyproject.toml
└── sciqlop_msa/
    ├── __init__.py
    ├── plugin.json
    └── ...
```

On tag push (`v*`), the CI builds a wheel per plugin and attaches them to a GitHub release.
