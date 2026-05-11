# sciqlop_radio plugin — design

**Date:** 2026-05-12
**Status:** approved-for-planning
**Author:** Alexis Jeandet (with Claude)

## Context

Lorentz Center workshop *"Bridging gaps in heliospheric radio data analyses"* (May 2026) has, as one of its software outcomes, a modular open-source data container for radio dynamic spectra inside SunPy. The workshop's documented pain points are concentrated around:

- discovery: no central catalogue of who serves what radio data
- download: per-instrument manual workflows (especially SolO/RPW, WAVES, SWAVES, RFS)
- format heterogeneity: CDF, FITS, `.fit.gz`, proprietary
- metadata heterogeneity: WIND/WAVES and STEREO/SWAVES use inconsistent CDF variable/attribute names
- multi-instrument synoptic views: PSP + SolO + WIND + STEREO + ground stations on the same time axis
- 1D-vs-2D flux storage and time-resolution mismatches

This plugin gives SciQLop a "radiospectra mode" — search, download, view of heliospheric radio dynamic spectra — and acts as Alexis's vehicle for engaging with the workshop. Long-term it can host the SciQLop side of whatever container abstraction the SunPy effort produces; near-term it stays thin and rides on `sunpy.radiospectra`.

## Goals

1. Ship a `sciqlop_radio` plugin in the `sciqlop-plugins` monorepo that, as MVP, lets the user pick one of `sunpy.radiospectra`'s 9 supported sources, fetch files for a time range via `sunpy.net.Fido`, and render each as a native `SciQLopPlot` colormap.
2. Render through SciQLop's native plotting (not embedded matplotlib) so plots participate in SciQLop's time bar, theme, sync, and future stacking.
3. Stay decoupled from any container abstraction in the MVP — the data model is `radiospectra.Spectrogram`. The translator's input contract is the only place that would need to grow if we later add a `RadioSpectrogram` model.
4. Provide a foundation to add later: multi-instrument stacking, instruments not covered by `radiospectra` (NDA Stokes, ORFEES, MWA, NenuFAR…), a Speasy provider, and contributions back to the SunPy container.

## Non-goals (MVP)

- No new data-model abstraction. Use `radiospectra.Spectrogram` directly through the translator boundary.
- No multi-instrument stacked synoptic view. One plot per spectrogram.
- No instruments outside `sunpy.radiospectra`'s built-in list (NDA, ORFEES, MWA, etc.).
- No Speasy provider work.
- No authentication / keyring. All target archives are anonymous.

## Repository placement

Per the monorepo strategy memory: this is a generic, multi-instrument plugin and belongs in `sciqlop-plugins` rather than a separate repo. New top-level subdirectory `sciqlop_radio/` with its own `pyproject.toml` and `plugin.json`. Releases tag as `sciqlop_radio/vX.Y.Z`.

## Package layout

```
sciqlop_radio/
  pyproject.toml          # sciqlop-radio; deps: SciQLop>=0.12, sunpy>=6.0, radiospectra>=1.0, astropy, numpy, pydantic
  plugin.json             # SciQLop manifest, requires SciQLop>=0.12
  sciqlop_radio/
    __init__.py           # load(main_window): registers dock + toolbar action (idempotent)
    sources.py            # SOURCES: list[RadioSource]; static registry of supported instruments
    fetch.py              # RadioFetchService(QObject): Fido search/fetch on QThreadPool with Qt signals
    reader.py             # open_spectrogram(path) -> Spectrogram | SpectrogramSequence (radiospectra shim)
    plot.py               # spectrogram_to_plot(spec, parent) -> SciQLopPlot (the translator)
    dock.py               # RadioSpectraDock(QDockWidget): UI orchestrator
    settings.py           # RadioSettings(ConfigEntry): cache dir, timeout, parallel downloads
    tests/
      conftest.py         # Qt stubs + atexit os._exit(0) workaround
      data/               # one tiny WIND/WAVES CDF, one eCallisto FIT — committed
      test_sources_registry.py
      test_plot_translator.py
      test_reader.py
      test_dock.py        # pytest-qt + fake fetch service
      test_fetch_live.py  # marked network, skipped unless RADIO_LIVE_TESTS=1
```

