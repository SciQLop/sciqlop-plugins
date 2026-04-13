"""Tests for the CdfFileView plottability heuristics."""
import pytest
import pycdfpp

pytest.importorskip("SciQLopPlots")

from cdf_workbench.file_view import _is_plottable
from cdf_workbench.tree_model import VariableInfo


def _info(shape, display_type="", cdf_type=pycdfpp.DataType.CDF_FLOAT):
    return VariableInfo(name="v", shape=shape, cdf_type=cdf_type, var_type="data", display_type=display_type)


def test_1d_plottable():
    assert _is_plottable(_info((100,)))


def test_2d_small_plottable():
    assert _is_plottable(_info((100, 3)))


def test_2d_spectrogram_plottable():
    assert _is_plottable(_info((24, 16384), display_type="spectrogram"))


def test_2d_huge_component_axis_not_plottable():
    """A (24, 16384) array without spectrogram hint would try to draw 16384
    lines and freeze the UI — it must not be considered plottable."""
    assert not _is_plottable(_info((24, 16384)))


def test_3d_not_plottable():
    assert not _is_plottable(_info((24, 3, 16384)))
