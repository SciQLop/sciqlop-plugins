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
