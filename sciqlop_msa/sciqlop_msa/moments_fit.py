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
# Real spectra fit to reduced chi2 ~ 0.002-0.09; pure-noise "fits" land at ~3.7-4.4.
# Reject anything above this ceiling as an unconverged/noise fit rather than a real one.
CHI2_MAX = 1.0

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


def kinetic_energy_eV(E_per_charge: np.ndarray, q: int) -> np.ndarray:
    """The MSA energy table is in volts (energy per charge): a q-charged ion at E volts
    has q*E eV of kinetic energy. The models must see kinetic energy."""
    return q * E_per_charge


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


def _reduced_chi2(f_obs: np.ndarray, f_model: np.ndarray, n_params: int) -> float:
    residual = _log_safe(f_obs) - _log_safe(np.maximum(f_model, 1e-300))
    return float(np.sum(residual ** 2) / max(len(f_obs) - n_params, 1))


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


def _single_population_fit(model: str, log_model, p0: list, bounds: tuple, params, Eg, fg,
                           f_model) -> "FitResult | None":
    try:
        popt, _ = curve_fit(log_model, Eg, np.log(fg), p0=p0, bounds=bounds, maxfev=10000)
    except (RuntimeError, ValueError):
        return None
    p = params(popt)
    if p is None:
        return None
    return FitResult(n_tot=p["nc"], T_c=p["Tc"], T_eff=p["Tc"], model=model,
                     chi2=_reduced_chi2(fg, f_model(Eg, p), len(p0)), params=p)


def fit_max(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray, A: float) -> "FitResult | None":
    """Fit a single Maxwellian over every usable point."""
    Eg, fg = energy[mask], f_obs[mask]
    if len(Eg) < 3:
        return None
    n0, T0 = _init_maxwell_slope(energy, f_obs, mask, 0.0, np.inf, A)
    return _single_population_fit(
        "max",
        lambda E, log_n, log_T: _log_safe(maxwellian(E, 10 ** log_n, 10 ** log_T, A)),
        [np.log10(n0), np.log10(min(T0, 3e4))], ([-3, 0], [4, 4.5]),
        lambda popt: dict(model="max", nc=10 ** popt[0], Tc=10 ** popt[1]),
        Eg, fg, lambda E, p: maxwellian(E, p["nc"], p["Tc"], A))


def fit_kap(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray, A: float) -> "FitResult | None":
    """Fit a single kappa distribution over every usable point; a kappa railed at its
    upper bound is a Maxwellian, and is rejected like in the multi-population fits."""
    Eg, fg = energy[mask], f_obs[mask]
    if len(Eg) < 4:
        return None
    n0, T0 = _init_maxwell_slope(energy, f_obs, mask, 0.0, np.inf, A)
    kap0 = _init_kappa_slope(energy, f_obs, mask, 800, 30000)

    def params(popt):
        if popt[2] >= 11.9:
            return None
        return dict(model="kap", nc=10 ** popt[0], Tc=10 ** popt[1], kappa=popt[2])

    return _single_population_fit(
        "kap",
        lambda E, log_n, log_T, kappa: _log_safe(kappa_distribution(E, 10 ** log_n, 10 ** log_T, kappa, A)),
        [np.log10(n0), np.log10(min(T0, 3e4)), kap0], ([-3, 0, 1.55], [4, 4.5, 12]),
        params, Eg, fg, lambda E, p: kappa_distribution(E, p["nc"], p["Tc"], p["kappa"], A))


def fit_max_kap(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray,
                A: float) -> "FitResult | None":
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


def fit_2max(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray,
            A: float) -> "FitResult | None":
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
    if Th_f > 20000:
        return None

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
                 A: float) -> "FitResult | None":
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


def usable_points(flux: np.ndarray, f_obs: np.ndarray) -> np.ndarray:
    """Points a fit may use: above the instrument noise floor, finite and positive."""
    return (flux >= NOISE_FLUX_THRESHOLD) & np.isfinite(f_obs) & (f_obs > 0)


FIT_MODELS = {"max": fit_max, "kap": fit_kap, "max_kap": fit_max_kap, "2max": fit_2max,
              "2max_kap": fit_2max_kap}
# "auto" picks among the multi-population models only, as it always has; a single
# population is fitted only when asked for.
AUTO_MODELS = ("max_kap", "2max", "2max_kap")
MODEL_CHOICES = {
    "Auto (best χ²)": "auto",
    "Maxwellian": "max",
    "Kappa": "kap",
    "Maxwellian + kappa": "max_kap",
    "2 Maxwellians": "2max",
    "2 Maxwellians + kappa": "2max_kap",
}


def fit_candidates(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray,
                   A: float, model: str = "auto") -> list:
    """Every candidate model that converged, best (lowest reduced chi-squared) first."""
    names = AUTO_MODELS if model == "auto" else (model,)
    results = (FIT_MODELS[name](energy, f_obs, mask, A) for name in names)
    return sorted((r for r in results if r is not None), key=lambda r: r.chi2)


def best_fit(energy: np.ndarray, f_obs: np.ndarray, mask: np.ndarray,
            A: float) -> "FitResult | None":
    candidates = fit_candidates(energy, f_obs, mask, A)
    return candidates[0] if candidates else None


def accepted_fit(candidates: list) -> "FitResult | None":
    if candidates and candidates[0].chi2 <= CHI2_MAX:
        return candidates[0]
    return None


_POPULATIONS = {
    "max": {"core": ("maxwellian", "nc", "Tc")},
    "kap": {"core": ("kappa", "nc", "Tc")},
    "max_kap": {"core": ("maxwellian", "nc", "Tc"), "halo": ("kappa", "nh", "Th")},
    "2max": {"core": ("maxwellian", "nc", "Tc"), "hot": ("maxwellian", "nh", "Th")},
    "2max_kap": {"core": ("maxwellian", "nc", "Tc"), "warm": ("maxwellian", "nw", "Tw"),
                 "halo": ("kappa", "nh", "Th")},
}


def model_components(params: dict, E_eV: np.ndarray, A: float) -> dict:
    """Phase-space density of each population of a fit, by population name."""

    def evaluate(shape, n_key, T_key):
        if shape == "kappa":
            return kappa_distribution(E_eV, params[n_key], params[T_key], params["kappa"], A)
        return maxwellian(E_eV, params[n_key], params[T_key], A)

    return {name: evaluate(*spec) for name, spec in _POPULATIONS[params["model"]].items()}


def effective_temperature(params: dict) -> float:
    """Density-weighted effective temperature across all populations in a fit."""
    model = params["model"]
    if model in ("max", "kap"):
        return params["Tc"]
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
