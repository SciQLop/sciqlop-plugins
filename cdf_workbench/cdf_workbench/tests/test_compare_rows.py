"""C1: the comparison as tree rows: what is shown, grouped and copyable."""
import numpy as np
import pycdfpp
import pytest

from cdf_workbench.compare_rows import build_rows, short_titles
from cdf_workbench.diff import diff_documents
from cdf_workbench.document import from_cdf

ATTRS = {"CATDESC": "field", "UNITS": "nT", "FIELDNAM": "B", "VAR_TYPE": "data"}


def _doc(units="nT", extra="", renamed=False, project="ISTP"):
    cdf = pycdfpp.CDF()
    cdf.add_attribute("Project", [project])
    cdf.add_attribute("Mission", ["MMS"])
    cdf.add_variable("same_var", values=np.ones(3))
    cdf["same_var"].add_attribute("UNITS", "s")
    cdf.add_variable("B", values=np.ones(3))
    cdf["B"].add_attribute("UNITS", units)
    cdf["B"].add_attribute("CATDESC", "magnetic field")
    name = "B_GSE" if renamed else "B_gse"
    cdf.add_variable(name, values=np.ones(3))
    for k, v in ATTRS.items():
        cdf[name].add_attribute(k, v)
    if extra:
        cdf.add_variable(extra, values=np.ones(2))
        cdf[extra].add_attribute("VAR_TYPE", "metadata")
        cdf[extra].add_attribute("CATDESC", "gone soon")
    return from_cdf(cdf)


@pytest.fixture
def diff():
    return diff_documents(_doc("nT", extra="gone", project="ISTP"), _doc("pT", renamed=True, project="SPDF"))


def _by_name(rows):
    return {r.name: r for r in rows}


def test_groups_list_globals_then_variables_with_counts(diff):
    rows = build_rows(diff, hide_same=True)
    assert [r.name for r in rows] == ["Global attributes", "B", "B_gse → B_GSE", "gone"]
    assert rows[0].note == "1 changed"
    assert [c.name for c in rows[0].children] == ["Project"]


def test_hide_identical_drops_unchanged_rows_and_variables(diff):
    assert "same_var" not in _by_name(build_rows(diff, hide_same=True))
    shown = _by_name(build_rows(diff, hide_same=False))
    assert "same_var" in shown
    assert [c.name for c in shown["Global attributes"].children] == ["Project", "Mission"]


def test_changed_rows_carry_both_values_and_a_copy_action(diff):
    b = _by_name(build_rows(diff, hide_same=True))["B"]
    units = _by_name(b.children)["UNITS"]
    assert (units.status, units.old, units.new) == ("changed", "nT", "pT")
    assert units.copy.startswith("copy-attr:")
    assert b.copy.startswith("copy-all:") and b.expanded


def test_removed_variables_are_one_collapsed_row(diff):
    gone = _by_name(build_rows(diff, hide_same=True))["gone"]
    assert gone.status == "removed" and not gone.expanded
    assert gone.note == "2 attributes" and gone.copy is None


def test_a_pure_rename_offers_the_rename(diff):
    renamed = _by_name(build_rows(diff, hide_same=True))["B_gse → B_GSE"]
    assert renamed.status == "renamed" and renamed.rename.startswith("copy-rename:")
    assert renamed.children == ()


def test_filter_keeps_matching_rows_and_their_group(diff):
    rows = build_rows(diff, hide_same=False, text="units")
    assert [r.name for r in rows] == ["same_var", "B", "B_gse → B_GSE"]
    assert [c.name for c in _by_name(rows)["B"].children] == ["UNITS"]
    assert [r.name for r in build_rows(diff, hide_same=False, text="gone")] == ["gone"]


def test_short_titles_drop_what_both_names_share():
    assert short_titles("mms1_edp_brst_l2_hmfe_20210705040813_v2.0.0.cdf",
                        "mms1_scm_srvy_l2_scsrvy_20241025_v2.2.0.cdf") == (
        "…edp_brst_l2_hmfe_20210705040813_v2.0.0", "…scm_srvy_l2_scsrvy_20241025_v2.2.0")
    assert short_titles("a.cdf", "b.cdf") == ("a", "b")
