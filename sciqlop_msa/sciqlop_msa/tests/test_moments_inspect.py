from datetime import date
from unittest.mock import patch

import numpy as np

from sciqlop_msa import moments_fit, moments_inspect
from sciqlop_msa.tests.test_moments_compute import _synthetic_day_spectra

A = moments_fit.SPECIES_MASS_TABLE["h_plus"][0]


def _view(index=0):
    from sciqlop_msa import moments_compute

    spectra = _synthetic_day_spectra()
    with patch("sciqlop_msa.moments_compute.fetch_day", return_value=spectra):
        fits = moments_compute._fit_day_uncached("h_plus", date(2025, 1, 8))
    return moments_inspect.record_view(spectra, fits, index, "h_plus")


def test_record_view_shows_the_phase_space_density_and_points_the_fit_used():
    view = _view()

    np.testing.assert_allclose(view.f_obs, moments_fit.flux_to_phase_space_density(view.energy, view.flux, A, 1))
    np.testing.assert_array_equal(view.used, view.flux >= moments_fit.NOISE_FLUX_THRESHOLD)
    assert view.used.sum() >= 6
    assert view.accepted is view.candidates[0]


def test_record_without_usable_points_has_no_candidates_and_no_accepted_fit():
    view = _view(index=1)

    assert not view.used.any()
    assert view.candidates == []
    assert view.accepted is None


def test_best_curves_put_each_population_in_its_column_and_absent_ones_as_nan():
    view = _view()
    columns = moments_inspect.BEST_CURVE_LABELS

    curves = moments_inspect.best_curves(view, A)

    assert curves.shape == (len(view.energy), len(columns))
    assert view.candidates[0].model == "max_kap"
    assert np.isnan(curves[:, columns.index("warm")]).all()
    assert np.isnan(curves[:, columns.index("hot")]).all()
    np.testing.assert_allclose(curves[:, columns.index("total")],
                               curves[:, columns.index("core")] + curves[:, columns.index("halo")])


def test_candidate_totals_has_one_column_per_model_and_nan_for_a_failed_one():
    view = _view()
    view.candidates = [c for c in view.candidates if c.model != "2max_kap"]

    totals = moments_inspect.candidate_totals(view, A)

    assert totals.shape == (len(view.energy), len(moments_inspect.CANDIDATE_MODELS))
    assert np.isnan(totals[:, moments_inspect.CANDIDATE_MODELS.index("2max_kap")]).all()
    assert np.isfinite(totals[:, moments_inspect.CANDIDATE_MODELS.index("max_kap")]).all()


def test_curves_of_a_record_without_candidates_are_all_nan():
    view = _view(index=1)

    assert np.isnan(moments_inspect.best_curves(view, A)).all()
    assert np.isnan(moments_inspect.candidate_totals(view, A)).all()


def test_load_day_reports_a_failed_fetch_instead_of_raising():
    def boom(species, day):
        raise ValueError("Can't find a provider")

    with patch("sciqlop_msa.moments_inspect.fetch_day", boom):
        loaded = moments_inspect.load_day("h_plus", date(2025, 1, 8))

    assert loaded.spectra is None and loaded.fits is None
    assert "Can't find a provider" in loaded.error


def test_load_day_returns_spectra_and_fits():
    spectra = _synthetic_day_spectra()
    with patch("sciqlop_msa.moments_inspect.fetch_day", return_value=spectra), \
            patch("sciqlop_msa.moments_inspect.fit_day", return_value="fits"):
        loaded = moments_inspect.load_day("h_plus", date(2025, 1, 8))

    assert (loaded.spectra, loaded.fits, loaded.error) == (spectra, "fits", None)


def test_load_day_without_data_says_so():
    with patch("sciqlop_msa.moments_inspect.fetch_day", return_value=None):
        loaded = moments_inspect.load_day("h_plus", date(2020, 1, 1))

    assert loaded.fits is None
    assert "No MSA h_plus data on 2020-01-01" in loaded.error


def test_inspectable_records_skip_records_without_candidates_on_request():
    from sciqlop_msa import moments_compute

    with patch("sciqlop_msa.moments_compute.fetch_day", return_value=_synthetic_day_spectra()):
        fits = moments_compute._fit_day_uncached("h_plus", date(2025, 1, 8))

    assert moments_inspect.inspectable_records(fits, fitted_only=True) == [0]
    assert moments_inspect.inspectable_records(fits, fitted_only=False) == [0, 1]


def test_candidate_totals_has_a_column_for_every_model():
    assert moments_inspect.CANDIDATE_MODELS == tuple(moments_fit.FIT_MODELS)


def test_load_day_fits_with_the_chosen_model():
    with patch("sciqlop_msa.moments_inspect.fetch_day", return_value=_synthetic_day_spectra()), \
            patch("sciqlop_msa.moments_inspect.fit_day", return_value="fits") as fit_day:
        moments_inspect.load_day("h_plus", date(2025, 1, 8), "kap")

    assert fit_day.call_args.args == ("h_plus", date(2025, 1, 8), "kap")
