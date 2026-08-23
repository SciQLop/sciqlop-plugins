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
    """flux holds RAW instrument differential-directional-energy flux
    (cm^-2 s^-1 sr^-1 eV^-1), not phase-space density."""

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
