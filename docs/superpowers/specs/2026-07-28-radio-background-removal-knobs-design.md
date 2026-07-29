# Background-removal knobs on the radio virtual products — design

**Date:** 2026-07-28
**Repo:** `plugins_sciqlop` / `sciqlop_radio`
**Depends on:** `SciQLop.user_api.dsp.background_subtract` (already merged in SciQLop `d0d23217`,
backed by `column_percentile` / `rolling_percentile` in SciQLopPlots `59f0a1f`)

## Goal

Let a user remove the per-channel receiver background from any radio spectrogram the plugin
serves, from the plot inspector, without re-registering a product or writing code.

The visible symptom this addresses: I-LOFAR and e-Callisto dynamic spectra are dominated by the
receiver bandpass — a saturated band across part of the frequency range that flattens the colour
scale and hides real emission. Dividing out a per-channel background collapses the per-channel
spread of the time-average from 4.3e7 to 0.31 dB on real I-LOFAR data.

## Decision record

The backend was built first and the UX deliberately left open. Three options were on the table:

- **(a) Knobs on the existing radio VPs** — chosen.
- (b) Derived virtual products (`radio/ilofar/X (bg-subtracted)`) — composable and stackable with
  the raw product, but doubles fetch cost without a shared cache.
- (c) Display-time colormap layer — best interactivity, biggest build, fights the resampler.

(a) was chosen because `lofar.py` already carries working `Beam`/`SAP` knobs to copy, and because
the transform is a pure function of `(x, y)` — (b) remains cheap to add later on top of this.

Scope decision: **all continuous sources plus the LOFAR LBA product.** Knob surface: **three
knobs** — mode, window, percentile. `gap_factor` stays at its default and is not user-facing.

## Architecture

One new module, `sciqlop_radio/background.py` (~80 lines), holding the knob annotation aliases and
a single `apply_background()` function. Both existing callbacks import the aliases at module top
level and call the function on their result.

No numerics live in the plugin. It delegates to `SciQLop.user_api.dsp.background_subtract`,
following the placement rule established during the backend design:

- generic spectrogram operations → `SciQLop.user_api.dsp`
- hot generic numerics → `SciQLopPlots/DSP`
- **only instrument and display policy → `sciqlop_radio`**

### The module-globals trap

`Knob` must be imported at the top of `background.py`, with the headless `ImportError` fallback
stub `lofar.py` already demonstrates. The annotation aliases must in turn be imported at the top
of `continuous.py` and `lofar.py`.

SciQLop introspects callbacks in two independent places, and both resolve stringified annotations
in the **defining function's module globals**. Under `from __future__ import annotations`, a
parameter annotated `bg_mode: BgMode` stringifies to `"BgMode"`, and that name is looked up in
`callback.__globals__` — i.e. in `continuous.py`, not in `background.py`. A lazy import inside the
factory function is invisible to both lookups.

Neither failure is loud, which is why this needs a test rather than vigilance:

- `extract_specs_from_callback` (`SciQLop/core/knobs/introspection.py:131-134`) calls
  `get_type_hints(callback, include_extras=True)` and swallows the `NameError` into `hints = {}`.
  It then falls back to the raw string annotation, which matches no spec branch, so
  `_spec_from_kwarg` returns `None` and **the knob simply never appears in the UI**.
- `_positional_args_types` (`SciQLop/components/plotting/backend/easy_provider.py:52-57`) calls
  `signature(callback, eval_str=True)` and on `NameError` retries without `eval_str`. Every
  annotation is then a string, so `start: float` no longer matches `float`, `_arguments_type`
  degrades to `ArgumentsType.Unknown`, and the provider emits a "missing type hints" warning and
  assumes float. That assumption is correct for these callbacks, so the visible cost is the
  warning — but it is the same root cause and disappears with the same fix.

## The knobs

Declared once in `background.py`, reused by both callbacks:

```python
BgMode   = Annotated[Literal['off', 'diff', 'ratio', 'db'], Knob(label="Background")]
BgWindow = Annotated[float, Knob(min=0.0, max=86400.0, step=1.0, unit="s", label="BG window")]
BgQ      = Annotated[float, Knob(min=0.0, max=100.0, step=1.0, unit="%", label="BG percentile")]
```

`Literal` gives SciQLop a `ChoiceKnob` for free (`introspection.py:85-88`) while the `Knob` marker
supplies the label — `_split_annotation` returns the `Literal` base and the marker separately, and
the `Literal` branch is reached before the marker's own `choices` branch.

| Knob | Type | Default | Meaning |
|---|---|---|---|
| `bg_mode` | choice | `'off'` | `off` \| `diff` \| `ratio` \| `db`. One knob does enable + mode. |
| `bg_window_s` | float, seconds | `0.0` | `0` = one constant background over the whole view; `>0` = sliding window of that duration. |
| `bg_q` | float, percent | `50.0` | Estimator percentile. 50 = median; 5–10 when bursts fill much of the view. |

