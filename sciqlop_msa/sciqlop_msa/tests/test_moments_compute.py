from datetime import date
from unittest.mock import patch

import numpy as np
import pytest

from sciqlop_msa import moments_fit
from sciqlop_msa.moments_source import DaySpectra


def _synthetic_day_spectra():
    """DaySpectra.flux holds RAW instrument flux (cm^-2 s^-1 sr^-1 eV^-1), not
    phase-space density. Build the target phase-space-density spectrum first,
    then invert flux_to_phase_space_density to get a realistic raw-flux row —
    this exercises the actual unit-conversion step inside _fit_day_uncached
    instead of bypassing it (a synthetic row built by calling maxwellian/
    kappa_distribution directly and handed to DaySpectra.flux as-is would
    silently skip that conversion and not catch a missing/wrong call)."""
    energy = np.logspace(0, np.log10(39200), 64)
    n_c, T_c = 45.0, 280.0
    n_h, T_h, kappa_true = 0.08, 5000.0, 3.5
    A, q = 1.00728, 1
    rng = np.random.default_rng(42)
    f_obs_true = (
        moments_fit.maxwellian(energy, n_c, T_c, A)
        + moments_fit.kappa_distribution(energy, n_h, T_h, kappa_true, A)
    ) * rng.lognormal(mean=0.0, sigma=0.05, size=64)
    m = moments_fit.ion_mass_kg(A)
    E_kin_J = q * energy * moments_fit.ELEMENTARY_CHARGE
    good_row = f_obs_true * (2.0 * E_kin_J ** 2) / (m ** 2 * 1e4)
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


def _noise_day_spectra():
    """Pure log-uniform random raw flux in [1e5, 1e8] cm^-2 s^-1 sr^-1 eV^-1 —
    realistic instrument-flux magnitude that survives NOISE_FLUX_THRESHOLD, but
    NOT built from maxwellian/kappa_distribution, so it carries no real physical
    population. Without a chi2 ceiling, best_fit still "succeeds" on this (reduced
    chi2 ~ 3.5-5.6, verified against real archive spectra which fit at ~0.002-0.09)
    and returns plausible-looking densities — this is the noise-fit regression the
    CHI2_MAX cutoff exists to catch."""
    energy = np.logspace(0, np.log10(39200), 64)
    rng = np.random.default_rng(1)
    row = 10 ** rng.uniform(np.log10(1e5), np.log10(1e8), size=64)
    time = np.array([1736300000.0])
    return DaySpectra(time=time, energy=energy, flux=row[np.newaxis, :])


def test_fit_day_uncached_rejects_noise_fit_above_chi2_ceiling():
    from sciqlop_msa import moments_compute

    with patch("sciqlop_msa.moments_compute.fetch_day", return_value=_noise_day_spectra()):
        result = moments_compute._fit_day_uncached("h_plus", date(2025, 1, 8))

    assert result is not None
    assert np.isnan(result.n_tot[0])
    assert result.model[0] == ""


def test_fit_day_keeps_every_candidate_of_every_record_for_inspection():
    from sciqlop_msa import moments_compute

    with patch("sciqlop_msa.moments_compute.fetch_day", return_value=_synthetic_day_spectra()):
        result = moments_compute._fit_day_uncached("h_plus", date(2025, 1, 8))

    assert result.candidates[0][0].model == result.model[0]
    assert len(result.candidates[0]) >= 2
    assert result.candidates[1] == []


def test_rejected_noise_fit_candidates_are_still_kept_for_inspection():
    from sciqlop_msa import moments_compute

    with patch("sciqlop_msa.moments_compute.fetch_day", return_value=_noise_day_spectra()):
        result = moments_compute._fit_day_uncached("h_plus", date(2025, 1, 8))

    assert result.model[0] == ""
    assert result.candidates[0][0].chi2 > moments_fit.CHI2_MAX


def test_fit_day_with_a_chosen_model_fits_only_that_model():
    from sciqlop_msa import moments_compute

    with patch("sciqlop_msa.moments_compute.fetch_day", return_value=_synthetic_day_spectra()):
        result = moments_compute._fit_day_uncached("h_plus", date(2025, 1, 8), model="kap")

    assert [c.model for c in result.candidates[0]] == ["kap"]
    assert result.model[0] in ("kap", "")


