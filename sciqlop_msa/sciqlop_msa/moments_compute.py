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

from .moments_fit import SPECIES_MASS_TABLE, best_fit, flux_to_phase_space_density
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
        f_obs = flux_to_phase_space_density(spectra.energy, row, A, q)
        result = best_fit(spectra.energy, f_obs, mask, A, q)
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