`bg_mode='off'` is the default, so nothing changes for existing users until they touch a knob.

**Window is in seconds, not samples — deliberately.** I-LOFAR runs at 1 s cadence and e-Callisto at
0.25 s, so a sample count means something different per product; a shared default would be a silent
4x error. Seconds are instrument-independent, and this sidesteps the `np.timedelta64`-is-an-`np.integer`
trap in `resolve_window` entirely: the plugin only ever constructs `np.timedelta64` or passes `None`.

## Data flow

**`continuous.py`** — `_build_callback` widens its returned callback to:

```python
def _callback(start, stop, bg_mode: BgMode = 'off',
              bg_window_s: BgWindow = 0.0, bg_q: BgQ = 50.0):
```

The transform is applied to `out` after `_concat_spectrograms`, before the `counter()` call and
return. Because `make_stream_source` builds its `ContinuousSource` for the same `_build_callback`,
every dock-built e-Callisto/RSTN stream inherits the knobs with no extra work — the registry
entries and the dock-built streams share one code path.

**`lofar.py`** — `lofar()` gains the same three parameters after `beam`/`sap`, and applies the
transform to `result` after `merge`.

Both VPs register with `out_of_process=True`, so the ~0.3 s the sliding percentile costs at LOFAR
scale (3565×488, float32) runs in SciQLop's remote worker process, not on the GUI thread. The
transform re-runs on every pan; that is the accepted cost of option (a).

## Display policy

Both radio metadata dicts declare `SCALETYP: "log"`. That is wrong for every background mode:
`diff` output contains negatives, and `db` is already logarithmic. `apply_background` therefore
sets `SCALETYP='linear'` on the returned variable's meta whenever it transforms.

**Corrected after implementation** (the original draft of this section overstated the effect):
that override is read back by `hints.py`'s `plot_hints_from_variable` →
`variable_as_istp_meta` → `istp_metadata_to_hints` **only on the in-process path**. Every radio
VP registers with `out_of_process=True`, and
`SciQLop/components/plotting/ui/time_sync_panel.py:666-676` returns on the `is_remote` branch
without ever reaching `_post_plot`, so plot hints are never constructed for a remote graph;
the remote protocol transports handles and layout metadata only, so `out.meta` never leaves the
worker process. On the default remote path the override is therefore inert — harmless, because
the remote z-axis is already linear by default. Keep the assignment: it is what makes
`out_of_process=False` correct, and it is what the tests exercise.

`background_subtract` already handles `UNITS` via its `meta_overrides` (`''` for ratio, `'dB'` for
db, untouched for diff). Only the scale type is the plugin's business.

## Error handling

`apply_background` never raises. A bad knob value must degrade to an unprocessed plot, never a
blank one.

| Input | Behaviour |
|---|---|
| `mode == 'off'` | Return the input object unchanged — identity fast path, zero cost. |
| `variable is None` | Return `None`. |
| Non-2-D variable | Return unchanged, log a warning. |
| Any exception from `dsp` | Log a warning, return the **raw** variable. |

`SciQLop.user_api.dsp` is imported lazily inside the function — it is a runtime call, not an
annotation, so the module-globals trap does not apply, and headless plugin tests without a SciQLop
install still import `background.py` cleanly.

## Testing

TDD, headless, no network — the existing plugin suite's fakes cover this.

1. `mode='off'` returns the identical object (`is` identity, not just equality).
2. Each of `diff` / `ratio` / `db` preserves shape and both axes, and sets `UNITS` / `SCALETYP`
   correctly.
3. `window_s=0` vs `window_s>0` produce measurably different output on synthetic data carrying a
   drifting background.
4. **Knob-introspection regression test:** `extract_specs_from_callback(cb)` returns exactly the
   three specs, with the right types, defaults and bounds. This is what catches the
   module-globals trap if someone later moves an import. Skipped when SciQLop is not importable.
5. Degenerate inputs — a 1-D variable, and a `dsp` call forced to raise — return the raw variable
   and log, without propagating.
6. Existing `continuous.py` / `lofar.py` callback tests pass unchanged: the widened signature is
   default-compatible.

Followed by a real-data check against the cached I-LOFAR BST files in `~/.cache/sciqlop_radio/`
(`20250726_*_bst_00X.dat`, 3565×488, 1 s cadence, ascending 10.5–244.5 MHz with real inter-band
gaps), confirming the per-channel spread of the time-average collapses as it does when
`background_subtract` is called directly.

## Out of scope

- `gap_factor` — stays at 3.0, not user-facing. It is a segmentation-tuning detail users have no
  intuition for.
- Caching the transform across pans. Option (a) accepts the re-run cost; a shared cache is what
  option (b) would need.
- Option (b) derived virtual products. Cheap to add later — the transform is a pure function.
- RFI channel flagging, median rebinning, and Stokes I from the I-LOFAR X/Y pair. All still
  deferred; see the radiospectra integration handover.
