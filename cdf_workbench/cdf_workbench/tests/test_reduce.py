"""Reduction of rank > 2 variables (particle distributions) to a time series or spectrogram."""
import numpy as np
import pycdfpp
import pytest

from cdf_workbench.reduce import (
    MEAN, PLOT, SUM, default_modes, needs_reduction, reduce_values, reduced_info, with_axis_mode,
)
from cdf_workbench.tree_model import VariableInfo

FILL = -1e31


def _dist() -> np.ndarray:
    """dist[r, phi, theta, energy] = 1000r + 100p + 10t + e, except dist[0, 0, 0, 0] = FILLVAL."""
    r, p, t, e = np.meshgrid(np.arange(3), np.arange(2), np.arange(3), np.arange(4), indexing="ij")
    dist = (1000 * r + 100 * p + 10 * t + e).astype(np.float32)
    dist[0, 0, 0, 0] = FILL
    return dist


def _info(depends=("phi", "theta", "energy"), shape=(3, 2, 3, 4), **attrs) -> VariableInfo:
    all_attributes = {f"DEPEND_{k}": [d] for k, d in enumerate(depends, start=1)}
    all_attributes.update({"DEPEND_0": ["Epoch"], "DISPLAY_TYPE": ["spectrogram"],
                           "FILLVAL": [FILL], "SCALETYP": ["log"]})
    all_attributes.update({k: [v] for k, v in attrs.items()})
    return VariableInfo(name="dist", shape=shape, cdf_type=pycdfpp.DataType.CDF_FLOAT, var_type="data",
                        depend_0="Epoch", depend_1=depends[0], display_type="spectrogram",
                        fill_value=FILL, scale_type="log", all_attributes=all_attributes)


def test_needs_reduction_only_for_numeric_rank_above_two():
    assert needs_reduction(_info())
    assert not needs_reduction(_info(depends=("energy",), shape=(3, 4)))
    assert not needs_reduction(_info(shape=(0, 2, 3, 4)))
    char = _info()
    char.cdf_type = pycdfpp.DataType.CDF_CHAR
    assert not needs_reduction(char)


def test_default_keeps_the_energy_axis_wherever_it_is():
    assert default_modes(_info()) == (SUM, SUM, PLOT)
    assert default_modes(_info(depends=("mms1_dis_energy_fast", "phi", "theta"))) == (PLOT, SUM, SUM)


def test_default_falls_back_to_the_last_axis():
    assert default_modes(_info(depends=("a", "b", "c"))) == (SUM, SUM, PLOT)


def test_only_one_axis_can_be_plotted():
    assert with_axis_mode((SUM, SUM, PLOT), 0, PLOT) == (PLOT, SUM, SUM)
    assert with_axis_mode((SUM, SUM, PLOT), 1, MEAN) == (SUM, MEAN, PLOT)
    assert with_axis_mode((SUM, SUM, PLOT), 2, 1) == (SUM, SUM, 1)


def test_omnidirectional_energy_spectrum_skips_fill_values():
    dist = _dist()
    out = reduce_values(dist, (SUM, SUM, PLOT), fill_value=FILL)

    expected = np.where(dist == FILL, 0, dist).astype(np.float64).sum(axis=(1, 2))
    assert out.shape == (3, 4)
    np.testing.assert_allclose(out, expected)


def test_mean_divides_by_the_number_of_valid_values():
    out = reduce_values(_dist(), (MEAN, MEAN, PLOT), fill_value=FILL)

    assert out[0, 0] == pytest.approx((sum(100 * p + 10 * t for p in range(2) for t in range(3)) - 0) / 5)
    assert out[1, 2] == pytest.approx(np.mean([1000 + 100 * p + 10 * t + 2 for p in range(2) for t in range(3)]))


def test_a_slice_keeps_one_index_and_valid_range_is_masked():
    out = reduce_values(_dist(), (1, SUM, PLOT), fill_value=FILL, valid_max=1099)

    assert out.shape == (3, 4)
    assert out[0, 3] == pytest.approx(sum(100 + 10 * t + 3 for t in range(3)))
    assert np.isnan(out[1, 0])


def test_collapsing_every_axis_gives_a_time_series():
    out = reduce_values(_dist(), (SUM, SUM, SUM), fill_value=FILL)

    assert out.shape == (3,)
    assert out[2] == pytest.approx(_dist()[2].astype(np.float64).sum())


def test_reduced_info_describes_the_plotted_axis():
    info = _info(LABL_PTR_3="energy_labels", VALIDMAX=1e6)

    reduced = reduced_info(info, (SUM, SUM, PLOT))

    assert reduced.shape == (3, 4)
    assert reduced.depend_1 == "energy"
    assert reduced.labl_ptr_1 == "energy_labels"
    assert reduced.display_type == "spectrogram"
    assert reduced.fill_value is None and reduced.valid_max is None
    assert reduced.all_attributes["DEPEND_1"] == ["energy"]
    assert reduced.all_attributes["SCALETYP"] == ["log"]
    assert not {"DEPEND_2", "DEPEND_3", "LABL_PTR_3", "FILLVAL", "VALIDMAX"} & reduced.all_attributes.keys()


def test_reduced_info_without_a_plotted_axis_is_a_time_series():
    reduced = reduced_info(_info(), (SUM, 0, MEAN))

    assert reduced.shape == (3,)
    assert reduced.depend_1 == ""
    assert reduced.display_type == "time_series"
    assert "DEPEND_1" not in reduced.all_attributes
