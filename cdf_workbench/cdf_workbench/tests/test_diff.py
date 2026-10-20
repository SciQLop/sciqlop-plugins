"""C1: structural comparison of two documents (variables and attributes, not values)."""
import numpy as np
import pycdfpp
import pytest

from cdf_workbench.diff import diff_documents, word_diff
from cdf_workbench.document import from_cdf


def _doc(variables: dict, globals_: dict | None = None):
    cdf = pycdfpp.CDF()
    for name, values in (globals_ or {}).items():
        cdf.add_attribute(name, values)
    for name, (values, attrs) in variables.items():
        cdf.add_variable(name, values=values)
        for k, v in attrs.items():
            cdf[name].add_attribute(k, v)
    return from_cdf(cdf)


ATTRS = {"VAR_TYPE": "data", "UNITS": "nT", "CATDESC": "Magnetic field", "DEPEND_0": "Epoch",
         "FIELDNAM": "B", "LABLAXIS": "B"}


def test_identical_documents_have_no_change():
    a = _doc({"B": (np.ones(3), ATTRS)}, {"Project": ["ISTP"]})
    diff = diff_documents(a, a)
    assert diff.summary() == {"same": 1}
    assert [v.status for v in diff.variables] == ["same"]
    assert [g.status for g in diff.attributes] == ["same"]


def test_added_removed_and_changed_variables():
    a = _doc({"B": (np.ones(3), ATTRS), "old": (np.ones(2), {})})
    b = _doc({"B": (np.ones(3, dtype=np.float32), {**ATTRS, "UNITS": "pT"}), "new": (np.ones(9), {"X": "y"})})

    diff = diff_documents(a, b)

    status = {v.name: v.status for v in diff.variables}
    assert status == {"B": "changed", "old": "removed", "new": "added"}
    b_diff = next(v for v in diff.variables if v.name == "B")
    assert ("type", "CDF_DOUBLE", "CDF_FLOAT") in b_diff.properties
    assert [(x.name, x.status, x.old, x.new) for x in b_diff.attributes if x.status != "same"] == [
        ("UNITS", "changed", "nT", "pT")]


def test_a_renamed_variable_is_one_entry_not_a_remove_and_an_add():
    a = _doc({"B_gse": (np.ones(3), ATTRS)})
    b = _doc({"B_GSE": (np.ones(3), {**ATTRS, "CATDESC": "Magnetic field in GSE"})})

    diff = diff_documents(a, b)

    assert [(v.name, v.old_name, v.status) for v in diff.variables] == [("B_GSE", "B_gse", "renamed")]


def test_unrelated_variables_are_not_paired_as_a_rename():
    a = _doc({"B": (np.ones(3), ATTRS)})
    b = _doc({"density": (np.ones((3, 2)), {"VAR_TYPE": "support_data", "UNITS": "cm^-3"})})
    assert sorted(v.status for v in diff_documents(a, b).variables) == ["added", "removed"]


def test_global_attribute_entries_are_compared_line_by_line():
    a = _doc({}, {"Project": ["ISTP", "SPDF"], "Gone": ["x"]})
    b = _doc({}, {"Project": ["ISTP", "CDAWeb"], "Mission": ["MMS"]})

    diff = diff_documents(a, b)

    assert {g.name: g.status for g in diff.attributes} == {"Project": "changed", "Gone": "removed",
                                                           "Mission": "added"}
    project = next(g for g in diff.attributes if g.name == "Project")
    assert (project.old, project.new) == ("ISTP\nSPDF", "ISTP\nCDAWeb")


def test_word_diff_marks_only_the_changed_words():
    old, new = word_diff("Magnetic field in GSE coordinates", "Magnetic field in RTN coordinates")
    assert old == "Magnetic field in <del>GSE</del> coordinates"
    assert new == "Magnetic field in <ins>RTN</ins> coordinates"


def test_word_diff_escapes_html_and_keeps_unchanged_lines_plain():
    old, new = word_diff("a <b>\nsame line", "a <c>\nsame line")
    assert "&lt;" in old and "<del>&lt;b&gt;</del>" in old and "<ins>&lt;c&gt;</ins>" in new
    assert old.endswith("\nsame line") and new.endswith("\nsame line")


def test_a_rename_needs_the_same_type_shape_and_nrv():
    a = _doc({"B": (np.ones(3), ATTRS)})
    b = _doc({"B_GSM": (np.ones((3, 3)), ATTRS)})
    assert sorted(v.status for v in diff_documents(a, b).variables) == ["added", "removed"]