Entry point:
```toml
[project.entry-points."sciqlop.plugins"]
sciqlop_radio = "sciqlop_radio:load"
```

`load(main_window)` registers exactly one dock and one toolbar action; calling it twice is a no-op.

## Components

### `sources.py` — static registry

```python
class RadioSource(BaseModel):
    key: str                     # "psp_rfs", "wind_waves", "ecallisto", ...
    label: str                   # "PSP / RFS"
    fido_instrument: str | None  # arg for sunpy.net.attrs.Instrument; None means local-only
    notes: str = ""
    accepts_local: bool = True

SOURCES: list[RadioSource] = [ ... ]   # one entry per radiospectra source
```

Pure data. Tests assert: unique keys, non-empty labels, every entry has at least one of `fido_instrument` or `accepts_local=True`.

### `fetch.py` — `RadioFetchService(QObject)`

Wraps `sunpy.net.Fido`. Two async methods, both fire-and-forget from the GUI thread:

- `search(source: RadioSource, t_start: datetime, t_end: datetime) -> None`
  emits `searchCompleted(rows: list[FidoRow])` or `searchFailed(message: str)`
- `fetch(rows: list[FidoRow]) -> None`
  emits `fetchProgress(done: int, total: int)`, `fetchCompleted(paths_ok: list[Path], paths_failed: list[tuple[FidoRow, str]])`, `fetchFailed(message: str)`

Implementation uses `QThreadPool.globalInstance()` + `QRunnable`. Inside the worker, calls `Fido.search`/`Fido.fetch` synchronously. Signals are emitted via `Qt.QueuedConnection` so they always land on the GUI thread. No `asyncio`, no `qasync` interaction (sidesteps the cancel-scope bug class from prior plugins).

Cache directory comes from `RadioSettings.cache_dir`. Each row's expected local filename is checked against the cache before invoking Fido; cache hits skip the network.

Cancellation: per-task `cancel_token` (`threading.Event`); the dock exposes a "Cancel" button that sets it. Best-effort — interrupts between files, not mid-byte.

### `reader.py` — `open_spectrogram(path: Path)`

One-line shim around `radiospectra.Spectrogram(path)`. Single seam for tests to mock and for per-source workarounds (eCallisto frequency-range-in-filename, etc.) if/when needed. Returns a `Spectrogram` or `SpectrogramSequence`.

### `plot.py` — `spectrogram_to_plot(spec, parent_window) -> SciQLopPlot`

The translator. The only module that imports SciQLop plotting types.

- Pulls `times`, `frequencies` (or `wavelength`), `data`, `meta` from the radiospectra spectrogram.
- Creates a `SciQLopPlot`, adds a colormap graph.
- `x_axis()` → time, label `"UTC"`.
- `y2_axis()` → frequency. Unit from `spec.meta.get("wavelength_unit", "Hz")`. Log scale if `spec.meta.get("scale_type", "log") == "log"`. Label `"Frequency [{unit}]"`.
  (Uses `y2_axis`, not `y_axis`, per the colormap-axes feedback memory.)
- `z_axis()` → intensity. Unit from `meta`. Log by default. Label `"Flux [{unit}]"`.
- Title: `f"{spec.meta['instrument']} — {start_iso}"`.
- Theme: `SciQLopTheme.dark()` (no parent — double-ownership memory) inside a `try: from SciQLopPlots import SciQLopTheme except ImportError: pass` guard (theme-version memory).

For a `SpectrogramSequence` (LFR + HFR style two-receiver concatenation), the translator concatenates along time before plotting. Receivers with overlapping time ranges are stacked frequency-wise on the same plot.

