import numpy as np

from sciqlop_pyspedas.convert import EFLUX_UNITS, empty_spectrum, spectrum_variable


def _times(n):
    return np.datetime64("2020-01-01T00:00:00", "ns") + np.arange(n) * np.timedelta64(10, "s")


def test_energy_spectrum_with_fixed_bins():
    v = spectrum_variable(_times(3), np.ones((3, 4)), np.array([10., 100., 1e3, 1e4]),
                          "energy", "mms1_dis_dist_fast_energy")
    assert v.values.shape == (3, 4)
    assert v.time.dtype == np.dtype("datetime64[ns]")
    assert v.axes[1].values.shape == (4,)
    assert v.axes[1].meta["UNITS"] == "eV"
    assert v.axes[1].meta["SCALETYP"] == "log"
    assert v.meta["UNITS"] == EFLUX_UNITS


def test_time_varying_bins_are_kept_2d():
    bins = np.tile(np.array([10., 100., 1e3, 1e4]), (3, 1))
    v = spectrum_variable(_times(3), np.ones((3, 4)), bins, "energy", "x")
    assert v.axes[1].values.shape == (3, 4)


def test_pitch_angle_axis_is_linear_degrees():
    v = spectrum_variable(_times(2), np.ones((2, 3)), np.array([15., 90., 165.]), "pa", "x")
    assert v.axes[1].meta["UNITS"] == "deg"
    assert v.axes[1].meta["SCALETYP"] == "linear"


def test_empty_spectrum_has_no_rows():
    v = empty_spectrum("gyro", "x")
    assert len(v.time) == 0
