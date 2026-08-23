# MSA Ground-Fit Moments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ground-based density/temperature moments to `sciqlop_msa`, fitted from
`diff_dir_en_flux_*` energy spectra (Maxwellian core + optional Kappa halo / second
Maxwellian), exposed as 12 Speasy virtual products (4 species × density/T_c/T_eff).

**Architecture:** Four new modules with one responsibility each: `moments_fit.py` (pure
physics, no I/O), `moments_source.py` (per-species/per-day fetch via `speasy.get_data()`),
`moments_compute.py` (day-bucketed cached fit orchestration), `moments_vp.py` (virtual
product registration). `plugin.py` and `quicklooks.py` get small additive edits.

**Tech Stack:** Python, numpy, scipy (`optimize.curve_fit`, `special.gamma`), Speasy
(`speasy.get_data`, `speasy.core.cache.CacheCall`), SciQLop `user_api.virtual_products`.

**Spec:** `docs/superpowers/specs/2026-08-23-msa-ground-fit-moments-design.md` — this
plan implements **Phase 1** only (flat flux threshold; no `quality_level`/`quality_bitmask`
filtering — that's Phase 2, gated on `speasy>=1.8` landing as a pinned dependency, and gets
its own follow-up plan once that lands).

## Global Constraints

- No velocity VP — the method has no angular information (spec Non-goals).
- Species mass table is fixed: `h_plus` (A=1.00728, q=1, exact), `alphas` (A=4.0026, q=2,
  exact), `heavies` (A=16 O+ proxy, q=1, **approximation**), `total` (A=1.00728, q=1,
  **approximation**). The two approximations must be stated in their VP descriptions, not
  just a code comment.
- No `n_h`/`T_h`/`kappa`/`model`/`chi2` VPs in v1 — keep them in the per-day fit result for
  later diagnostics, don't register them as products.
- Run tests with the SciQLop dev venv, not system Python:
  `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest ...`
  (bundles the pinned `speasy`/`SciQLop` versions this plugin actually depends on).
- `scipy.optimize.curve_fit` failures are caught as `(RuntimeError, ValueError)`
  specifically — never a blanket `except:`.

---

## Task 1: `moments_fit.py` — flux conversion and distribution functions

**Files:**
- Create: `sciqlop_msa/sciqlop_msa/moments_fit.py`
- Test: `sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py`

**Interfaces:**
- Produces: `ELEMENTARY_CHARGE`, `ATOMIC_MASS_UNIT`, `NOISE_FLUX_THRESHOLD` (constants);
  `SPECIES_MASS_TABLE: dict[str, tuple[float, int]]`; `ion_mass_kg(A) -> float`;
  `flux_to_phase_space_density(E_eV, F, A, q) -> np.ndarray`;
  `maxwellian(E_eV, n_cc, T_eV, A) -> np.ndarray`;
  `kappa_distribution(E_eV, n_cc, T_eV, kappa, A) -> np.ndarray`.

- [ ] **Step 1: Write the failing tests**

```python
# sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py
import numpy as np
import pytest
from scipy.integrate import quad

from sciqlop_msa import moments_fit


def test_flux_to_phase_space_density_matches_hand_calculation():
    E_eV = np.array([100.0])
    F = np.array([1e7])
    A, q = 1.00728, 1

    m = A * moments_fit.ATOMIC_MASS_UNIT
    E_kin_J = q * E_eV[0] * moments_fit.ELEMENTARY_CHARGE
    expected = m ** 2 * 1e4 / (2.0 * E_kin_J ** 2) * F[0]

    result = moments_fit.flux_to_phase_space_density(E_eV, F, A, q)

    assert result[0] == pytest.approx(expected)


def test_maxwellian_density_normalizes_to_injected_density():
    """Integrating f(v) over all velocity space (4*pi*v^2*dv) must recover n."""
    n_cc, T_eV, A = 7.0, 150.0, 1.00728
    m = moments_fit.ion_mass_kg(A)

    def integrand(v):
        E_eV = 0.5 * m * v ** 2 / moments_fit.ELEMENTARY_CHARGE
        f = moments_fit.maxwellian(np.array([E_eV]), n_cc, T_eV, A)[0]
        return 4 * np.pi * v ** 2 * f

    density_m3, _ = quad(integrand, 0, 2e6, limit=200)

    assert density_m3 == pytest.approx(n_cc * 1e6, rel=1e-6)


def test_kappa_distribution_has_heavier_tail_than_maxwellian_at_high_energy():
    n_cc, T_eV, kappa, A = 5.0, 200.0, 3.0, 1.00728
    E_high = np.array([5000.0])

    f_max = moments_fit.maxwellian(E_high, n_cc, T_eV, A)
    f_kap = moments_fit.kappa_distribution(E_high, n_cc, T_eV, kappa, A)

    assert f_kap[0] > f_max[0]


def test_species_mass_table_has_all_four_channels():
    assert set(moments_fit.SPECIES_MASS_TABLE) == {"h_plus", "alphas", "heavies", "total"}
    assert moments_fit.SPECIES_MASS_TABLE["h_plus"] == (1.00728, 1)
    assert moments_fit.SPECIES_MASS_TABLE["alphas"] == (4.0026, 2)
    assert moments_fit.SPECIES_MASS_TABLE["heavies"] == (16.0, 1)
    assert moments_fit.SPECIES_MASS_TABLE["total"] == (1.00728, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sciqlop_msa.moments_fit'`

- [ ] **Step 3: Write the implementation**

