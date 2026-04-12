# MSA Live Smoothing Demo — Design

**Date:** 2026-04-12
**Plugin:** `sciqlop_msa`
**Purpose:** Demo feature for the BepiColombo meeting (2026-04-13). Showcases SciQLop's
unique combination of live Speasy data + Python processing + GUI knobs by letting an
audience drag sliders and watch L1 count spectrograms re-smooth in real time.

## Goal

Add a "Live Smoothing Demo" entry to the MSA plugin that:

1. Registers four virtual spectrogram products that wrap the L1 corrected count
   spectrograms (`h_plus`, `alphas`, `heavies`, `total`) and apply a 2D Gaussian filter.
2. Opens a dock widget with three controls — `σ_time`, `σ_energy`, and a
   "log-space smoothing" toggle — that drive the filter parameters.
3. Refreshes the active panel in real time as sliders move.

The narrative for the talk: *"Five-line plugin, your data, your filter, no file
handling. Same hook lets you drop in despiking, background subtraction, or anything
else without touching SciQLop core."*

## Non-goals

- No physics claims. We are smoothing, not calibrating, denoising, or recomputing
  moments. The spec deliberately avoids any moment-recomputation path so there is
  nothing to defend on stage.
- No new dependencies beyond `scipy` (already a transitive dep of speasy in
  practice, but we declare it explicitly).
- No persistence of slider state between sessions.
- No support for arbitrary user-supplied filters in this iteration.

## Data we are smoothing

The existing `quicklooks.py` already references the four L1 corrected count
spectrograms:

```
speasy/archive/BepiColombo/MSA/L1_Low_ECounts_Moments_TOF/bc_mmo_mppe_msa_l1_l_ecounts_moments_tof/{h_plus,alphas,heavies,total}_counts_corrected
```

These are the only MSA data we currently have cached, and they cover the demo
interval `2025-01-08 01:38:50 — 17:27:23 UTC`. The same interval and same products
are used for the smoothing demo so the audience can see the existing "L1 Count
Spectrograms" quick-look first, then the smoothed version side-by-side.

## Architecture

Three new files under `sciqlop_msa/sciqlop_msa/`, plus wiring in `plugin.py`:

```
sciqlop_msa/
├── plugin.py            # registers virtual products + dock + menu entry
├── quicklooks.py        # existing, unchanged
├── realtime.py          # NEW — pure smoothing function
└── realtime_dock.py     # NEW — QDockWidget with the sliders
```

### `realtime.py` — the smoothing function

Single pure function, easy to unit-test, no Qt and no SciQLop imports:

```python
def smooth_spectrogram(
    var: SpeasyVariable,
    sigma_t: float,
    sigma_e: float,
    log_space: bool,
) -> SpeasyVariable:
    """Return a copy of `var` with values 2D-Gaussian-smoothed.

    Smoothing is applied along (time, energy) axes. When `log_space` is True,
    smoothing is performed on log10(values + 1) and then exponentiated back —
    this gives visually nicer results on Poisson-distributed counts.
    """
```

Implementation notes:
- Uses `scipy.ndimage.gaussian_filter` with `sigma=(sigma_t, sigma_e)`.
- `sigma_t == 0 and sigma_e == 0` short-circuits to a copy of the input
  (no-op so the slider zero point shows the raw spectrogram).
