"""Vectorised drop-in for pyspedas's mms_pgs_make_e_spec.

pyspedas 2.1/2.2 rebins each sample with a Python loop over every
(energy, angle) bin and a Python-level nearest-neighbour search: ~0.7 s per
FPI distribution, i.e. ~10 min per hour of fast ions before any pa/gyro work.
Same result, one numpy pass."""
import numpy as np


def mms_pgs_make_e_spec(data_in):
    data = data_in.copy()
    # In place on purpose, as pyspedas does: pa/gyro are built from this array next.
    data['data'][data['bins'] == 0] = 0.0
    outtable = data['orig_energy']
    n_angle = data['data'].shape[1]
    nearest = np.abs(data['energy'][:, :, None] - outtable).argmin(axis=-1)
    outbins = np.zeros(data['data'].shape)
    np.add.at(outbins, (nearest, np.arange(n_angle)), data['data'])
    outbins[(outtable < np.min(data['energy'])) | (outtable > np.max(data['energy']))] = np.nan
    if n_angle > 1:
        return outtable, np.sum(outbins, axis=1) / np.sum(data['bins'], axis=1)
    return outtable, outbins / data['bins']


def install() -> None:
    from pyspedas.projects.mms.particles import mms_part_products

    mms_part_products.mms_pgs_make_e_spec = mms_pgs_make_e_spec