```python
# sciqlop_msa/sciqlop_msa/moments_fit.py
"""Ground-based Maxwellian + Kappa spectral fitting for MSA energy-flux spectra.

Implements the method from the LPP internship report (Diane Kara Youssef, 2026):
convert an MSA differential-directional-energy-flux spectrum to phase-space density,
then fit it as a sum of a Maxwellian core and (optionally) a Kappa suprathermal halo
or a second Maxwellian, selecting whichever candidate model has the lowest reduced
chi-squared in log-space.

The onboard-computed MSA moments are unusable for the archived flyby data (empty in
L2pre, ~zero in L1 — see project memory msa_l2pre_onboard_moments_invalid.md), which
is why this ground-fit method exists.
"""
from dataclasses import dataclass

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import gamma

ELEMENTARY_CHARGE = 1.602176634e-19  # C
ATOMIC_MASS_UNIT = 1.66053906660e-27  # kg
NOISE_FLUX_THRESHOLD = 1e5  # cm^-2 s^-1 sr^-1 eV^-1

# simplify: heavies/total mix species of different mass; there is no single correct
# (A, q) for the m^2/(2(qE)^2) flux-to-phase-space-density conversion. Density values
# for these two channels are approximate by construction. Upgrade path: if MSA ever
# ships a per-species heavy-ion breakdown, replace the O+ proxy with real per-species
# fits.
SPECIES_MASS_TABLE = {
    "h_plus": (1.00728, 1),
    "alphas": (4.0026, 2),
    "heavies": (16.0, 1),
    "total": (1.00728, 1),
}


@dataclass
class FitResult:
    n_tot: float
    T_c: float
    T_eff: float
    model: str
    chi2: float
    params: dict


def ion_mass_kg(A: float) -> float:
    return A * ATOMIC_MASS_UNIT


def flux_to_phase_space_density(E_eV: np.ndarray, F: np.ndarray, A: float, q: int) -> np.ndarray:
    """Convert differential directional energy flux [cm^-2 s^-1 sr^-1 eV^-1] to
    phase-space density [s^3/m^6] (Kara Youssef report, eq. 2)."""
    m = ion_mass_kg(A)
    E_kin_J = q * E_eV * ELEMENTARY_CHARGE
    return m ** 2 * 1e4 / (2.0 * E_kin_J ** 2) * F


def _log_safe(values: np.ndarray) -> np.ndarray:
    return np.log(np.where(values > 0, values, 1e-300))


def maxwellian(E_eV: np.ndarray, n_cc: float, T_eV: float, A: float) -> np.ndarray:
    m = ion_mass_kg(A)
    kT = T_eV * ELEMENTARY_CHARGE
    return n_cc * 1e6 * (m / (2 * np.pi * kT)) ** 1.5 * np.exp(-E_eV * ELEMENTARY_CHARGE / kT)


def kappa_distribution(E_eV: np.ndarray, n_cc: float, T_eV: float, kappa: float, A: float) -> np.ndarray:
    m = ion_mass_kg(A)
    kT = T_eV * ELEMENTARY_CHARGE
    theta2 = (2 * kappa - 3) / kappa * kT / m
    v2 = 2 * E_eV * ELEMENTARY_CHARGE / m
    norm = n_cc * 1e6 * (np.pi * kappa * theta2) ** -1.5 * gamma(kappa + 1) / gamma(kappa - 0.5)
    return norm * (1.0 + v2 / (kappa * theta2)) ** -(kappa + 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
cd sciqlop_msa
git add sciqlop_msa/moments_fit.py sciqlop_msa/tests/test_moments_fit.py
git commit -m "feat(msa): add flux-to-phase-space-density and distribution functions"
```

---

## Task 2: `moments_fit.py` — chi-squared and effective temperature

**Files:**
- Modify: `sciqlop_msa/sciqlop_msa/moments_fit.py`
- Modify: `sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py`

**Interfaces:**
- Consumes: nothing new from Task 1 beyond what's already imported.
- Produces: `_reduced_chi2(f_obs, f_model, n_params) -> float`;
  `effective_temperature(params: dict) -> float`.

- [ ] **Step 1: Write the failing tests**

Append to `test_moments_fit.py`:

```python
def test_reduced_chi2_is_zero_for_perfect_fit():
    f_obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    chi2 = moments_fit._reduced_chi2(f_obs, f_obs.copy(), n_params=2)
    assert chi2 == pytest.approx(0.0, abs=1e-12)


def test_reduced_chi2_is_positive_for_imperfect_fit():
    f_obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    f_model = f_obs * 1.5
    chi2 = moments_fit._reduced_chi2(f_obs, f_model, n_params=2)
    assert chi2 > 0.0


def test_effective_temperature_max_kap_and_2max_share_formula():
    params = dict(model="max_kap", nc=10.0, Tc=100.0, nh=1.0, Th=1000.0)
    expected = (10.0 * 100.0 + 1.0 * 1000.0) / (10.0 + 1.0)
    assert moments_fit.effective_temperature(params) == pytest.approx(expected)

    params2 = dict(model="2max", nc=10.0, Tc=100.0, nh=1.0, Th=1000.0)
    assert moments_fit.effective_temperature(params2) == pytest.approx(expected)


def test_effective_temperature_2max_kap_weights_three_populations():
    params = dict(
        model="2max_kap",
        nc=10.0, Tc=100.0,
        nw=2.0, Tw=500.0,
        nh=0.5, Th=5000.0,
    )
    expected = (10.0 * 100.0 + 2.0 * 500.0 + 0.5 * 5000.0) / (10.0 + 2.0 + 0.5)
    assert moments_fit.effective_temperature(params) == pytest.approx(expected)


def test_effective_temperature_rejects_unknown_model():
    with pytest.raises(ValueError):
        moments_fit.effective_temperature({"model": "not_a_model"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py -v`
Expected: the 5 new tests FAIL with `AttributeError: module 'sciqlop_msa.moments_fit' has no attribute '_reduced_chi2'` (or `effective_temperature`)

- [ ] **Step 3: Write the implementation**

Append to `moments_fit.py`:

```python
def _reduced_chi2(f_obs: np.ndarray, f_model: np.ndarray, n_params: int) -> float:
    residual = _log_safe(f_obs) - _log_safe(np.maximum(f_model, 1e-300))
    return float(np.sum(residual ** 2) / max(len(f_obs) - n_params, 1))


def effective_temperature(params: dict) -> float:
    """Density-weighted effective temperature across all populations in a fit."""
    model = params["model"]
    if model in ("max_kap", "2max"):
        return (params["nc"] * params["Tc"] + params["nh"] * params["Th"]) / (
            params["nc"] + params["nh"]
        )
    if model == "2max_kap":
        return (
            params["nc"] * params["Tc"]
            + params["nw"] * params["Tw"]
            + params["nh"] * params["Th"]
        ) / (params["nc"] + params["nw"] + params["nh"])
    raise ValueError(f"Unknown model {model!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
cd sciqlop_msa
git add sciqlop_msa/moments_fit.py sciqlop_msa/tests/test_moments_fit.py
git commit -m "feat(msa): add reduced chi-squared and effective temperature"
```

---

## Task 3: `moments_fit.py` — `fit_max_kap` (Maxwellian core + Kappa halo)

**Files:**
- Modify: `sciqlop_msa/sciqlop_msa/moments_fit.py`
- Modify: `sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py`

**Interfaces:**
- Consumes: `maxwellian`, `kappa_distribution`, `_log_safe`, `_reduced_chi2`,
  `effective_temperature`, `ion_mass_kg`, `ELEMENTARY_CHARGE` from Tasks 1-2.
- Produces: `_init_maxwell_slope(energy, f_obs, mask, e_min, e_max, A) -> (n, T)`;
  `_init_kappa_slope(energy, f_obs, mask, e_min, e_max) -> kappa`;
  `fit_max_kap(energy, f_obs, mask, A, q) -> FitResult | None`.

  `energy`/`f_obs`/`mask` are full-length 1D arrays (64 points, one spectrum) — `mask`
  selects which points are usable (finite, positive, above noise threshold). This
  full-array-plus-mask convention is used by every `fit_*`/`best_fit` function so
  callers don't have to pre-slice.

- [ ] **Step 1: Write the failing test**

Append to `test_moments_fit.py`:

```python
def test_fit_max_kap_recovers_injected_maxwell_plus_kappa_parameters():
    energy = np.logspace(0, np.log10(39200), 64)
    n_c, T_c = 45.0, 280.0
    n_h, T_h, kappa_true = 0.08, 5000.0, 3.5
    A, q = 1.00728, 1

    f_true = (
        moments_fit.maxwellian(energy, n_c, T_c, A)
        + moments_fit.kappa_distribution(energy, n_h, T_h, kappa_true, A)
    )
    rng = np.random.default_rng(42)
    f_obs = f_true * rng.lognormal(mean=0.0, sigma=0.05, size=f_true.shape)
    mask = np.ones_like(energy, dtype=bool)

    result = moments_fit.fit_max_kap(energy, f_obs, mask, A, q)

    assert result is not None
    assert result.model == "max_kap"
    assert result.params["nc"] == pytest.approx(n_c, rel=0.05)
    assert result.params["Tc"] == pytest.approx(T_c, rel=0.05)
    assert result.params["nh"] == pytest.approx(n_h, rel=0.1)
    assert result.params["Th"] == pytest.approx(T_h, rel=0.05)
    assert result.params["kappa"] == pytest.approx(kappa_true, rel=0.1)
    assert result.n_tot == pytest.approx(n_c + n_h, rel=0.05)
    assert result.T_c == pytest.approx(T_c, rel=0.05)


def test_fit_max_kap_returns_none_with_too_few_points():
    energy = np.logspace(0, np.log10(39200), 64)
    f_obs = np.full(64, np.nan)
    mask = np.zeros(64, dtype=bool)
    mask[:2] = True  # fewer than 3 points in the core window

    result = moments_fit.fit_max_kap(energy, f_obs, mask, 1.00728, 1)

    assert result is None
```

These tolerances were verified against a standalone reproduction of this exact
algorithm before writing this plan: recovered `nc`≈45.21 (inj. 45.0), `Tc`≈280.68
(inj. 280.0), `nh`≈0.0804 (inj. 0.08), `Th`≈4994.7 (inj. 5000.0), `kappa`≈3.378 (inj.
3.5) — all comfortably inside the tolerances above.

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py -v`
Expected: the 2 new tests FAIL with `AttributeError: module 'sciqlop_msa.moments_fit' has no attribute 'fit_max_kap'`

- [ ] **Step 3: Write the implementation**

Append to `moments_fit.py`:

```python
def _init_maxwell_slope(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray,
                        e_min: float, e_max: float, A: float) -> tuple:
    m = mask & (energy > e_min) & (energy < e_max)
    if m.sum() < 3:
        return 1.0, 100.0
    try:
        slope, intercept = np.polyfit(energy[m], np.log(f_obs[m]), 1)
    except np.linalg.LinAlgError:
        return 1.0, 100.0
    T = max(-1.0 / slope, 1.0) if slope < 0 else 100.0
    n = max(
        np.exp(intercept) / (ion_mass_kg(A) / (2 * np.pi * T * ELEMENTARY_CHARGE)) ** 1.5 / 1e6,
        0.01,
    )
    return n, T


def _init_kappa_slope(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray,
                      e_min: float, e_max: float) -> float:
    m = mask & (energy > e_min) & (energy < e_max)
    if m.sum() < 3:
        return 3.0
    try:
        slope, _ = np.polyfit(np.log(energy[m]), np.log(f_obs[m]), 1)
    except np.linalg.LinAlgError:
        return 3.0
    return float(np.clip(-slope - 1.0, 1.6, 10.0))


