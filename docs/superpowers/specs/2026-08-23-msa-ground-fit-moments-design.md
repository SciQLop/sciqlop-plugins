# MSA Ground-Fit Moments — Design

**Date:** 2026-08-23
**Plugin:** `sciqlop_msa`
**Purpose:** Integrate the internship (Diane Kara Youssef, supervised by Lina Hadid, LPP,
summer 2026) ground-based spectral-fit moment method into `sciqlop_msa`, so density and
temperature can be computed from MSA L2pre energy-flux spectra and plotted like any other
SciQLop product. Source material: `~/Documents/Stages/2026/MSA Moments Lina/` (report +
`Deuxversions (1).ipynb`).

## Why this exists

The onboard-computed MSA moments are unusable for the whole flyby-era dataset we have
archived: L2pre's `h_plus_density`/`velocity`/`pressure` (and the alphas/heavies
equivalents) are empty arrays (`CAVEATS`: *"No valid moments data due to MSA flight
onboard computation misconfiguration"*), and the sibling L1 file's same variables are
populated but ~all zero/NaN (`CAVEATS`: *"data with energy range above 5Kev are
discarded"*). The intern's fit-based method — converting `diff_dir_en_flux_*` to phase-
space density and fitting a Maxwellian core + Kappa suprathermal halo — is currently the
only way to get density/temperature out of MSA data for this mission phase.

## Goal

1. Register virtual products for density, core temperature, and effective temperature,
   per species, computed by fitting each energy spectrum on demand.
2. Reuse the existing Speasy archive inventory (`sciqlop_msa/inventory.yaml`) rather than
   hand-rolling CDF downloading.
3. Fix what's rough in the intern's notebook along the way: two divergent copies of the
   same physics, hardcoded local paths, manual per-spectrum-index overrides.

## Non-goals

- No velocity. The method only ever sees an energy spectrum (angle-integrated), so there
  is no directional information to recover a bulk velocity vector from — unlike the
  onboard `MomentCalc.c` pipeline, which has full angular resolution. This is a hard
  limitation of the physics, not a scope cut.
- No comparison-with-MIA/MEA plotting. Those instruments' data isn't in our archive (only
  `Bepi/msa/` exists at `sciqlop.lpp.polytechnique.fr/data/Bepi/`); the intern's MIA/MEA
  comparison used her own local text dumps. Revisit if/when that data is archived here.
- No `n_h`/`T_h`/`kappa`/`model`/`chi2` VPs in v1 — kept in the per-day cached fit result
  for later diagnostic use, not surfaced as products yet.
- No change to the existing L1/L2pre quicklook templates or `realtime.py`/`realtime_dock.py`
  smoothing demo.

## Species / mass table

`f(E) = m²/(2(qE)²)·F(E)` needs a single `(mass, charge)` per fitted channel. Two of the
four `diff_dir_en_flux_*` channels are unambiguous; two mix species of different mass and
use a documented proxy:

| Species (VP path segment) | CDF variable | A (amu) | q | Status |
|---|---|---|---|---|
| `h_plus` | `diff_dir_en_flux_h_plus` | 1.00728 | 1 | exact |
| `alphas` | `diff_dir_en_flux_alphas` | 4.0026 | 2 | exact |
| `heavies` | `diff_dir_en_flux_heavies` | 16 | 1 | **approximation** — O+ proxy, dominant heavy species per the report |
| `total` | `diff_dir_en_flux_total` | 1.00728 | 1 | **approximation** — proton-equivalent, conventional for omni-flux-derived density |

```python
# simplify: heavies/total mix species of different mass; there is no single correct
# (A, q) for the m²/(2(qE)²) conversion. Density values for these two channels are
# approximate by construction. Upgrade path: per-species heavy-ion breakdown, if MSA
# ever ships one, replaces the O+ proxy with a real per-species fit.
SPECIES_MASS_TABLE = {
    "h_plus":  (1.00728, 1),
    "alphas":  (4.0026, 2),
    "heavies": (16.0, 1),
    "total":   (1.00728, 1),
}
```

Each affected VP's description states the approximation explicitly (not just a code
comment) so it's visible from the product tree.

## Architecture

Four new modules under `sciqlop_msa/sciqlop_msa/`, plus wiring in `plugin.py` and a new
`quicklooks.py` template:

```
sciqlop_msa/
├── plugin.py            # existing, + moments_vp registration call
├── quicklooks.py         # existing, + "L2pre Ground Moments (Fit)" template
├── moments_fit.py        # NEW — pure physics, no SciQLop/Speasy imports
├── moments_source.py     # NEW — per-species, per-day fetch + masking
├── moments_compute.py    # NEW — day-bucketed cached fit orchestration
└── moments_vp.py         # NEW — virtual product registration
```

### `moments_fit.py` — pure physics

Unifies the intern's two notebook cells (`cdflib`-based 3-model selector, `pyistp`-based
single-model fitter) into one implementation, matching the report's validated method:

