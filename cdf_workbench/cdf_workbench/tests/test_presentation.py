"""How variables and their quality are summarised in the tree and the inspector."""
import pycdfpp
import pytest

from cdf_workbench.presentation import common_prefix, quality_badge, quality_summary, row_label
from cdf_workbench.quality import QualityReport
from cdf_workbench.tree_model import VariableInfo


def _info(shape, display_type="time_series", cdf_type=pycdfpp.DataType.CDF_DOUBLE):
    return VariableInfo(name="v", shape=shape, cdf_type=cdf_type, var_type="data", display_type=display_type)


def test_row_label_is_one_short_muted_label():
    assert row_label(_info((555, 3))) == "2D · TS"
    assert row_label(_info((100,), "spectrogram")) == "1D · SP"
    assert row_label(_info((10,), "")) == "1D"


def test_row_label_does_not_count_the_string_length_of_text_variables():
    assert row_label(_info((1, 3, 6), "", pycdfpp.DataType.CDF_CHAR)) == "2D"


@pytest.mark.parametrize("pct, expected", [(100.0, None), (99.96, None), (97.0, ("97%", "warning")),
                                           (60.0, ("60%", "warning")), (30.0, ("30%", "error"))])
def test_quality_badge_only_when_something_is_missing(pct, expected):
    assert quality_badge(pct) == expected


def test_common_prefix_ends_at_an_underscore():
    assert common_prefix(["mms1_dis_dist_fast", "mms1_dis_energy_fast", "mms1_dis_phi_fast"]) == "mms1_dis_"
    assert common_prefix(["tha_peif_density", "tha_peeb_fluxQ"]) == "tha_"
    assert common_prefix(["Epoch", "B"]) == ""
    assert common_prefix(["only_one"]) == ""


def test_quality_summary_is_one_line_with_a_level():
    perfect = QualityReport(fill_percentage=0.0, out_of_range_percentage=0.0, epoch_gaps=0, total_points=10)
    assert quality_summary(perfect) == ("✓ 100% valid · 0% fill · 0% out of range · 0 gaps", "ok")
    gappy = QualityReport(fill_percentage=2.5, out_of_range_percentage=0.5, epoch_gaps=3, total_points=10)
    assert quality_summary(gappy) == ("97% valid · 2.5% fill · 0.5% out of range · 3 gaps", "warning")
    bad = QualityReport(fill_percentage=70.0, out_of_range_percentage=0.0, epoch_gaps=0, total_points=10)
    assert quality_summary(bad)[1] == "error"