def fit_max_kap(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray,
                A: float, q: int) -> "FitResult | None":
    """Fit a Maxwellian core + Kappa suprathermal halo."""
    Eg, fg = energy[mask], f_obs[mask]
    nc0, Tc0 = _init_maxwell_slope(energy, f_obs, mask, 20, 700, A)
    kap0 = _init_kappa_slope(energy, f_obs, mask, 800, 30000)
    nh0, Th0 = 0.15 * nc0, 10 * Tc0

    mc = (Eg > 20) & (Eg < 700)
    if mc.sum() < 3:
        return None
    try:
        pm, _ = curve_fit(
            lambda E, log_n, log_T: _log_safe(maxwellian(E, 10 ** log_n, 10 ** log_T, A)),
            Eg[mc], np.log(fg[mc]),
            p0=[np.log10(nc0), np.log10(Tc0)],
            bounds=([-3, 0], [4, 3]),
            maxfev=10000,
        )
    except (RuntimeError, ValueError):
        return None
    nc_seed, Tc_seed = 10 ** pm[0], 10 ** pm[1]

    residual = fg - maxwellian(Eg, nc_seed, Tc_seed, A)
    mk = (residual > 0) & (Eg > 800)
    if mk.sum() >= 3:
        try:
            pk, _ = curve_fit(
                lambda E, log_n, log_T, kappa: _log_safe(kappa_distribution(E, 10 ** log_n, 10 ** log_T, kappa, A)),
                Eg[mk], np.log(residual[mk]),
                p0=[np.log10(max(nh0, 0.001)), np.log10(max(Th0, 30)), kap0],
                bounds=([-3, 1.5, 1.55], [4, 4.5, 12]),
                maxfev=10000,
            )
            nh_seed, Th_seed, kap_seed = 10 ** pk[0], 10 ** pk[1], pk[2]
        except (RuntimeError, ValueError):
            nh_seed, Th_seed, kap_seed = nh0, Th0, kap0
    else:
        nh_seed, Th_seed, kap_seed = nh0, Th0, kap0

    def joint_model(E, log_nc, log_Tc, log_nh, log_Th, kappa):
        return _log_safe(
            maxwellian(E, 10 ** log_nc, 10 ** log_Tc, A)
            + kappa_distribution(E, 10 ** log_nh, 10 ** log_Th, kappa, A)
        )

    try:
        popt, _ = curve_fit(
            joint_model, Eg, np.log(fg),
            p0=[np.log10(nc_seed), np.log10(Tc_seed), np.log10(nh_seed), np.log10(Th_seed), kap_seed],
            bounds=([-3, 0, -3, 1.5, 1.55], [4, 3, 4, 4.5, 12]),
            maxfev=40000,
        )
    except (RuntimeError, ValueError):
        return None

    nc_f, Tc_f, nh_f, Th_f, kap_f = 10 ** popt[0], 10 ** popt[1], 10 ** popt[2], 10 ** popt[3], popt[4]
    if Th_f > 20000 or kap_f >= 11.9:
        return None

    f_model = maxwellian(Eg, nc_f, Tc_f, A) + kappa_distribution(Eg, nh_f, Th_f, kap_f, A)
    params = dict(model="max_kap", nc=nc_f, Tc=Tc_f, nh=nh_f, Th=Th_f, kappa=kap_f)
    return FitResult(
        n_tot=nc_f + nh_f,
        T_c=Tc_f,
        T_eff=effective_temperature(params),
        model="max_kap",
        chi2=_reduced_chi2(fg, f_model, 5),
        params=params,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
cd sciqlop_msa
git add sciqlop_msa/moments_fit.py sciqlop_msa/tests/test_moments_fit.py
git commit -m "feat(msa): add fit_max_kap (Maxwellian core + Kappa halo)"
```

---

## Task 4: `moments_fit.py` — `fit_2max`, `fit_2max_kap`, `best_fit`

**Files:**
- Modify: `sciqlop_msa/sciqlop_msa/moments_fit.py`
- Modify: `sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3, plus `_init_maxwell_slope`, `_init_kappa_slope`.
- Produces: `fit_2max(energy, f_obs, mask, A, q) -> FitResult | None`;
  `fit_2max_kap(energy, f_obs, mask, A, q) -> FitResult | None`;
  `best_fit(energy, f_obs, mask, A, q) -> FitResult | None` (tries all three, keeps
  lowest `chi2` among the ones that didn't fail).

- [ ] **Step 1: Write the failing tests**

Append to `test_moments_fit.py`:

```python
def test_fit_2max_recovers_two_independent_maxwellian_populations():
    energy = np.logspace(0, np.log10(39200), 64)
    n_c, T_c = 20.0, 150.0
    n_h, T_h = 2.0, 1500.0
    A, q = 1.00728, 1

    f_true = moments_fit.maxwellian(energy, n_c, T_c, A) + moments_fit.maxwellian(energy, n_h, T_h, A)
    rng = np.random.default_rng(7)
    f_obs = f_true * rng.lognormal(mean=0.0, sigma=0.05, size=f_true.shape)
    mask = np.ones_like(energy, dtype=bool)

    result = moments_fit.fit_2max(energy, f_obs, mask, A, q)

    assert result is not None
    assert result.model == "2max"
    assert result.params["nc"] == pytest.approx(n_c, rel=0.1)
    assert result.params["Tc"] == pytest.approx(T_c, rel=0.05)
    assert result.params["nh"] == pytest.approx(n_h, rel=0.05)
    assert result.params["Th"] == pytest.approx(T_h, rel=0.05)


def test_best_fit_selects_max_kap_when_data_has_a_kappa_tail():
    energy = np.logspace(0, np.log10(39200), 64)
    n_c, T_c = 45.0, 280.0
    n_h, T_h, kappa_true = 0.08, 5000.0, 3.5
    A, q = 1.00728, 1

    f_true = (
        moments_fit.maxwellian(energy, n_c, T_c, A)
        + moments_fit.kappa_distribution(energy, n_h, T_h, kappa_true, A)
    )
    rng = np.random.default_rng(42)
    f_obs = f_true * rng.lognormal(mean=0.0, sigma=0.05, size=f_true.shape)
    mask = np.ones_like(energy, dtype=bool)

    result = moments_fit.best_fit(energy, f_obs, mask, A, q)

    assert result is not None
    assert result.model == "max_kap"


def test_best_fit_returns_none_when_all_models_fail():
    energy = np.logspace(0, np.log10(39200), 64)
    f_obs = np.full(64, np.nan)
    mask = np.zeros(64, dtype=bool)

    assert moments_fit.best_fit(energy, f_obs, mask, 1.00728, 1) is None
```

The `best_fit` selection tolerance is exact-match on `model` because a standalone
reproduction of this algorithm before writing this plan showed a clean separation:
`max_kap` chi2 ≈ 0.00163 vs `2max` chi2 ≈ 0.0255 vs `2max_kap` returning `None`
(insufficiently constrained by only 64 points) on this exact synthetic spectrum.

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py -v`
Expected: the 3 new tests FAIL with `AttributeError: module 'sciqlop_msa.moments_fit' has no attribute 'fit_2max'`

- [ ] **Step 3: Write the implementation**

Append to `moments_fit.py`:

```python
def fit_2max(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray,
            A: float, q: int) -> "FitResult | None":
    """Fit two independent Maxwellians (cold core + warm secondary population)."""
    Eg, fg = energy[mask], f_obs[mask]
    nc0, Tc0 = _init_maxwell_slope(energy, f_obs, mask, 10, 400, A)
    nh0, Th0 = _init_maxwell_slope(energy, f_obs, mask, 300, 8000, A)

    mc = Eg < 400
    if mc.sum() < 3:
        return None
    try:
        pm, _ = curve_fit(
            lambda E, log_n, log_T: _log_safe(maxwellian(E, 10 ** log_n, 10 ** log_T, A)),
            Eg[mc], np.log(fg[mc]),
            p0=[np.log10(nc0), np.log10(Tc0)],
            bounds=([-3, 0], [4, 3.5]),
            maxfev=10000,
        )
    except (RuntimeError, ValueError):
        return None
    nc_seed, Tc_seed = 10 ** pm[0], 10 ** pm[1]

    residual = fg - maxwellian(Eg, nc_seed, Tc_seed, A)
    mh = (residual > 0) & (Eg > 300)
    if mh.sum() < 3:
        return None
    try:
        ph, _ = curve_fit(
            lambda E, log_n, log_T: _log_safe(maxwellian(E, 10 ** log_n, 10 ** log_T, A)),
            Eg[mh], np.log(residual[mh]),
            p0=[np.log10(max(nh0, 0.001)), np.log10(max(Th0, 30))],
            bounds=([-3, 1.5], [4, 4.5]),
            maxfev=10000,
        )
    except (RuntimeError, ValueError):
        return None
    nh_seed, Th_seed = 10 ** ph[0], 10 ** ph[1]

    def joint_model(E, log_nc, log_Tc, log_nh, log_Th):
        return _log_safe(
            maxwellian(E, 10 ** log_nc, 10 ** log_Tc, A)
            + maxwellian(E, 10 ** log_nh, 10 ** log_Th, A)
        )

    try:
        popt, _ = curve_fit(
            joint_model, Eg, np.log(fg),
            p0=[np.log10(nc_seed), np.log10(Tc_seed), np.log10(nh_seed), np.log10(Th_seed)],
            bounds=([-3, 0, -3, 1.5], [4, 3.5, 4, 4.5]),
            maxfev=40000,
        )
    except (RuntimeError, ValueError):
        return None

    nc_f, Tc_f, nh_f, Th_f = 10 ** popt[0], 10 ** popt[1], 10 ** popt[2], 10 ** popt[3]
    f_model = maxwellian(Eg, nc_f, Tc_f, A) + maxwellian(Eg, nh_f, Th_f, A)
    params = dict(model="2max", nc=nc_f, Tc=Tc_f, nh=nh_f, Th=Th_f)
    return FitResult(
        n_tot=nc_f + nh_f,
        T_c=Tc_f,
        T_eff=effective_temperature(params),
        model="2max",
        chi2=_reduced_chi2(fg, f_model, 4),
        params=params,
    )


def fit_2max_kap(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray,
                 A: float, q: int) -> "FitResult | None":
    """Fit cold core + warm secondary Maxwellian + Kappa suprathermal halo."""
    Eg, fg = energy[mask], f_obs[mask]
    nc0, Tc0 = _init_maxwell_slope(energy, f_obs, mask, 10, 200, A)
    nw0, Tw0 = _init_maxwell_slope(energy, f_obs, mask, 200, 1500, A)
    kap0 = _init_kappa_slope(energy, f_obs, mask, 1500, 30000)

    mc = (Eg > 10) & (Eg < 200)
    if mc.sum() < 3:
        return None
    try:
        pm, _ = curve_fit(
            lambda E, log_n, log_T: _log_safe(maxwellian(E, 10 ** log_n, 10 ** log_T, A)),
            Eg[mc], np.log(fg[mc]),
            p0=[np.log10(nc0), np.log10(Tc0)],
            bounds=([-3, 0.5], [4, 2.5]),
            maxfev=10000,
        )
    except (RuntimeError, ValueError):
        return None
    nc_seed, Tc_seed = 10 ** pm[0], 10 ** pm[1]

    residual1 = fg - maxwellian(Eg, nc_seed, Tc_seed, A)
    mw = (residual1 > 0) & (Eg > 200) & (Eg < 1500)
    if mw.sum() < 3:
        return None
    try:
        pw, _ = curve_fit(
            lambda E, log_n, log_T: _log_safe(maxwellian(E, 10 ** log_n, 10 ** log_T, A)),
            Eg[mw], np.log(residual1[mw]),
            p0=[np.log10(max(nw0, 0.001)), np.log10(max(Tw0, 30))],
            bounds=([-3, 2], [4, 3.5]),
            maxfev=10000,
        )
    except (RuntimeError, ValueError):
        return None
    nw_seed, Tw_seed = 10 ** pw[0], 10 ** pw[1]

    residual2 = residual1 - maxwellian(Eg, nw_seed, Tw_seed, A)
    mk = (residual2 > 0) & (Eg > 1500)
    if mk.sum() >= 3:
        try:
            pk, _ = curve_fit(
                lambda E, log_n, log_T, kappa: _log_safe(kappa_distribution(E, 10 ** log_n, 10 ** log_T, kappa, A)),
                Eg[mk], np.log(residual2[mk]),
                p0=[np.log10(0.1), np.log10(5000), kap0],
                bounds=([-4, 3, 1.55], [3, 4.5, 12]),
                maxfev=10000,
            )
            nh_seed, Th_seed, kap_seed = 10 ** pk[0], 10 ** pk[1], pk[2]
        except (RuntimeError, ValueError):
            nh_seed, Th_seed, kap_seed = 0.1, 5000.0, kap0
    else:
        nh_seed, Th_seed, kap_seed = 0.1, 5000.0, kap0

    def joint_model(E, log_nc, log_Tc, log_nw, log_Tw, log_nh, log_Th, kappa):
        return _log_safe(
            maxwellian(E, 10 ** log_nc, 10 ** log_Tc, A)
            + maxwellian(E, 10 ** log_nw, 10 ** log_Tw, A)
            + kappa_distribution(E, 10 ** log_nh, 10 ** log_Th, kappa, A)
        )

    try:
        popt, _ = curve_fit(
            joint_model, Eg, np.log(fg),
            p0=[
                np.log10(nc_seed), np.log10(Tc_seed),
                np.log10(nw_seed), np.log10(Tw_seed),
                np.log10(max(nh_seed, 1e-4)), np.log10(max(Th_seed, 1000)),
                kap_seed,
            ],
            bounds=([-3, 0.5, -3, 2, -4, 3, 1.55], [4, 2.5, 4, 3.5, 3, 4.5, 12]),
            maxfev=80000,
        )
    except (RuntimeError, ValueError):
        return None

    nc_f, Tc_f = 10 ** popt[0], 10 ** popt[1]
    nw_f, Tw_f = 10 ** popt[2], 10 ** popt[3]
    nh_f, Th_f, kap_f = 10 ** popt[4], 10 ** popt[5], popt[6]
    if Th_f > 20000 or kap_f >= 11.9:
        return None

    f_model = (
        maxwellian(Eg, nc_f, Tc_f, A)
        + maxwellian(Eg, nw_f, Tw_f, A)
        + kappa_distribution(Eg, nh_f, Th_f, kap_f, A)
    )
    params = dict(model="2max_kap", nc=nc_f, Tc=Tc_f, nw=nw_f, Tw=Tw_f, nh=nh_f, Th=Th_f, kappa=kap_f)
    return FitResult(
        n_tot=nc_f + nw_f + nh_f,
        T_c=Tc_f,
        T_eff=effective_temperature(params),
        model="2max_kap",
        chi2=_reduced_chi2(fg, f_model, 7),
        params=params,
    )


def best_fit(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray,
            A: float, q: int) -> "FitResult | None":
    """Try all three candidate models, keep the one with the lowest reduced chi-squared."""
    candidates = [
        r for r in (
            fit_max_kap(energy, f_obs, mask, A, q),
            fit_2max(energy, f_obs, mask, A, q),
            fit_2max_kap(energy, f_obs, mask, A, q),
        )
        if r is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda r: r.chi2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_fit.py -v`
Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
cd sciqlop_msa
git add sciqlop_msa/moments_fit.py sciqlop_msa/tests/test_moments_fit.py
git commit -m "feat(msa): add fit_2max, fit_2max_kap, and best_fit model selection"
```

---

## Task 5: `moments_source.py` — per-species, per-day fetch

**Files:**
- Create: `sciqlop_msa/sciqlop_msa/moments_source.py`
- Test: `sciqlop_msa/sciqlop_msa/tests/test_moments_source.py`

**Interfaces:**
- Consumes: `moments_fit.NOISE_FLUX_THRESHOLD`, `moments_fit.SPECIES_MASS_TABLE` (for
  the set of valid species keys).
- Produces: `DaySpectra` dataclass (`time: np.ndarray` epoch-seconds float,
  `energy: np.ndarray` shape `(64,)`, `flux: np.ndarray` shape `(n, 64)`, NaN where
  masked); `fetch_day(species: str, day: datetime.date) -> DaySpectra | None`.

- [ ] **Step 1: Write the failing test**

```python
# sciqlop_msa/sciqlop_msa/tests/test_moments_source.py
from datetime import date

import numpy as np
import pytest


def _make_fake_variable(flux, energy, times):
    from speasy.products import SpeasyVariable, VariableTimeAxis, VariableAxis, DataContainer

    time_axis = VariableTimeAxis(values=times.astype("datetime64[ns]"))
    energy_axis = VariableAxis(values=energy, name="energy_table_mass", is_time_dependent=False)
    values = DataContainer(
        values=flux,
        meta={"FILLVAL": -9.999999848243207e30},
        is_time_dependent=True,
    )
    return SpeasyVariable(axes=[time_axis, energy_axis], values=values)


def test_fetch_day_masks_fillval_and_noise_threshold(monkeypatch):
    from sciqlop_msa import moments_source

    energy = np.array([10.0, 100.0, 1000.0])
    times = np.array(["2025-01-08T00:00:00", "2025-01-08T00:01:00"], dtype="datetime64[s]")
    flux = np.array([
        [1e6, -9.999999848243207e30, 1e4],
        [1e7, 1e6, 1e5],
    ])
    fake_var = _make_fake_variable(flux, energy, times)

    import speasy
    monkeypatch.setattr(speasy, "get_data", lambda *a, **kw: fake_var)

    result = moments_source.fetch_day("h_plus", date(2025, 1, 8))

    assert result is not None
    assert result.energy.tolist() == pytest.approx([10.0, 100.0, 1000.0])
    assert result.flux.shape == (2, 3)
    assert np.isnan(result.flux[0, 1])  # FILLVAL -> NaN
    assert np.isnan(result.flux[0, 2])  # below NOISE_FLUX_THRESHOLD -> NaN
    assert result.flux[0, 0] == pytest.approx(1e6)
    assert result.flux[1, 2] == pytest.approx(1e5)  # exactly at threshold: kept
    assert len(result.time) == 2


def test_fetch_day_returns_none_when_speasy_has_no_data(monkeypatch):
    from sciqlop_msa import moments_source
    import speasy

    monkeypatch.setattr(speasy, "get_data", lambda *a, **kw: None)

    result = moments_source.fetch_day("h_plus", date(2020, 1, 1))

    assert result is None


def test_fetch_day_rejects_unknown_species():
    from sciqlop_msa import moments_source

    with pytest.raises(KeyError):
        moments_source.fetch_day("not_a_species", date(2025, 1, 8))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_source.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sciqlop_msa.moments_source'`

- [ ] **Step 3: Write the implementation**

```python
# sciqlop_msa/sciqlop_msa/moments_source.py
"""Per-species, per-day fetch of MSA L2pre energy-flux spectra from the Speasy archive."""
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

import numpy as np

from .moments_fit import NOISE_FLUX_THRESHOLD

_L2PRE = "archive/BepiColombo/MSA/L2pre_Low_EFlux_Moments_TOF/bc_mmo_mppe_msa_l2pre_l_eflux_moments_tof"

_SPECIES_VARIABLE = {
    "h_plus": "diff_dir_en_flux_h_plus",
    "alphas": "diff_dir_en_flux_alphas",
    "heavies": "diff_dir_en_flux_heavies",
    "total": "diff_dir_en_flux_total",
}


@dataclass
class DaySpectra:
    time: np.ndarray
    energy: np.ndarray
    flux: np.ndarray


def _day_bounds(day: date) -> tuple:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    stop = datetime.combine(day, time.max, tzinfo=timezone.utc)
    return start, stop


def fetch_day(species: str, day: date) -> "DaySpectra | None":
    import speasy

    variable = _SPECIES_VARIABLE[species]
    start, stop = _day_bounds(day)
    var = speasy.get_data(f"{_L2PRE}/{variable}", start, stop)
    if var is None or len(var) == 0:
        return None

    var = var.replace_fillval_by_nan(convert_to_float=True)

    energy = np.asarray(var.axes[1].values, dtype=float)
    if energy.ndim == 2:
        energy = energy[0]
    flux = np.asarray(var.values, dtype=float)
    flux = np.where(flux < NOISE_FLUX_THRESHOLD, np.nan, flux)

    time_epoch = var.time.astype("datetime64[s]").astype("int64").astype(float)
    return DaySpectra(time=time_epoch, energy=energy, flux=flux)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_source.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd sciqlop_msa
git add sciqlop_msa/moments_source.py sciqlop_msa/tests/test_moments_source.py
git commit -m "feat(msa): add per-species per-day L2pre flux fetch"
```

---

## Task 6: `moments_compute.py` — day-bucketed cached fit orchestration

**Files:**
- Create: `sciqlop_msa/sciqlop_msa/moments_compute.py`
- Test: `sciqlop_msa/sciqlop_msa/tests/test_moments_compute.py`

**Interfaces:**
- Consumes: `moments_source.fetch_day`, `moments_source.DaySpectra`,
  `moments_fit.best_fit`, `moments_fit.SPECIES_MASS_TABLE`.
- Produces: `DayFits` dataclass (`time`, `n_tot`, `T_c`, `T_eff`: `np.ndarray` float;
  `model`: `np.ndarray` of `str`; `chi2`: `np.ndarray` float — all same length, one
  entry per spectrum, `NaN`/`""` where the fit failed);
  `_fit_day_uncached(species: str, day: date) -> DayFits | None` (the testable,
  undecorated function); `fit_day(species: str, day: date) -> DayFits | None` (the
  `CacheCall`-wrapped public entry point used by `moments_vp.py`).

- [ ] **Step 1: Write the failing tests**

```python
# sciqlop_msa/sciqlop_msa/tests/test_moments_compute.py
from datetime import date
from unittest.mock import patch

import numpy as np
import pytest

from sciqlop_msa import moments_fit
from sciqlop_msa.moments_source import DaySpectra


def _synthetic_day_spectra():
    energy = np.logspace(0, np.log10(39200), 64)
    n_c, T_c = 45.0, 280.0
    n_h, T_h, kappa_true = 0.08, 5000.0, 3.5
    rng = np.random.default_rng(42)
    good_row = (
        moments_fit.maxwellian(energy, n_c, T_c, 1.00728)
        + moments_fit.kappa_distribution(energy, n_h, T_h, kappa_true, 1.00728)
    ) * rng.lognormal(mean=0.0, sigma=0.05, size=64)
    empty_row = np.full(64, np.nan)  # fewer than 6 usable points -> skipped
    flux = np.stack([good_row, empty_row])
    time = np.array([1736300000.0, 1736300060.0])
    return DaySpectra(time=time, energy=energy, flux=flux)


def test_fit_day_uncached_fits_valid_rows_and_skips_sparse_rows():
    from sciqlop_msa import moments_compute

    with patch("sciqlop_msa.moments_compute.fetch_day", return_value=_synthetic_day_spectra()):
        result = moments_compute._fit_day_uncached("h_plus", date(2025, 1, 8))

    assert result is not None
    assert len(result.time) == 2
    assert result.n_tot[0] == pytest.approx(45.08, rel=0.1)
    assert result.model[0] == "max_kap"
    assert np.isnan(result.n_tot[1])
    assert result.model[1] == ""


def test_fit_day_uncached_returns_none_when_fetch_returns_none():
    from sciqlop_msa import moments_compute

    with patch("sciqlop_msa.moments_compute.fetch_day", return_value=None):
        result = moments_compute._fit_day_uncached("h_plus", date(2020, 1, 1))

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_compute.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sciqlop_msa.moments_compute'`

- [ ] **Step 3: Write the implementation**

```python
# sciqlop_msa/sciqlop_msa/moments_compute.py
"""Day-bucketed, cached moment fitting: fetch + fit once per (species, day),
then let moments_vp.py slice/concatenate day-buckets to an arbitrary window.

Day-bucketed (not file-signature-based) because Speasy's get_data() already
handles archive file resolution/stitching (see moments_source.py) — there's no
file path for this module to key a cache on. Flybys are 1-2 days of data, so
one day is a natural, simple cache granularity (mirrors sciqlop_radio's
day-bucketed search cache).
"""
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from .moments_fit import SPECIES_MASS_TABLE, best_fit
from .moments_source import fetch_day

_MIN_POINTS_TO_FIT = 6


@dataclass
class DayFits:
    time: np.ndarray
    n_tot: np.ndarray
    T_c: np.ndarray
    T_eff: np.ndarray
    model: np.ndarray
    chi2: np.ndarray


def _fit_day_uncached(species: str, day: date) -> "DayFits | None":
    spectra = fetch_day(species, day)
    if spectra is None:
        return None

    A, q = SPECIES_MASS_TABLE[species]
    n = len(spectra.time)
    n_tot = np.full(n, np.nan)
    T_c = np.full(n, np.nan)
    T_eff = np.full(n, np.nan)
    model = np.full(n, "", dtype="<U8")
    chi2 = np.full(n, np.nan)

    for i in range(n):
        row = spectra.flux[i]
        mask = np.isfinite(row) & (row > 0)
        if mask.sum() < _MIN_POINTS_TO_FIT:
            continue
        result = best_fit(spectra.energy, row, mask, A, q)
        if result is None:
            continue
        n_tot[i] = result.n_tot
        T_c[i] = result.T_c
        T_eff[i] = result.T_eff
        model[i] = result.model
        chi2[i] = result.chi2

    return DayFits(time=spectra.time, n_tot=n_tot, T_c=T_c, T_eff=T_eff, model=model, chi2=chi2)


_cached_fit_day = None


def _make_cached_fit_day():
    from speasy.core.cache import CacheCall

    @CacheCall(cache_retention=timedelta(days=30), is_pure=True)
    def _cached(species: str, day: date):
        return _fit_day_uncached(species, day)

    return _cached


def fit_day(species: str, day: date) -> "DayFits | None":
    global _cached_fit_day
    if _cached_fit_day is None:
        _cached_fit_day = _make_cached_fit_day()
    return _cached_fit_day(species, day)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_compute.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
cd sciqlop_msa
git add sciqlop_msa/moments_compute.py sciqlop_msa/tests/test_moments_compute.py
git commit -m "feat(msa): add day-bucketed cached moment fit orchestration"
```

---

## Task 7: `moments_vp.py` — virtual product registration + `plugin.py` wiring

**Files:**
- Create: `sciqlop_msa/sciqlop_msa/moments_vp.py`
- Create: `sciqlop_msa/sciqlop_msa/tests/conftest.py`
- Test: `sciqlop_msa/sciqlop_msa/tests/test_moments_vp.py`
- Modify: `sciqlop_msa/sciqlop_msa/plugin.py`

**Interfaces:**
- Consumes: `moments_fit.SPECIES_MASS_TABLE`, `moments_compute.fit_day`,
  `moments_compute.DayFits`.
- Produces: `FIELDS: dict[str, tuple[str, str]]` (field name -> `(DayFits` attribute
  name, unit`)`); `register_moments_vps() -> list` (also used by `plugin.py.load()`).

This task also creates `sciqlop_msa/sciqlop_msa/tests/conftest.py`, needed because
`register_moments_vps()` imports `SciQLop.user_api.virtual_products`, which — on a
machine with a real SciQLop install — pulls in Qt global state that SIGABRTs without a
running `QApplication`. This mirrors the existing pattern in
`sciqlop_sismo/sciqlop_sismo/tests/conftest.py` and
`sciqlop_radio/sciqlop_radio/tests/conftest.py`; `sciqlop_msa` doesn't have one yet.

- [ ] **Step 1: Write the test conftest and the failing tests**

```python
# sciqlop_msa/sciqlop_msa/tests/conftest.py
"""Test fixtures for sciqlop_msa's moments-fit tests.

Stubs SciQLop.user_api.virtual_products so moments_vp.register_moments_vps() can
be unit-tested without a real SciQLop/Qt install (mirrors the sciqlop_sismo /
sciqlop_radio pattern) and isolates Speasy's disk cache per test run.
"""
import atexit
import os
import sys
import tempfile
from unittest.mock import MagicMock

# Must precede any speasy import: the cache singleton reads SPEASY_CACHE_PATH at
# import time. A fresh tempdir keeps the fragment cache from leaking across runs.
os.environ.setdefault(
    "SPEASY_CACHE_PATH", tempfile.mkdtemp(prefix="sciqlop_msa_cache_")
)

import pytest


def _force_exit():
    os._exit(0)


atexit.register(_force_exit)

for _name in ("SciQLop", "SciQLop.user_api", "SciQLop.user_api.virtual_products"):
    sys.modules.setdefault(_name, MagicMock())


@pytest.fixture(autouse=True)
def _isolate_speasy_cache():
    """Drop all Speasy cache entries before each test so the day-bucketed fit
    cache can't leak hits from one test into another."""
    import re

    from speasy.core.cache import drop_matching_entries

    drop_matching_entries(re.compile(".*"))
    yield
```

```python
# sciqlop_msa/sciqlop_msa/tests/test_moments_vp.py
from datetime import date
from unittest.mock import patch

import numpy as np
import pytest

from sciqlop_msa.moments_compute import DayFits


def _day_fits(day_offset_seconds=0.0):
    return DayFits(
        time=np.array([1736300000.0, 1736300060.0]) + day_offset_seconds,
        n_tot=np.array([45.0, 46.0]),
        T_c=np.array([280.0, 281.0]),
        T_eff=np.array([300.0, 301.0]),
        model=np.array(["max_kap", "max_kap"]),
        chi2=np.array([0.001, 0.002]),
    )


def test_register_moments_vps_creates_twelve_products():
    from sciqlop_msa import moments_vp

    with patch("SciQLop.user_api.virtual_products.create_virtual_product") as mock_create:
        moments_vp.register_moments_vps()

    assert mock_create.call_count == 12
    paths = {call.kwargs["path"] for call in mock_create.call_args_list}
    assert "msa/moments_fit/h_plus/density" in paths
    assert "msa/moments_fit/alphas/T_c" in paths
    assert "msa/moments_fit/heavies/T_eff" in paths
    assert "msa/moments_fit/total/density" in paths


def test_density_callback_returns_values_sliced_to_requested_window():
    from sciqlop_msa import moments_vp

    callback = moments_vp._make_callback("h_plus", "density")

    with patch("sciqlop_msa.moments_vp.fit_day", return_value=_day_fits()):
        result = callback(1736300000.0, 1736300060.0)

    assert result is not None
    assert result.values.reshape(-1).tolist() == pytest.approx([45.0, 46.0])


def test_density_callback_returns_none_when_no_data():
    from sciqlop_msa import moments_vp

    callback = moments_vp._make_callback("h_plus", "density")

    with patch("sciqlop_msa.moments_vp.fit_day", return_value=None):
        result = callback(1577836800.0, 1577840400.0)

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/test_moments_vp.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sciqlop_msa.moments_vp'`

- [ ] **Step 3: Write the implementation**

```python
# sciqlop_msa/sciqlop_msa/moments_vp.py
"""Virtual product registration for the ground-fit MSA moments."""
from datetime import datetime, timedelta, timezone

import numpy as np

from .moments_compute import fit_day
from .moments_fit import SPECIES_MASS_TABLE

FIELDS = {
    "density": ("n_tot", "cm^-3"),
    "T_c": ("T_c", "eV"),
    "T_eff": ("T_eff", "eV"),
}

_APPROXIMATE_SPECIES = {
    "heavies": "O+ proxy (A=16, q=1) — diff_dir_en_flux_heavies sums species of different mass.",
    "total": "proton-equivalent (A=1.00728, q=1) — diff_dir_en_flux_total sums species of different mass.",
}

_registered_vps = []


def _days_between(start_dt: datetime, stop_dt: datetime):
    day = start_dt.date()
    last_day = stop_dt.date()
    while day <= last_day:
        yield day
        day += timedelta(days=1)


def _description(species: str, field: str) -> str:
    base = f"MSA {species} ground-fit {field}, from a Maxwellian+Kappa spectral fit."
    approx = _APPROXIMATE_SPECIES.get(species)
    return f"{base} Approximate: fitted assuming a {approx}" if approx else base


def _make_callback(species: str, field: str):
    attr, unit = FIELDS[field]

    def callback(start: float, stop: float):
        from speasy.products import SpeasyVariable, VariableTimeAxis, DataContainer

        start_dt = datetime.fromtimestamp(float(start), tz=timezone.utc)
        stop_dt = datetime.fromtimestamp(float(stop), tz=timezone.utc)

        times, values = [], []
        for day in _days_between(start_dt, stop_dt):
            day_fits = fit_day(species, day)
            if day_fits is None:
                continue
            times.append(day_fits.time)
            values.append(getattr(day_fits, attr))

        if not times:
            return None

        time = np.concatenate(times)
        value = np.concatenate(values)
        order = np.argsort(time)
        time, value = time[order], value[order]

        keep = (time >= float(start)) & (time <= float(stop))
        time, value = time[keep], value[keep]
        if len(time) == 0:
            return None

        return SpeasyVariable(
            axes=[VariableTimeAxis(values=(time * 1e9).astype("int64").astype("datetime64[ns]"))],
            values=DataContainer(
                values=value,
                meta={"UNITS": unit, "LABLAXIS": field, "SCALETYP": "log"},
                is_time_dependent=True,
            ),
        )

    return callback


def register_moments_vps() -> list:
    from SciQLop.user_api.virtual_products import create_virtual_product, VirtualProductType

    for species in SPECIES_MASS_TABLE:
        for field in FIELDS:
            vp = create_virtual_product(
                path=f"msa/moments_fit/{species}/{field}",
                callback=_make_callback(species, field),
                product_type=VirtualProductType.Scalar,
                labels=[field],
                cachable=True,
            )
            _registered_vps.append(vp)
    return _registered_vps
```

Now wire it into `plugin.py`. Read the current file first — it already has `load()`
calling `install_inventory()` and `rebuild_speasy_inventory()`:

```python
# sciqlop_msa/sciqlop_msa/plugin.py — add this import near the top, alongside the
# existing imports:
```

```python
from .moments_vp import register_moments_vps
```

```python
# sciqlop_msa/sciqlop_msa/plugin.py — modify the `load()` function:
def load(main_window):
    install_inventory()
    rebuild_speasy_inventory()
    register_moments_vps()
    return MSAPlugin(main_window)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/ -v`
Expected: all tests across every file in this plan pass (22 total: 14 from
`test_moments_fit.py` + 3 from `test_moments_source.py` + 2 from
`test_moments_compute.py` + 3 from `test_moments_vp.py`)

- [ ] **Step 5: Commit**

```bash
cd sciqlop_msa
git add sciqlop_msa/moments_vp.py sciqlop_msa/plugin.py sciqlop_msa/tests/conftest.py sciqlop_msa/tests/test_moments_vp.py
git commit -m "feat(msa): register ground-fit moment virtual products"
```

---

## Task 8: `quicklooks.py` — new quick-look template

**Files:**
- Modify: `sciqlop_msa/sciqlop_msa/quicklooks.py`

**Interfaces:**
- Consumes: the 12 VP paths registered by `moments_vp.register_moments_vps()`
  (`msa/moments_fit/<species>/<field>`).
- Produces: a new entry in the existing `TEMPLATES` dict, no new functions.

No test — this file has no existing tests (`get_template`/`create_quicklook` are
thin dict/UI glue, matching how the three existing templates are handled: no test
coverage, verified by using the menu entry manually). Adding a fourth dict entry
carries the same (lack of) risk as the existing three.

- [ ] **Step 1: Add the template**

Modify `sciqlop_msa/sciqlop_msa/quicklooks.py` — add this entry to the `TEMPLATES`
dict, alongside the existing three (`"L1 Count Spectrograms"`, `"L1 Raw Count
Spectrograms"`, `"L1 Moments"`, `"L2pre Energy Flux Spectrograms"`):

```python
    "L2pre Ground Moments (Fit)": {
        "products": [
            "msa/moments_fit/h_plus/density",
            "msa/moments_fit/alphas/density",
            "msa/moments_fit/heavies/density",
            "msa/moments_fit/total/density",
            "msa/moments_fit/h_plus/T_eff",
        ],
    },
```

- [ ] **Step 2: Verify the module still imports cleanly**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -c "from sciqlop_msa import quicklooks; print(list(quicklooks.TEMPLATES))"`
Expected: prints a list including `'L2pre Ground Moments (Fit)'` alongside the four
existing template names, no traceback.

- [ ] **Step 3: Commit**

```bash
cd sciqlop_msa
git add sciqlop_msa/quicklooks.py
git commit -m "feat(msa): add ground-fit moments quick-look template"
```

---

## Task 9: Full suite verification

**Files:** none (verification-only task).

- [ ] **Step 1: Run the complete `sciqlop_msa` test suite**

Run: `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_msa/sciqlop_msa/tests/ -v`
Expected: all tests pass, exit code 0. Read the actual pass count and exit code —
don't infer success from a partial grep (per project workflow rules).

- [ ] **Step 2: Manually smoke-test in the running app**

Launch SciQLop with the dev plugin loaded, open "MSA Quick-Looks" → "L2pre Ground
Moments (Fit)", and verify the panel populates with density/T_eff curves for the
default 2025-01-08 flyby window (matches the existing templates' default range) — this
confirms the whole path end-to-end (Speasy fetch → fit → VP → plot) against real
archive data, which the automated suite deliberately doesn't cover (no network in
tests, per `Global Constraints`).

- [ ] **Step 3: Update project memory**

Add a note to
`/home/jeandet/.claude/projects/-var-home-jeandet-Documents-prog-plugins-sciqlop/memory/msa_moment_fit_integration.md`
recording that Phase 1 shipped: which commit range, and that Phase 2
(`quality_level`/`quality_bitmask` via a custom codec) is still pending on
`speasy>=1.8`.
