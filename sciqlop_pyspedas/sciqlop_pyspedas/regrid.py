"""Vectorised drop-in for pyspedas's spd_pgs_regrid.

pyspedas 2.1/2.2 queries its nearest-neighbour interpolators one grid point
at a time: 2 x 32 x 512 scalar scipy calls per distribution, ~2 s per FPI
sample. Same interpolators, one array query per energy."""
import numpy as np
from scipy.interpolate import NearestNDInterpolator


def _unit_vectors(phi_deg, theta_deg):
    phi, theta = np.radians(phi_deg), np.radians(theta_deg)
    return np.stack([np.cos(theta) * np.cos(phi), np.cos(theta) * np.sin(phi), np.sin(theta)], axis=-1)


def _angle_grid(n_phi, n_theta):
    cells = np.arange(n_phi * n_theta)
    d_phi, d_theta = 360.0 / n_phi, 180.0 / n_theta
    phi = (cells % n_phi) * d_phi + d_phi / 2.0
    theta = np.fix(cells / n_phi) * d_theta + d_theta / 2.0 - 90
    return phi, theta, d_phi


def spd_pgs_regrid(data, regrid_dimen):
    n_energy = data['energy'].shape[0]
    phi, theta, d_phi = _angle_grid(int(regrid_dimen[0]), int(regrid_dimen[1]))
    grid = _unit_vectors(phi, theta)
    data_grid = np.zeros((n_energy, len(phi)))
    bins_grid = np.zeros((n_energy, len(phi)))
    for i in range(n_energy):
        points = _unit_vectors(data['phi'][i], data['theta'][i])
        data_grid[i] = NearestNDInterpolator(points, data['data'][i])(grid)
        bins_grid[i] = NearestNDInterpolator(points, data['bins'][i])(grid)
    # Same dict as pyspedas, quirks included: 'scaling' aliases 'data' and
    # 'dtheta' holds the phi spacing.
    output = {'data': data_grid,
              'scaling': data_grid,
              'phi': np.tile(phi, (n_energy, 1)),
              'dphi': np.full(data_grid.shape, d_phi),
              'theta': np.tile(theta, (n_energy, 1)),
              'dtheta': np.full(data_grid.shape, d_phi),
              'energy': np.repeat(data['energy'][:, :1], len(phi), axis=1),
              'denergy': np.repeat(data['denergy'][:, :1], len(phi), axis=1),
              'bins': bins_grid}
    output.update({k: data[k] for k in ('orig_energy', 'charge', 'mass') if k in data})
    return output


def install() -> None:
    from pyspedas.projects.mms.particles import mms_part_products

    mms_part_products.spd_pgs_regrid = spd_pgs_regrid