- NaNs in the input are preserved by zero-fill smoothing followed by mask
  reapplication. (MSA L1 counts shouldn't contain NaNs in practice but we
  guard against it cheaply so the demo can't blow up on stage.)
- Returns a `SpeasyVariable` with the same axes and metadata as the input,
  only `values` replaced.

### `realtime_dock.py` — the control dock

A `QDockWidget` containing:
- `QSlider` "σ time" — integer 0..10, displayed as the current value.
- `QSlider` "σ energy" — integer 0..5, displayed.
- `QCheckBox` "log-space smoothing".

The dock owns a single `dict` of current parameter values:

```python
{"sigma_t": 0.0, "sigma_e": 0.0, "log_space": False}
```

This dict is the shared mutable state — all four virtual product callbacks
read from it via closure.

On any control change, the dock:
1. Updates the dict.
2. Calls a `refresh_callback` provided by the plugin, which forces a refresh
   on the currently active plot panel.

The dock exposes:
- `params: dict` — the live parameter dict (read-only externally; mutated
  internally only).
- `set_refresh_callback(fn)` — wires the slider→panel refresh.

### Wiring in `plugin.py`

In `MSAPlugin.__init__`:

1. Construct the dock and add it to the main window via `addDockWidget`.
2. For each of the four count products, build a closure that captures the
   product path and the dock's params dict, then register a virtual
   spectrogram via `create_virtual_product`. The virtual products live under
   `MSA/Smoothed/{name}_counts`.
3. Add a new "Live Smoothing Demo" entry to the existing MSA toolbar menu.
   When clicked, it creates a plot panel pre-loaded with the four smoothed
   products on the same time interval as the existing quick-looks, then sets
   the dock's refresh callback to a function that forces a refresh on that
   panel.

The closure pattern:

```python
def make_callback(product_path: str, params: dict):
    def callback(start: float, stop: float):
        raw = speasy.get_data(product_path, start, stop)
        if raw is None:
            return None
        return smooth_spectrogram(
            raw,
            sigma_t=params["sigma_t"],
            sigma_e=params["sigma_e"],
            log_space=params["log_space"],
        )
    return callback
```

`cacheable=False` (the default) so each refresh re-runs the function — this
is exactly what we want for slider-driven recomputation.

### Forcing the refresh

`PlotPanel.time_range` setter (in SciQLop's user_api) unconditionally calls
`set_time_axis_range`, which triggers a re-fetch of all plotted products.
The refresh callback is therefore:

```python
def refresh():
    panel.time_range = panel.time_range
```

If a no-op short-circuit turns out to live downstream, fallback is to nudge
by 1 ns:

```python
tr = panel.time_range
panel.time_range = TimeRange(tr.start() + 1e-9, tr.stop())
```

We will verify which works during smoke-testing.

## Data flow

```
Slider moves
    │
    ▼
Dock updates params dict
    │
    ▼
Dock calls refresh_callback()
    │
    ▼
Panel.time_range = Panel.time_range
    │
    ▼
SciQLop re-requests data for each plotted virtual product
    │
    ▼
Each virtual product callback runs:
    speasy.get_data(L1 counts)  →  smooth_spectrogram(...)  →  SpeasyVariable
    │
    ▼
Spectrograms re-render
```

The Speasy `get_data` call hits the local cache (pre-warmed the night before
the demo), so each refresh is bounded by the smoothing cost — `gaussian_filter`
on a `~14000 × 64` array, well under 100 ms.

## Testing

Unit tests for `realtime.py` only (`tests/test_realtime.py`):

- `smooth_spectrogram` with `sigma_t=0, sigma_e=0` returns values equal to the input.
- `smooth_spectrogram` with `sigma_t=2, sigma_e=0` reduces variance along the time
  axis (compare `np.var` before/after on a noisy synthetic input).
- `smooth_spectrogram` with `log_space=True` on a non-negative input returns a
  non-negative output with the same shape, and matches a hand-computed
  `10**(gaussian_filter(log10(x+1))) - 1` on a small fixture.
- NaN inputs produce non-NaN outputs in the non-NaN regions.

The dock and the plugin wiring are not unit-tested — they require a running
SciQLop main window and the existing `conftest.py` already stubs Qt for the
unit-test layer. They are validated by the smoke test on stage one (see below).

## Pre-demo smoke test (the night before)

1. Pre-warm the Speasy cache for the demo interval by triggering the existing
   "L1 Count Spectrograms" quick-look once.
2. Run "Live Smoothing Demo" from the MSA menu — verify the four smoothed
   spectrograms appear.
3. Drag each slider end-to-end — verify spectrograms re-render within ~100 ms
   per change.
4. Toggle log-space — verify visible difference and no exceptions.
5. Pan the time axis — verify smoothing is reapplied to the new window.

## Safety / fallbacks

- If the slider→refresh path proves flaky on stage, the existing
  "L1 Count Spectrograms" quick-look still works and the "Live Smoothing Demo"
  entry can be skipped silently.
- The smoothing function is defensive against NaN and zero-sigma to avoid
  any chance of an exception during a live drag.
- We do **not** modify any existing file behavior — `quicklooks.py`,
  `inventory.yaml`, and the existing menu entries are untouched. The demo is
  purely additive.

## Out of scope (explicit, to keep tomorrow's risk down)

- Live moment recomputation.
- Background subtraction with calibration tables.
- Despiking, sigma-clipping, or any other filter family.
- User-defined filter selection from the dock.
- Smoothed-vs-raw side-by-side in the *same* plot (would require a second
  panel layout we don't currently template).
- Any change to `cdf_workbench`.
