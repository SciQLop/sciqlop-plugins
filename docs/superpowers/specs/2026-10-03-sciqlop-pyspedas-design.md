# sciqlop_pyspedas — MMS particle spectra (experimental) — design

Date: 2026-10-03. Status: approved in brainstorming, pending spec review.

## Goal

Experiment: bring pyspedas capabilities into SciQLop for users who work on
MMS, THEMIS and PSP data. First slice: **particle spectra derived from 3D
distributions** (energy, pitch-angle, gyrophase spectrograms), which Speasy
cannot provide.

Success: a user picks e.g. "FPI ions / pitch angle", sets probe and data
rate, and gets a correct spectrogram in a normal SciQLop panel that follows
the panel's time range — without the GUI freezing.

## Scope

In v1: **MMS only**, via `pyspedas.projects.mms.mms_part_getspec`
(pyspedas 2.2.0) — the only mission where pyspedas computes spectra from
distributions in one call (it loads distributions, B field and position
itself).

Out of scope, with reason (survey of pyspedas 2.2.0):

| Mission | Why not in v1 |
|---|---|
| ERG/Arase | `erg_*_part_products` take pre-loaded tplot vars; needs a hand-written load chain per instrument. Add on demand. |
| THEMIS | pyspedas has no port of `thm_part_products`. |
| PSP | pyspedas only loads SPAN L2/L3 files, whose spectra are already on CDAWeb → Speasy. |

## Architecture

Plugin directory `sciqlop_pyspedas/`, laid out like `sciqlop_radio`:

- `catalog.py` — data table: instrument/species entries (FPI `i`/`e`,
  HPCA `hplus`/`heplus`/`heplusplus`/`oplus`), their data rates, and the
  spectrum outputs (`energy`, `pa`, `gyro`).
- `getspec.py` — worker-side callback: range check → hourly split →
  cached per-hour compute → tplot→SpeasyVariable conversion → concat.
- `plugin.py` — `load()`: registers the virtual products with
  `out_of_process=True`.

pyspedas is imported **only inside the callback**, so its import cost and
its global tplot store live in SciQLop's remote worker, never in the GUI
process.

### Why the remote worker

SciQLop runs one worker process per plugin (keyed by the callback's
top-level module) with a single-threaded serve loop that coalesces stale
requests. Consequences:

- pyspedas's global `data_quants` store is private to the worker and never
  accessed concurrently → no lock, no tplot-name collisions.
- Long downloads never block the GUI.
- Requests to this plugin are serialized: a slow burst load delays the next
  pyspedas product (not Speasy products). Acceptable for an experiment.
- Callbacks must be cloudpickle-able: module-level functions, no closures
  over Qt objects.

### Product tree

One product per (instrument/species × spectrum); probe and data rate are
knobs:

```
pyspedas/MMS/
  FPI ions/        energy · pitch angle · gyrophase
  FPI electrons/   energy · pitch angle · gyrophase
  HPCA H+/ He+/ He++/ O+/   energy · pitch angle · gyrophase
knobs: probe [1-4], data_rate [fast|brst] (FPI) / [srvy|brst] (HPCA)
```

18 nodes. Spectrum type stays in the tree because users stack energy and
pitch-angle panels, each needing its own product.

## Data flow (per request, in the worker)

1. Receive `(start, stop, probe, data_rate)` for one product.
2. Reject if the range exceeds the cap (see Errors).
3. Split into 1-hour fragments.
4. Per fragment: cache hit, or run
   `mms_part_getspec(instrument, probe, species, data_rate, trange,
   output=['energy','pa','gyro'])` once, producing all three spectra.
5. Convert each tplot variable (`get_data` → times, values, axis + tplot
   options) to a SpeasyVariable with spectrogram plot hints (log z, log
   energy axis where applicable, units).
6. Concatenate fragments, return the requested spectrum.

## Caching

- **Disk:** Speasy `@Cacheable`, one entry per (product params, output,
  1-hour fragment) — same pattern as `sciqlop_sismo`.
- **Memory:** the worker memoizes the last `mms_part_getspec` result, so
  asking for energy right after pitch angle (same params, same fragment)
  costs no second compute.
- **Downloads:** pyspedas's own CDF cache, stored **in the SciQLop
  workspace**. Before importing pyspedas the worker sets
  `SPEDAS_DATA_DIR = $SCIQLOP_WORKSPACE_DIR/spedas_data` (files land in
  `<workspace>/spedas_data/mms/`). Works because SciQLop exports
  `SCIQLOP_WORKSPACE_DIR`, a workspace switch restarts the process, and the
  remote worker inherits `os.environ`. A user-set `MMS_DATA_DIR` still
  wins (pyspedas's own precedence) — right for shared mirrors.

## Errors

- **No data in a fragment:** return an empty SpeasyVariable, never `None`
  (a `None` from a Cacheable function leaves stale locks that hang other
  threads for 10 min).
- **Range too long:** raise a clear error before any download. Caps live in
  a `ConfigEntry` (clamped on load); starting defaults 6 h for fast/srvy,
  30 min for brst — tuned during the experiment. Fail loudly, never
  truncate.
- **pyspedas exceptions:** propagate out of the worker through SciQLop's
  remote error path.

## Dependencies

`pyspedas>=2.2,<3` in `plugin.json` `python_dependencies` and
`pyproject.toml`; `SciQLop>=0.13.0,<0.15.0` like radio (the remote worker
first shipped in v0.13.0).

## Testing

- Unit: tplot→SpeasyVariable conversion on synthetic arrays (shape, axis,
  units, hints); catalog table; range cap; hourly split; empty-fragment
  result.
- Callback test with `mms_part_getspec` monkeypatched (verifies one compute
  serves all three outputs).
- Opt-in live test (`-m live`): real 10-minute FPI burst interval.
- Visual: render a real panel to PNG and inspect it.
- Tests run with the SciQLop dev venv; conftest stubs `SciQLop.*` like
  radio/sismo.