def test_each_model_has_its_own_cached_day(monkeypatch):
    from sciqlop_msa import moments_compute
    calls = []
    monkeypatch.setattr(moments_compute, "_fit_day_uncached",
                        lambda species, day, model="auto", floor="legacy": calls.append(model) or model)

    assert moments_compute.fit_day("h_plus", date(2025, 1, 8), "kap") == "kap"
    assert moments_compute.fit_day("h_plus", date(2025, 1, 8), "2max") == "2max"
    assert moments_compute.fit_day("h_plus", date(2025, 1, 8), "kap") == "kap"
    assert calls == ["kap", "2max"]


def test_alpha_moments_are_recovered_from_their_kinetic_energy():
    """The energy table is in volts (energy per charge): an alpha (q=2) at E volts has a
    kinetic energy of 2E. Fitting the models on E returned T/q and n/q^1.5."""
    from sciqlop_msa import moments_compute

    A, q = moments_fit.SPECIES_MASS_TABLE["alphas"]
    energy = np.logspace(0, np.log10(39200), 64)
    kinetic = q * energy
    f_true = moments_fit.maxwellian(kinetic, 2.0, 400.0, A)
    m, e_kin_J = moments_fit.ion_mass_kg(A), kinetic * moments_fit.ELEMENTARY_CHARGE
    flux = f_true * 2.0 * e_kin_J ** 2 / (m ** 2 * 1e4)
    flux = np.where(flux >= moments_fit.NOISE_FLUX_THRESHOLD, flux, np.nan)
    spectra = DaySpectra(time=np.array([1736300000.0]), energy=energy, flux=flux[np.newaxis, :])

    with patch("sciqlop_msa.moments_compute.fetch_day", return_value=spectra):
        result = moments_compute._fit_day_uncached("alphas", date(2025, 1, 8), model="max")

    assert result.T_c[0] == pytest.approx(400.0, rel=0.02)
    assert result.n_tot[0] == pytest.approx(2.0, rel=0.05)


def _low_flux_day_spectra():
    """A real-looking plasma whose flux stays under the original 10^5 floor (under 100 counts)."""
    A, q = moments_fit.SPECIES_MASS_TABLE["h_plus"]
    energy = np.logspace(0, np.log10(39200), 64)
    f_true = moments_fit.maxwellian(energy, 0.05, 300.0, A)
    m, e_J = moments_fit.ion_mass_kg(A), energy * moments_fit.ELEMENTARY_CHARGE
    counts = np.random.default_rng(5).poisson(f_true * 2 * e_J ** 2 / (m ** 2 * 1e4) / moments_fit.FLUX_PER_COUNT)
    flux = counts.astype(float) * moments_fit.FLUX_PER_COUNT
    assert np.nanmax(flux) < moments_fit.NOISE_FLUX_THRESHOLD
    return DaySpectra(time=np.array([1736300000.0]), energy=energy, flux=flux[np.newaxis, :])


def test_a_counts_floor_fits_records_the_original_floor_drops():
    from sciqlop_msa import moments_compute

    with patch("sciqlop_msa.moments_compute.fetch_day", return_value=_low_flux_day_spectra()):
        legacy = moments_compute._fit_day_uncached("h_plus", date(2025, 1, 8), model="max", floor="legacy")
        counts = moments_compute._fit_day_uncached("h_plus", date(2025, 1, 8), model="max", floor="2")

    assert legacy.candidates[0] == [] and np.isnan(legacy.n_tot[0])
    assert counts.n_tot[0] == pytest.approx(0.05, rel=0.15)
    assert counts.T_c[0] == pytest.approx(300.0, rel=0.15)


def test_each_floor_has_its_own_cached_day(monkeypatch):
    from sciqlop_msa import moments_compute
    calls = []
    monkeypatch.setattr(moments_compute, "_fit_day_uncached",
                        lambda species, day, model="auto", floor="legacy": calls.append(floor) or floor)

    assert moments_compute.fit_day("h_plus", date(2025, 1, 8), "auto", "legacy") == "legacy"
    assert moments_compute.fit_day("h_plus", date(2025, 1, 8), "auto", "2") == "2"
    assert moments_compute.fit_day("h_plus", date(2025, 1, 8), "auto", "legacy") == "legacy"
    assert calls == ["legacy", "2"]
