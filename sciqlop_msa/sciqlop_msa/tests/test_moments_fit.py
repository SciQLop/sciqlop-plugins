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

    result = moments_fit.fit_max_kap(energy, f_obs, mask, A)

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

    result = moments_fit.fit_max_kap(energy, f_obs, mask, 1.00728)

    assert result is None


def test_fit_2max_recovers_two_independent_maxwellian_populations():
    energy = np.logspace(0, np.log10(39200), 64)
    n_c, T_c = 20.0, 150.0
    n_h, T_h = 2.0, 1500.0
    A, q = 1.00728, 1

    f_true = moments_fit.maxwellian(energy, n_c, T_c, A) + moments_fit.maxwellian(energy, n_h, T_h, A)
    rng = np.random.default_rng(7)
    f_obs = f_true * rng.lognormal(mean=0.0, sigma=0.05, size=f_true.shape)
    mask = np.ones_like(energy, dtype=bool)

    result = moments_fit.fit_2max(energy, f_obs, mask, A)

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

    result = moments_fit.best_fit(energy, f_obs, mask, A)

    assert result is not None
    assert result.model == "max_kap"


def test_best_fit_returns_none_when_all_models_fail():
    energy = np.logspace(0, np.log10(39200), 64)
    f_obs = np.full(64, np.nan)
    mask = np.zeros(64, dtype=bool)

    assert moments_fit.best_fit(energy, f_obs, mask, 1.00728) is None


def test_fit_2max_rejects_unphysically_railed_second_population():
    """A single Maxwellian core plus a flat instrument-noise floor leaves no
    real second population: the residual above the core is flat (non-decaying),
    so no finite temperature explains it and curve_fit pins Th at its own upper
    bound (10**4.5 eV ~= 31622.78), wider than the 20000 eV ceiling fit_max_kap
    and fit_2max_kap enforce. This is the unconverged-fit signature the reviewer
    flagged; fit_2max must reject it rather than return a railed value."""
    energy = np.logspace(0, np.log10(39200), 64)
    A = 1.00728
    n_c, T_c = 20.0, 150.0
    f_obs = moments_fit.maxwellian(energy, n_c, T_c, A) + 1e-12
    mask = np.ones_like(energy, dtype=bool)

    result = moments_fit.fit_2max(energy, f_obs, mask, A)

    assert result is None


def test_chi2_max_is_a_sane_positive_threshold():
    assert isinstance(moments_fit.CHI2_MAX, float)
    assert 0 < moments_fit.CHI2_MAX < 100


def _max_kap_spectrum():
    energy = np.logspace(0, np.log10(39200), 64)
    A = 1.00728
    f_true = (
        moments_fit.maxwellian(energy, 45.0, 280.0, A)
        + moments_fit.kappa_distribution(energy, 0.08, 5000.0, 3.5, A)
    )
    f_obs = f_true * np.random.default_rng(42).lognormal(mean=0.0, sigma=0.05, size=64)
    return energy, f_obs, np.ones(64, dtype=bool), A


def test_model_components_add_up_to_the_fitted_model():
    energy, f_obs, mask, A = _max_kap_spectrum()
    result = moments_fit.fit_max_kap(energy, f_obs, mask, A)
    p = result.params

    components = moments_fit.model_components(p, energy, A)

    assert set(components) == {"core", "halo"}
    expected = (moments_fit.maxwellian(energy, p["nc"], p["Tc"], A)
                + moments_fit.kappa_distribution(energy, p["nh"], p["Th"], p["kappa"], A))
    np.testing.assert_allclose(components["core"] + components["halo"], expected)


def test_fit_candidates_are_sorted_by_chi2_and_best_fit_is_the_first():
    energy, f_obs, mask, A = _max_kap_spectrum()

    candidates = moments_fit.fit_candidates(energy, f_obs, mask, A)

    assert len(candidates) >= 2
    assert [c.chi2 for c in candidates] == sorted(c.chi2 for c in candidates)
    assert moments_fit.best_fit(energy, f_obs, mask, A).model == candidates[0].model


def test_accepted_fit_rejects_a_best_candidate_above_chi2_max():
    def fit(chi2):
        return moments_fit.FitResult(n_tot=1.0, T_c=1.0, T_eff=1.0, model="2max", chi2=chi2, params={})

    assert moments_fit.accepted_fit([fit(0.01), fit(0.5)]).chi2 == 0.01
    assert moments_fit.accepted_fit([fit(moments_fit.CHI2_MAX * 2)]) is None
    assert moments_fit.accepted_fit([]) is None


def test_usable_points_drop_noise_floor_non_finite_and_non_positive_points():
    floor = moments_fit.NOISE_FLUX_THRESHOLD
    flux = np.array([floor * 10, floor, floor / 10, np.nan, floor * 10])
    f_obs = np.array([1.0, 1.0, 1.0, np.nan, 0.0])

    assert moments_fit.usable_points(flux, f_obs).tolist() == [True, True, False, False, False]