On missing required fields, raises `RadioPlotError(source, reason)` — typed exception caught by the dock.

### `dock.py` — `RadioSpectraDock(QDockWidget)`

Layout:

```
+------------------------------------+
| [Source ▼]            [Open local…]|
| Start: [datetime]                  |
| End:   [datetime]      [Fetch]     |
|                        [Cancel]    |
+------------------------------------+
| Results:                           |
|  ☐ wi_l2_wav_20240501_v01.cdf      |
|  ☐ wi_l2_wav_20240502_v01.cdf      |
|  ...                               |
|                  [Plot selected]   |
+------------------------------------+
| Status: ready                      |
+------------------------------------+
```

Owns one `RadioFetchService`. Pure signal wiring; no domain logic. On "Plot selected", iterates selected rows → `reader.open_spectrogram(path)` → `plot.spectrogram_to_plot(spec)` → adds the plot to the SciQLop main window's central plot area.

### `settings.py` — `RadioSettings(ConfigEntry)`

```python
class RadioSettings(ConfigEntry):
    category: ClassVar[str] = "PLUGINS"
    subcategory: ClassVar[str] = "Radio Spectra"
    cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "sciqlop_radio")
    download_timeout_s: int = Field(default=60, ge=5, le=600)
    parallel_downloads: int = Field(default=4, ge=1, le=16)

    @field_validator("download_timeout_s", mode="before")
    @classmethod
    def _clamp_timeout(cls, v):
        try: return max(5, min(600, int(v)))
        except (TypeError, ValueError): return v

    # same clamping for parallel_downloads
```

Bounded numeric fields clamp on load (stale YAML must not crash the settings page).

## Data flow

### Flow 1 — Search + download + plot (headline)

```
dock.on_fetch_clicked()
  → fetch_service.search(source, t0, t1)
      [QThreadPool worker]
      → Fido.search(a.Time(t0,t1), a.Instrument(source.fido_instrument))
      → emit searchCompleted(rows) | searchFailed(msg)
  → dock populates result list

dock.on_plot_selected_clicked()
  → fetch_service.fetch(selected_rows)
      [QThreadPool worker]
      → for row in rows:
          if cache_hit(row): use cached path
          else: Fido.fetch(row, path=cache_dir)
          emit fetchProgress(i, total)
      → emit fetchCompleted(paths_ok, paths_failed)
  → for path in paths_ok:
      spec = reader.open_spectrogram(path)
      plot = plot.spectrogram_to_plot(spec, main_window)
      main_window.plot_area.add_plot(plot)
```

### Flow 2 — Local file (BYO files)

```
dock.on_open_local_clicked()
  → QFileDialog → path
  → spec = reader.open_spectrogram(path)
  → plot = plot.spectrogram_to_plot(spec, main_window)
  → main_window.plot_area.add_plot(plot)
```

### Flow 3 — Cache hit (silent)

Cache check happens inside `fetch_service.fetch` before any Fido call; cache hits go straight to the path list. Re-plotting a previously fetched row is network-free.

### Invariants

- The translator is the only module that imports SciQLop plotting types. `fetch.py` and `reader.py` speak only in `Path` and `Spectrogram`.
- Nothing on the GUI thread blocks. Search and fetch are async via Qt signals; reads are sync but small.
- One plot per spectrogram in the MVP. The translator returns a `SciQLopPlot`, which is composable for future stacking.

## Error handling

- `search` failure → `searchFailed(message)`; dock shows status-line message, clears result list.
- `fetch` per-file failure → batch continues; failures emitted alongside successes; dock shows "N of M downloaded" with a "Last error" expander (no modal).
- `reader.open_spectrogram` failure → caught per-file in the dock; other files still plot.
- Translator failure → `RadioPlotError(source, reason)` caught in the dock and surfaced like a fetch error.

## Threading model

