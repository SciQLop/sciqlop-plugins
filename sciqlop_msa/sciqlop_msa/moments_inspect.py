"""What one record's moment fit saw and produced, as arrays ready to plot.

Pure functions over the cached DayFits: nothing here refits, so the fit inspector
can follow a slider at interactive speed.
"""
import logging
from dataclasses import dataclass
from datetime import date

import numpy as np

from .moments_compute import DayFits, fit_day
from .moments_fit import SPECIES_MASS_TABLE, accepted_fit, flux_to_phase_space_density, model_components, \
    usable_points
from .moments_source import DaySpectra, fetch_day

log = logging.getLogger(__name__)

POPULATIONS = ("core", "warm", "hot", "halo")
BEST_CURVE_LABELS = POPULATIONS + ("total",)
CANDIDATE_MODELS = ("max_kap", "2max", "2max_kap")


@dataclass
class LoadedDay:
    spectra: "DaySpectra | None"
    fits: "DayFits | None"
    error: "str | None"


def load_day(species: str, day: date) -> LoadedDay:
    try:
        spectra = fetch_day(species, day)
        fits = fit_day(species, day) if spectra is not None else None
    except Exception as e:
        log.exception("Failed to load MSA %s fits for %s", species, day)
        return LoadedDay(None, None, f"Failed to load MSA {species} on {day}: {e}")
    if fits is None:
        return LoadedDay(None, None, f"No MSA {species} data on {day}.")
    return LoadedDay(spectra, fits, None)


def inspectable_records(fits: DayFits, fitted_only: bool) -> list:
    return [i for i, candidates in enumerate(fits.candidates) if candidates or not fitted_only]


@dataclass
class RecordView:
    time: float
    energy: np.ndarray
    flux: np.ndarray
    f_obs: np.ndarray
    used: np.ndarray
    candidates: list

    @property
    def accepted(self):
        return accepted_fit(self.candidates)


def record_view(spectra: DaySpectra, fits: DayFits, index: int, species: str) -> RecordView:
    A, q = SPECIES_MASS_TABLE[species]
    flux = spectra.flux[index]
    f_obs = flux_to_phase_space_density(spectra.energy, flux, A, q)
    return RecordView(time=float(spectra.time[index]), energy=spectra.energy, flux=flux, f_obs=f_obs,
                      used=usable_points(flux, f_obs), candidates=list(fits.candidates[index]))


def _nan_columns(view: RecordView, count: int) -> np.ndarray:
    return np.full((len(view.energy), count), np.nan)


def best_curves(view: RecordView, A: float) -> np.ndarray:
    """Columns follow BEST_CURVE_LABELS; populations the best model lacks stay NaN."""
    curves = _nan_columns(view, len(BEST_CURVE_LABELS))
    if not view.candidates:
        return curves
    components = model_components(view.candidates[0].params, view.energy, A)
    for name, values in components.items():
        curves[:, POPULATIONS.index(name)] = values
    curves[:, -1] = sum(components.values())
    return curves


def candidate_totals(view: RecordView, A: float) -> np.ndarray:
    """Columns follow CANDIDATE_MODELS; a model that did not converge stays NaN."""
    totals = _nan_columns(view, len(CANDIDATE_MODELS))
    for candidate in view.candidates:
        totals[:, CANDIDATE_MODELS.index(candidate.model)] = sum(
            model_components(candidate.params, view.energy, A).values())
    return totals