def _noisy(f_true):
    return f_true * np.random.default_rng(7).lognormal(mean=0.0, sigma=0.05, size=f_true.shape)


def test_fit_max_recovers_a_single_maxwellian():
    energy, A = np.logspace(0, np.log10(39200), 64), 1.00728
    f_obs = _noisy(moments_fit.maxwellian(energy, 12.0, 450.0, A))
    usable = f_obs > 1e-30  # far tail underflows to zero

    result = moments_fit.fit_max(energy, f_obs, usable, A)

    assert result.model == "max"
    assert result.n_tot == pytest.approx(12.0, rel=0.05)
    assert result.T_c == result.T_eff == pytest.approx(450.0, rel=0.05)


def test_fit_kap_recovers_a_single_kappa():
    energy, A = np.logspace(0, np.log10(39200), 64), 1.00728
    f_obs = _noisy(moments_fit.kappa_distribution(energy, 3.0, 800.0, 4.0, A))

    result = moments_fit.fit_kap(energy, f_obs, np.ones(64, dtype=bool), A)

    assert result.model == "kap"
    assert result.n_tot == pytest.approx(3.0, rel=0.05)
    assert result.T_c == pytest.approx(800.0, rel=0.05)
    assert result.params["kappa"] == pytest.approx(4.0, rel=0.1)


def test_single_population_components_are_one_core():
    energy, A = np.logspace(0, 4, 8), 1.00728
    kap = moments_fit.model_components(dict(model="kap", nc=3.0, Tc=800.0, kappa=4.0), energy, A)
    mx = moments_fit.model_components(dict(model="max", nc=12.0, Tc=450.0), energy, A)

    np.testing.assert_allclose(kap["core"], moments_fit.kappa_distribution(energy, 3.0, 800.0, 4.0, A))
    np.testing.assert_allclose(mx["core"], moments_fit.maxwellian(energy, 12.0, 450.0, A))
    assert set(kap) == set(mx) == {"core"}


def test_a_chosen_model_is_the_only_candidate_and_auto_is_unchanged():
    energy, f_obs, mask, A = _max_kap_spectrum()

    assert [c.model for c in moments_fit.fit_candidates(energy, f_obs, mask, A, model="kap")] == ["kap"]
    assert {c.model for c in moments_fit.fit_candidates(energy, f_obs, mask, A)} <= {"max_kap", "2max", "2max_kap"}
    assert set(moments_fit.MODEL_CHOICES.values()) == {"auto"} | set(moments_fit.FIT_MODELS)


def test_noise_floor_choices_map_to_a_flux_threshold_and_a_weighting():
    assert moments_fit.noise_floor("legacy") == (1e5, False)
    assert moments_fit.noise_floor("2") == (2 * moments_fit.FLUX_PER_COUNT, True)
    assert "legacy" in moments_fit.FLOOR_CHOICES.values()


def test_poisson_sigma_is_the_relative_error_of_the_counts():
    counts = np.array([1.0, 4.0, 100.0])

    sigma = moments_fit.poisson_sigma(counts * moments_fit.FLUX_PER_COUNT)

    np.testing.assert_allclose(sigma, [1.0, 0.5, 0.1])


def test_usable_points_follow_the_chosen_floor():
    flux = np.array([3e3, 5e4, 2e5])
    f_obs = np.ones(3)

    assert moments_fit.usable_points(flux, f_obs).tolist() == [False, False, True]
    assert moments_fit.usable_points(flux, f_obs, floor_flux=2e3).tolist() == [True, True, True]


def test_weighted_fit_of_poisson_counts_recovers_the_plasma_with_chi2_near_one():
    energy, A = np.logspace(0, np.log10(39200), 64), 1.00728
    f_true = (moments_fit.maxwellian(energy, 45.0, 280.0, A)
              + moments_fit.kappa_distribution(energy, 0.08, 5000.0, 3.5, A))
    m, e_J = moments_fit.ion_mass_kg(A), energy * moments_fit.ELEMENTARY_CHARGE
    expected_counts = f_true * 2 * e_J ** 2 / (m ** 2 * 1e4) / moments_fit.FLUX_PER_COUNT
    counts = np.random.default_rng(3).poisson(expected_counts).astype(float)
    flux = counts * moments_fit.FLUX_PER_COUNT
    f_obs = moments_fit.flux_to_phase_space_density(energy, flux, A, 1)
    mask = moments_fit.usable_points(flux, f_obs, floor_flux=2 * moments_fit.FLUX_PER_COUNT)

    result = moments_fit.fit_max_kap(energy, f_obs, mask, A, sigma=moments_fit.poisson_sigma(flux))

    assert result.params["nc"] == pytest.approx(45.0, rel=0.05)
    assert result.params["Tc"] == pytest.approx(280.0, rel=0.05)
    assert 0.3 < result.chi2 < 3.0
