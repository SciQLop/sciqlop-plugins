import numpy as np
import pytest

from sciqlop_pyspedas.regrid import spd_pgs_regrid

reference = pytest.importorskip("pyspedas.particles.spd_part_products.spd_pgs_regrid")


def _fac_data(n_energy=8, n_angle=64, seed=0):
    rng = np.random.default_rng(seed)
    shape = (n_energy, n_angle)
    return {
        "data": rng.uniform(0, 1e6, shape),
        "bins": (rng.uniform(size=shape) > 0.2).astype(float),
        "phi": rng.uniform(0, 360, shape),
        "theta": rng.uniform(-90, 90, shape),
        "energy": np.repeat(np.geomspace(2.0, 3e4, n_energy)[:, None], n_angle, axis=1),
        "denergy": np.ones(shape),
        "orig_energy": np.geomspace(2.0, 3e4, n_energy),
        "charge": 1.0,
        "mass": 0.0104,
    }


def test_matches_pyspedas():
    expected = reference.spd_pgs_regrid(_fac_data(), [32, 16])
    actual = spd_pgs_regrid(_fac_data(), [32, 16])
    assert actual.keys() == expected.keys()
    for key in expected:
        np.testing.assert_array_equal(actual[key], expected[key], err_msg=key)
