# sciqlop_sismo — design

**Status:** design, awaiting approval
**Date:** 2026-05-12
**Author:** Alexis Jeandet (with Claude)

## Goal

A SciQLop plugin that brings seismology waveforms into the SciQLop main timeline as first-class `SpeasyVariable` products, by implementing a custom Speasy data provider on top of the FDSN web services (via ObsPy). Unlike `sciqlop_radio`, the plugin does **not** host its own plots — every fetched channel is a Speasy product that drag-drops onto the main timeline, composes with other space-physics data, and benefits from SciQLop's catalogs, time navigator, and multi-panel sync.

## Non-goals (v1)

- Real-time / SeedLink streaming.
- Instrument-response deconvolution (counts → m/s via StationXML). Plumbed for v2.
- Map view of stations (planned for v2 — see "Evolution path").
- Cross-correlation, beamforming, ML pipelines.
- A persisted user inventory editor — v1 persists added channels to YAML but does not provide a UI to edit it.

## User-facing summary

A "Sismo" dock with three tabs (Stations, Events, Local files) lets the user discover FDSN channels and add them to a "sismo" tree in SciQLop's main inventory. Each channel exposes three products:

- `<NSLC>/waveform` — 1-D time-series, lightly preprocessed (detrend + bandpass).
- `<NSLC>/raw` — 1-D time-series, raw instrument counts, no processing.
- `<NSLC>/spectrogram` — 2-D time × frequency colormap.

Once added, these products drag-drop onto any panel exactly like CDA-Web or AMDA products.

## Architecture

```
┌────────────────────────── sciqlop_sismo ───────────────────────────┐
│                                                                    │
│  dock.py  (browser/builder, no plots)                              │
│    ├─ Stations tab   ──┐                                           │
│    ├─ Events tab     ──┤  "Add to inventory"  ┐                    │
│    └─ Local files    ──┘                      │                    │
│                                               ▼                    │
│                                     provider.SismoProvider         │
│                                     (Speasy DataProvider)          │
│                                     ┌────────────────────────────┐ │
│                                     │ build_inventory()          │ │
│                                     │ add_channel(NSLC, range)   │ │
│                                     │ get_data(prod, t0, t1)     │ │
│                                     └────────────┬───────────────┘ │
│                                                  │                 │
│                                                  ▼                 │
│  fdsn_client.py  (pure I/O; no Qt, no Speasy)                      │
│    fetch_stream(NSLC, t0, t1) → obspy.Stream                       │
│    search_stations(...) / search_events(...)                       │
│                                                  │                 │
│  process.py     (pure fns: detrend, bandpass)    │                 │
│  stream_to_variable.py  (Stream→SpeasyVariable,  │                 │
│                          Stream→spectrogram SV)  ▼                 │
│                                          SpeasyVariable            │
│                                                  │                 │
└──────────────────────────────────────────────────┼─────────────────┘
                                                   │
                            drops into SciQLop main timeline
                            (drag-drop, plot_product, catalogs)
```

### Module layout

```
sciqlop_sismo/
├── pyproject.toml              # entry point: sciqlop.plugins → sciqlop_sismo:load
├── README.md
└── sciqlop_sismo/
    ├── __init__.py             # load(main_window): instantiate provider + dock
    ├── provider.py             # SismoProvider(DataProvider)
    ├── fdsn_client.py          # ObsPy RoutingClient wrapper, pure I/O
    ├── process.py              # pure fns: detrend, bandpass, default_pipeline
    ├── stream_to_variable.py   # Stream → SpeasyVariable (waveform + spectrogram)
    ├── local_files.py          # obspy.read(path) + inventory injection helper
    ├── dock.py                 # SismoBrowserDock (search + "Add to inventory")
    ├── settings.py             # pydantic, with field_validator clamping
    └── tests/
        ├── conftest.py
        ├── test_fdsn_client.py
        ├── test_process.py
        ├── test_stream_to_variable.py
        ├── test_local_files.py
        ├── test_provider.py
        ├── test_dock.py
        ├── test_settings.py
        └── test_load.py
```

