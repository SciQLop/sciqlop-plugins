import numpy as np

from sciqlop_pyspedas.espec import mms_pgs_make_e_spec


def reference_e_spec(data_in):
    """pyspedas 2.1.5 mms_pgs_make_e_spec, verbatim minus comments."""
    data = data_in.copy()
    zero_bins = np.argwhere(data['bins'] == 0)
    if zero_bins.size != 0:
        for item in zero_bins:
            data['data'][item[0], item[1]] = 0.0
    outtable = data['orig_energy']
    outbins = np.zeros([len(data['data'][:, 0]), len(data['data'][0, :])])
    erange = [np.min(data['energy']), np.max(data['energy'])]
    for ang_idx in range(0, len(data['data'][0, :])):
        etable = data['energy'][:, ang_idx]
        for binidx in range(0, len(outtable)):
            if data['data'][binidx, ang_idx] != 0.0:
                this_en = min(np.array(outtable), key=lambda p: sum((p - [etable[binidx]])**2))
                whereen = np.argwhere(outtable == this_en)
                outbins[whereen, ang_idx] += data['data'][binidx, ang_idx]
    where_out_of_erange = np.argwhere((outtable < erange[0]) | (outtable > erange[1]))
    if where_out_of_erange.size != 0:
        outbins[where_out_of_erange] = np.nan
    if len(data['data'][0, :]) > 1:
        ave = np.sum(outbins, axis=1)/np.sum(data['bins'], axis=1)
    else:
        ave = outbins/data['bins']
    return outtable, ave


def _clean_data(n_energy, n_angle, seed=0):
    rng = np.random.default_rng(seed)
    table = np.geomspace(2.0, 3e4, n_energy)
    # Per-angle energies jittered off the table, as after a bulk-velocity shift.
    energy = table[:, None] * rng.uniform(0.8, 1.25, (n_energy, n_angle))
    bins = (rng.uniform(size=(n_energy, n_angle)) > 0.2).astype(float)
    data = rng.uniform(0, 1e6, (n_energy, n_angle))
    return {"data": data, "bins": bins, "energy": energy, "orig_energy": table}


def test_matches_pyspedas_reference():
    expected_in, actual_in = _clean_data(32, 64), _clean_data(32, 64)
    expected = reference_e_spec(expected_in)
    actual = mms_pgs_make_e_spec(actual_in)
    np.testing.assert_array_equal(actual[0], expected[0])
    np.testing.assert_allclose(actual[1], expected[1], rtol=1e-12, equal_nan=True)


def test_zeroes_inactive_bins_in_place_like_pyspedas():
    # pa/gyro spectra are built from the same clean_data afterwards.
    expected_in, actual_in = _clean_data(16, 8), _clean_data(16, 8)
    reference_e_spec(expected_in)
    mms_pgs_make_e_spec(actual_in)
    np.testing.assert_array_equal(actual_in["data"], expected_in["data"])


def test_single_angle():
    expected = reference_e_spec(_clean_data(16, 1))
    actual = mms_pgs_make_e_spec(_clean_data(16, 1))
    np.testing.assert_allclose(actual[1], expected[1], rtol=1e-12, equal_nan=True)