- All Fido work runs in `QThreadPool` workers via `QRunnable`.
- Signals use `Qt.QueuedConnection` to land on the GUI thread.
- No `asyncio` / `qasync` interaction — radiospectra/Fido are sync and stay sync.
- Cancellation via `threading.Event` `cancel_token`, checked between files.

## Testing strategy

### Unit tests (no Qt, no network)

- `test_sources_registry.py` — every `RadioSource` has non-empty `key` + `label`; either `fido_instrument` or `accepts_local=True`; keys are unique. Parametrized over `SOURCES`.
- `test_plot_translator.py` — synthetic `Spectrogram`-shaped object (numpy arrays + dict meta). Assert:
  - frequencies land on `y2_axis()` with the right unit and log/lin flag
  - data lands on `z_axis()` with the right unit and log/lin flag
  - x-axis label is `"UTC"`
  - single-receiver and 2-receiver concatenation both work
  - missing `times`/`frequencies`/`data` → raises `RadioPlotError`
- `test_reader.py` — uses tiny committed sample files (one WIND/WAVES CDF, one eCallisto FIT) under `tests/data/`. Verifies `open_spectrogram` returns non-empty data.

### Qt-integration tests (`pytest-qt`, no network)

- `test_dock.py` — instantiates `RadioSpectraDock` with an injected fake `RadioFetchService` that emits canned signals. Asserts: result list populates, plots are added to a stub plot-area, error states render in the status line.

### Network tests (opt-in)

- `test_fetch_live.py` — one test per source, hits real archives with a known-good 1-hour window. Skipped unless `RADIO_LIVE_TESTS=1`. Catches upstream regressions; doesn't gate normal PRs.

### Conftest

- Root monorepo `conftest.py` already stubs Qt modules for non-Qt tests.
- `sciqlop_radio/tests/conftest.py` adds the `atexit.register(lambda: os._exit(0))` session fixture (SciQLopPlots exit-segfault memory).

### TDD shape

Translator and registry tests written before implementation. Dock test follows once the fake-service interface is settled. Reader test added when sample files are in tree.

## Future expansion (not in MVP)

1. **Multi-instrument stacked synoptic view** — extend dock to accept multiple sources and render stacked panels sharing one time axis.
2. **Instruments outside `radiospectra`** — NDA Stokes I/V, ORFEES, MWA dynamic spectra, NenuFAR. Each becomes a new `RadioSource` whose `fido_instrument` is `None` and whose `reader.open_spectrogram` branch reads the native format. At that point, promoting the translator's input to a small `RadioSpectrogram` Pydantic model becomes worthwhile.
3. **Speasy `MaserProvider`** — separate effort in Speasy; once landed, `sciqlop_radio` gains a Speasy-backed source row "for free".
4. **Contribute back to SunPy** — if the `RadioSpectrogram` model proves useful, upstream it as the workshop's container abstraction.

## Risks and open questions

- **SciQLop main-window plot-area API** — exact method to add a plot to the central area depends on the current `SciQLop >= 0.12` API surface. To be confirmed in the implementation plan against the installed SciQLop version.
- **`radiospectra` API stability** — pin to `radiospectra >= 1.0`; live tests act as the canary for upstream drift.
- **`SpectrogramSequence` concatenation correctness** — multi-receiver overlap handling needs verification against real RPW LFR+HFR files; covered by `test_reader.py` once a real LFR+HFR pair is in `tests/data/`.

## Dependencies

| Package | Version | Why |
|---|---|---|
| `SciQLop` | `>= 0.12` | Plugin entry-point + `core.plot_hints` available |
| `sunpy` | `>= 6.0` | Fido + radiospectra compatibility |
| `radiospectra` | `>= 1.0` | The 9 built-in sources |
| `astropy` | (transitive) | radiospectra dependency |
| `numpy` | `>= 1.24` | array work in the translator |
| `pydantic` | `>= 2.0` | `RadioSource`, `RadioSettings` |
