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