### Module rules

- `fdsn_client.py`, `process.py`, `stream_to_variable.py`, `local_files.py`: **no Qt, no Speasy** imports. Pure ObsPy + NumPy + SciPy. Trivially testable headless.
- `provider.py`: depends on Speasy + the three pure modules. No Qt. `get_data` runs on whatever thread calls it (SciQLop's data thread on drag-drop, or a `QRunnable` worker the dock kicks off for "Add now").
- `dock.py`: Qt + provider, no ObsPy directly. Talks to the provider via its public methods. Uses `QThreadPool` + `QRunnable` + queued `Signal`s for async — **no qasync** (per `feedback_qasync_httpx_async_client`).
- `settings.py`: pydantic `BaseSettings` with `field_validator(mode="before")` clamping for any bounded numeric (per `feedback_configentry_clamp_bounds`).

## Provider & product model

**`SismoProvider(DataProvider)`** — `provider_name="sismo"`, alt names `["seismic", "fdsn"]`.

### Inventory shape

```
sismo/
└── <Network>/                  e.g. "G"  (GEOSCOPE)
    └── <Station>/              e.g. "SSB"
        └── <Loc>.<Chan>        e.g. "00.HHZ"   ← DatasetIndex
            ├── waveform        ParameterIndex (1-D, m/s)
            ├── raw             ParameterIndex (1-D, counts)
            └── spectrogram     ParameterIndex (2-D, dB)
```

One channel → one dataset → three parameters. UIDs are the Speasy product paths used by `get_data` and drag-drop, e.g. `sismo/G/SSB/00.HHZ/waveform`. Three params keeps "raw vs processed vs spectrogram" explicit and individually drag-droppable, rather than hiding the choice behind kwargs that Speasy's `get_data` cannot carry.

### `meta` carried on each `ParameterIndex`

- `nslc`: `("G", "SSB", "00", "HHZ")` tuple
- `kind`: one of `"waveform" | "raw" | "spectrogram"`
- `sample_rate_hz`: from StationXML when available, else None
- `bandpass`: `(fmin, fmax)` for waveform/spectrogram (defaults from settings; overridable per-channel)
- `routing`: data-center / federator identifier the channel was discovered on, or `local:<sha1-of-path>` for local files
- `start_date` / `stop_date`: ObsPy channel availability (used by `_parameter_range`)

### Inventory lifecycle

- `build_inventory(root)`: starts **empty** (no global FDSN crawl). Optionally re-loads a user inventory from YAML at `~/.config/sciqlop/sismo/inventory.yaml` so previously added channels persist across restarts.
- `add_channel(net, sta, loc, chan, t0, t1, *, sample_rate=None, routing="iris-federator")`: synthesizes the three `ParameterIndex` nodes under the right parent and refreshes SciQLop's inventory tree. Also appends to the YAML for persistence.
- `remove_channel(...)`: counterpart for cleanup.

### `get_data(product, start_time, stop_time, **kwargs) → SpeasyVariable`

Dispatched on `meta["kind"]`:

- `waveform` → `fdsn_client.fetch_stream(NSLC, t0, t1)` → `process.default_pipeline(stream, settings)` → `stream_to_variable.stream_to_speasy_variable(stream, chan, units="m/s")`
- `raw` → `fetch_stream` → `stream_to_speasy_variable(..., units="counts")` (no processing)
- `spectrogram` → `fetch_stream` → `default_pipeline` → `stream_to_variable.spectrogram(stream, chan, nfft, overlap)` → 2-D `SpeasyVariable` with `VariableAxis` for frequency. SciQLop renders as colormap natively (per `feedback_sciqlopplots_colormap_axes`).

## Dock — inventory builder

`SismoBrowserDock(QWidget)` — one dock, three tabs. **No plot widgets in the dock.** "Plot" affordances all call `SciQLop.user_api.plot.create_plot_panel()` + `panel.plot_product(uid)` on the main timeline.

### Tab 1 — Stations

- Inputs: `Network` (e.g. `G,FR,IU`), `Station` (e.g. `SSB,CCD,*`), `Location` (default `*`), `Channel` (default `HH?,BH?`), time range (start/end UTC pickers).
- Routing dropdown: `iris-federator` (default), `eida-routing`, or a single data-center code.
- **`Search`** → on a `QThreadPool` worker: `fdsn_client.search_stations(...)` → returns an `obspy.Inventory`. Results populate a tree-view (Network → Station → Loc.Chan rows) showing availability range and sample rate.
- Selection model: extended (multi-select).
- **`Add to inventory`** → calls `provider.add_channel(...)` per selected row; rows turn green ("in inventory").
- **`Plot waveform`** / **`Plot spectrogram`** → calls `create_plot_panel()` + `plot_product()` for each selected row's `waveform` / `spectrogram` parameter (auto-adds first if needed). Time range = the search range.

The Stations tab is built as a `QSplitter` with two children — `StationsTreeView` (v1) and a placeholder slot for `StationsMapView` (v2). Both bind to a shared `QItemSelectionModel` over the same backing `QAbstractItemModel`, so the v2 map widget drops in without retrofit.

### Tab 2 — Events

- Inputs: time range, `min_magnitude`, optional bbox (lat/lon min/max) or center+radius, event catalog (`USGS` default, `EMSC`, `ISC`).
- **`Search events`** → `fdsn_client.search_events(...)` → table of events.
- Pick one event. Distance controls: `min_radius_deg` / `max_radius_deg` (default 0–30°). Channel filter pre-filled from Tab 1's defaults.
- **`Find stations`** → `search_stations(..., latitude, longitude, radius=...)` constrained around the event. Sub-list of results.
- **`Add all to inventory`** / **`Plot record section`** — record section = one panel per station, stacked, aligned on `event.origin_time ± window`. Implemented as a loop of `panel.plot_product()` calls into one freshly created `create_plot_panel()`.

### Tab 3 — Local files

- **`Open local…`** → `QFileDialog` → for each file, `local_files.import_file(path)` registers it in the provider's inventory under `sismo/<Net>/<Sta>/<Loc>.<Chan>` (with `routing="local:<sha1>"`).
- **`Plot waveform`** / **`Plot spectrogram`** on selected files.

### Status bar

Cross-tab, selectable, word-wrapped — single source of truth for "what's happening / what failed".

## Error handling

- Search/fetch errors caught at the `QRunnable.run()` boundary, emitted on a `failed(msg)` signal → status bar (selectable text).
- When **every** item in a batch fails, pop a `QMessageBox.Warning` with `setDetailedText(...)` listing per-row reasons — the user can't miss total failure. Mirrors the radio plugin's all-fail modal.
- `get_data` errors (called on SciQLop's data thread on drag-drop, not by the dock) bubble up as `None` plus a logged exception. Speasy handles `None` returns gracefully.
- Input validation (start_time after stop_time, bad NSLC pattern): in the dock before launching a worker; surfaced in status bar, no modal.
- `RoutingClient` errors from a flaky sub-data-center include a multi-line message naming the bad sub-client — **preserve verbatim** in the status bar; do not truncate.

## Caching

- Per-channel `Stream` results cached on disk via Speasy's `@CacheCall` with configurable retention (default 7 days). Key: `(NSLC, start_time, stop_time, routing, processed_flag)`.
- Spectrogram colormaps cached separately (STFT on hours of 100 Hz data is non-trivial).
- StationXML responses (`search_stations`) cached with shorter retention (12 h).
- Cache directory configurable via `settings.cache_dir` (default `~/.cache/sciqlop/sismo/`).

## Threading

Every blocking call (FDSN search, FDSN fetch, `obspy.read`, STFT compute) goes through `QThreadPool.globalInstance().start(QRunnable)`. Worker emits a queued `Signal` back to the dock. No qasync. No GUI-thread network calls.

## Testing

- `test_fdsn_client.py` — mock `obspy.clients.fdsn.RoutingClient`/`Client`. One live-network test behind a `pytest.mark.live` marker hitting `IRIS` for `IU.ANMO.00.BHZ` for a known small window. Skipped by default in CI.
- `test_process.py` — pure-function tests. Detrend on a synthetic Stream with known offset → mean ≈ 0. Bandpass on summed sinusoids → out-of-band amplitudes near zero.
- `test_stream_to_variable.py` — synthetic Stream → `SpeasyVariable`; assert `axes[0]` is `VariableTimeAxis` with monotone UTC epochs, `values.shape` matches trace npts, units propagate. For spectrogram, assert 2-D shape, monotone frequency axis, no NaN.
- `test_local_files.py` — bundle one ~5 KB miniSEED fixture (synthetic via `obspy.Trace.write`); read it, assert `add_channel` gets the right NSLC.
- `test_provider.py` — instantiate `SismoProvider`, call `add_channel`, assert inventory shape, call `get_data` with `fdsn_client.fetch_stream` patched, assert a valid `SpeasyVariable` returns.
- `test_dock.py` — Qt headless via `pytest-qt` `qtbot`. Patch the provider + client. Drive search → results populate; "Add to inventory" → provider got called with expected NSLC. No real network.
- `test_settings.py` — pydantic validators clamp out-of-range freq band and `cache_retention_days`. Stale-YAML round-trip doesn't crash (per `feedback_configentry_clamp_bounds`).
- `test_load.py` — import-and-`load(MagicMock())` smoke; entry point resolves.

**Conventions to keep:**

- `conftest.py` applies the `atexit os._exit(0)` workaround (per `feedback_sciqlopplots_exit_segfault`).
- Guard SciQLop / SciQLopPlots imports under `try/except ImportError` so headless CI works; plot-trigger buttons no-op when `SciQLop.user_api.plot` isn't importable.

## Dependencies

**Runtime:** `obspy>=1.4`, `numpy`, `scipy`, `speasy>=1.7`, `pydantic>=2`, `PyYAML`.
**Optional (v2):** `matplotlib`, `cartopy` — gated by the map widget.
**Host environment:** `PySide6`, `SciQLop` (provided by the host, like other plugins).

`pyproject.toml` entry point:

```toml
[project.entry-points."sciqlop.plugins"]
sismo = "sciqlop_sismo:load"
```

Release tags follow the `sciqlop_sismo/v0.1.0` convention (per `plugin_repo_layout`).

## Evolution path

- **v1** — Stations + Events + Local files dock; three parameters per channel (waveform / raw / spectrogram); YAML-persisted inventory; federator-first FDSN routing.
- **v2** — Map view of stations (option 1: `QGraphicsView` + Natural Earth raster, ~150 LoC, no new heavy deps); instrument-response removal as a fourth parameter or a `kind="waveform_displacement"`; event catalog products (Speasy `Catalog`).
- **v3** — Persisted user inventory editor; cross-correlation helpers; possible reshape of `sciqlop_radio` onto the same Speasy-provider pattern.

## Open questions (none blocking implementation)

- Should `add_channel` accept a `bandpass_override` kwarg for per-channel filter customization, or are project-wide settings sufficient? **Default for v1:** project-wide only; per-channel overrides come if users ask.
- Persistence YAML schema: include `routing` per channel? **Default for v1:** yes, so reload works exactly as added.

## Anti-template note

`sciqlop_radio` is **not** the structural template for this plugin (per `feedback_radio_plugin_not_a_template`). We reuse its working pieces — `QThreadPool` + `QRunnable` + `Signal` threading model, pydantic settings with clamping, all-fail modal — but we explicitly reject its "dock as self-contained viewer with its own plot tabs" shape in favor of the Speasy-provider integration.