```python
def flux_to_f(E_eV, F, A, q) -> np.ndarray: ...
def f_maxwell(E_eV, n_cc, T_eV, A) -> np.ndarray: ...
def f_kappa(E_eV, n_cc, T_eV, kappa, A) -> np.ndarray: ...

def fit_max_kap(Eg, fg, energie, f_obs, mask, A, q) -> FitResult | None: ...
def fit_2max(Eg, fg, energie, f_obs, mask, A, q) -> FitResult | None: ...
def fit_2max_kap(Eg, fg, energie, f_obs, mask, A, q) -> FitResult | None: ...
def best_fit(Eg, fg, energie, f_obs, mask, A, q) -> FitResult | None: ...  # lowest reduced chi²

def effective_temperature(params: dict) -> float: ...  # density-weighted Σ(n_i·T_i)/Σn_i
```

`FitResult` is a small dataclass: `n_tot`, `T_c`, `T_eff`, `model` (`"max_kap"` / `"2max"`
/ `"2max_kap"`), `chi2`, plus the raw per-population params (`nc`, `Tc`, `nh`, `Th`,
`kappa`, …) for later diagnostics. `scipy.optimize` `RuntimeError`/`ValueError` are caught
specifically per model attempt — not a blanket `except:` — and a failed model attempt
contributes `None` to the candidate list `best_fit` chooses from, exactly like the
intern's `meilleur_fit`.

No SciQLop/Speasy import in this file — fully unit-testable against synthetic spectra.

### `moments_source.py` — per-species, per-day fetch

```python
def fetch_day(species: str, day: date) -> DaySpectra | None:
    """Fetch diff_dir_en_flux_<species> for one UTC day via speasy.get_data(),
    mask FILLVAL, apply the noise-flux threshold. Returns None if speasy has no
    data for that day (day not in an archived flyby window)."""
```

