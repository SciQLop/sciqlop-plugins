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