`speasy.get_data("archive/BepiColombo/MSA/L2pre_Low_EFlux_Moments_TOF/.../diff_dir_en_flux_<species>", day_start, day_end)`
already handles archive file discovery, HTTP fetch/caching (`.netrc`-authenticated), and
multi-file stitching — no hand-rolled CDF downloading. The returned `SpeasyVariable`'s
`axes[1]` is the energy table (`energy_table_mass`, attached automatically by Speasy's
ISTP codec via the variable's `DEPEND_1`), so no separate energy-table fetch is needed.

`DaySpectra` bundles `time` (epoch array), `energy` (1D, shared across records), `flux`
(2D, records×64), post-FILLVAL-masking and post-threshold-masking (`SEUIL = 1e5
eV/cm²/s/sr/eV`, a module constant, not per-index overrides).

**Quality-flag filtering is Phase 2** (see below) — not implemented in this file yet.

### `moments_compute.py` — cached fit orchestration

```python
@CacheCall(cache_retention=timedelta(days=30), is_pure=True)
def fit_day(species: str, day: date) -> DayFits | None:
    """For one species/day: fetch_day() then moments_fit.best_fit() per record.
    Returns arrays of (time, n_tot, T_c, T_eff, model, chi2) aligned to the day's
    Epoch. Cached because the curve_fits are the expensive, deterministic step."""
```

Day-bucketed caching (not file-signature-based, since file resolution is now Speasy's
job) mirrors `sciqlop_radio`'s day-bucketed search cache — flybys are 1-2 days of data,
so this is a natural, simple granularity. A VP callback for an arbitrary `[start, stop)`
window calls `fit_day` once per UTC day overlapping the window, concatenates, and slices
to the exact requested range — the same "cache at fixed granularity, slice on read"
pattern `feedback_continuous_virtual_products.md` documents for exactly this reason
(caching keyed by an arbitrary pan/zoom range never hits).

### `moments_vp.py` — virtual product registration

```python
FIELDS = ["density", "T_c", "T_eff"]  # v1 scope; no velocity (see Non-goals)

def register_moments_vps():
    from SciQLop.user_api.virtual_products import create_virtual_product, VirtualProductType
    for species in SPECIES_MASS_TABLE:
        for field in FIELDS:
            create_virtual_product(
                f"msa/moments_fit/{species}/{field}",
                _make_callback(species, field),
                VirtualProductType.Scalar,
                labels=[field],
            )
```

12 VPs total (4 species × 3 fields). Callback signature `(start: float, stop: float) ->
SpeasyVariable | None`, returns a `SpeasyVariable` (not a bare tuple) with
`meta["UNITS"]`/`meta["LABLAXIS"]` set (`cm^-3` for density, `eV` for temperatures) so
plot hints auto-apply per the standard VP path. `plugin.py`'s `load()` calls
`register_moments_vps()` alongside the existing `install_inventory()` /
`rebuild_speasy_inventory()` calls, and keeps a module-level reference to the returned
`VirtualProduct` objects (SciQLop holds them weakly).

### `quicklooks.py` — new template

A "L2pre Ground Moments (Fit)" entry alongside the existing three templates, plotting
`density` for all four species plus `T_eff` for `h_plus`, matching the existing
templates' style (list of product paths, same default time window).

## Quality/noise handling — phased

**Phase 1 (this implementation):** flat flux threshold only (`SEUIL = 1e5`), same
noise cutoff the intern used, now a module constant instead of a per-flyby manual
`sans_debruit`/`corr_manuelles` index list. No `quality_level`/`quality_bitmask` use yet.

**Phase 2 (fast-follow, gated on SciQLop pinning `speasy>=1.8`):** `quality_level` and
`quality_bitmask` are `VAR_TYPE='support_data'` in the L2pre CDF, on a different time
grid (`Epoch_1`, 8288 records) than the flux products (`Epoch`, 517 records) — and
Speasy's archive provider today only exposes `VAR_TYPE='data'` variables as gettable
products, via `pyistp.data_variables()`-driven inventory discovery. That's fixed in
speasy ≥1.8 (confirmed by reading the local `~/Documents/prog/speasy` checkout at
`v1.8.0.dev0-17-ga27d2f5b`, not yet on PyPI): a codec's `list_variables(file)` now drives
`master_file`/`master_cdf` discovery instead of the old hardcoded data-only filter, and a
custom `CodecInterface` can be registered and selected per dataset via a `codec:` YAML
field.

Phase 2 adds:
- `sciqlop_msa/codec.py` — a small codec (`list_variables`/`load_variables` reading any
  named CDF variable via `pycdfpp`, not filtered to `VAR_TYPE='data'`), registered via
  `register_codec` at plugin load.
- `codec: msa_l2pre_full_cdf` added to the relevant `inventory.yaml` entries, making
  `quality_level`/`quality_bitmask` normal gettable Speasy products.
- `moments_source.fetch_day` additionally fetches those two, nearest-time-aligns them
  (`Epoch_1` → `Epoch`), and excludes records where `quality_level` indicates bad data or
  `quality_bitmask` has SWEEP OFF set — replacing the flat threshold as the primary
  filter (the flux threshold likely stays as a secondary guard).

**2026-09-01 update: speasy>=1.8 landed, and Phase 2 is now blocked on archive data
instead.** Speasy 1.8.0 is released and installed (not an editable dev checkout); the
codec mechanism above was re-verified against the real package (`register_codec`,
`CodecInterface`, `codec:` YAML field, `get_codec(codec_id).list_variables()` driving
non-ISTP inventory discovery, `get_product(codec=...)` driving per-fetch loads) and works
exactly as designed. The `ProductsModel` Qt-static crash risk noted below did not
reproduce against the released 1.8.0 (plain `import speasy` succeeds cleanly).

But `quality_level`/`quality_bitmask` — the two variables Phase 2 was designed to
filter on — are **100% `FILLVAL`, archive-wide**. Checked every L2pre flyby currently
served (2021-10-01, 2022-06-22, 2023-06-19, 2024-09-04, 2025-01-08) plus their L1
siblings: zero real values across ~58,000 combined records. No other per-record quality
indicator exists in either CDF level (checked every variable name for `qual`/`flag`/
`status`/`valid`/`sweep`/etc.) — the only real hit is `spoiler_state` (mostly `0`, some
`255` fill, one out-of-VALIDMAX-range `18`), an instrument-mode variable whose meaning
for data validity isn't documented in the CDF and isn't something to guess at.

**Decision (2026-09-01): Phase 2 is dropped, not deferred-and-blocked.** The codec
mechanism works and could be built in an afternoon, but there is nothing populated to
filter on — building it now would be dead plumbing. Phase 1's flat flux threshold
remains the only filter. Revisit only if LPP repopulates `quality_level`/
`quality_bitmask` in a future archive reprocessing, or if `spoiler_state`'s meaning for
data quality is clarified by the instrument team. See
[[msa_l2pre_onboard_moments_invalid]] for the full data-check record.

## Error handling

A spectrum where all 3 candidate models fail → `NaN` in that record's output arrays, not
a crash (matches `SpeasyVariable` gap semantics — SciQLop already renders NaN as a data
gap). `fetch_day` returning `None` for a day with no archived coverage propagates as a
gap in the VP's output for that sub-range, not an exception.

## Testing (TDD)

1. **`test_moments_fit.py` first** — the reproducer. Synthetic spectra built the same way
   the report validates its own method (§8.3): pure Maxwellian, Maxwellian+Kappa, and
   2-Maxwellian combinations with known `n`, `T`, `kappa`. Assert `best_fit` recovers
   `n_tot`/`T_c`/`T_eff` within tolerance, and picks the model family the synthetic
   spectrum was actually built from when there's a clear winner.
2. **`test_moments_source.py`** — `fetch_day` against a small synthetic `SpeasyVariable`
   (no network): FILLVAL masking, threshold masking, `None` on empty coverage.
3. **`test_moments_compute.py`** — `fit_day` composes `fetch_day` + `moments_fit` (mock
   `fetch_day`, real `moments_fit`); asserts the day-bucket cache key and output shape.
4. **`test_moments_vp.py`** — VP registration + one callback smoke test using the
   existing `SciQLop.*` stub pattern already present in the plugin's test setup (matches
   `sciqlop_radio`/`sciqlop_sismo` conftest conventions).

Real-archive access stays manual/exploratory (as with the rest of this plugin's tests),
not part of the automated suite. Phase 2's quality-flag alignment gets its own test file
(`test_moments_quality.py`) once the codec lands.

## Out of scope (explicit)

- Velocity moments (see Non-goals — not a cut, a physical limitation).
- MIA/MEA comparison plotting.
- `n_h`/`T_h`/`kappa`/`model`/`chi2` as VPs.
- Full automation of "which model won, and why" surfaced in the UI (report's own
  "Perspectives" section flags this as future work, not settled methodology).
- The `speasy` `ProductsModel` import crash — tracked as a known risk blocking Phase 2,
  not fixed here.
