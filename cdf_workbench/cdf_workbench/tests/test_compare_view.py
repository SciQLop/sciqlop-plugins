"""C1: the comparison tab."""
import numpy as np
import pycdfpp
import pytest

from cdf_workbench.compare_view import CompareView, render_html
from cdf_workbench.diff import diff_documents
from cdf_workbench.document import from_cdf


def _doc(units: str, extra: str = "", renamed: bool = False):
    cdf = pycdfpp.CDF()
    cdf.add_attribute("Project", ["ISTP"])
    cdf.add_variable("same_var", values=np.ones(3))
    cdf["same_var"].add_attribute("UNITS", "s")
    cdf.add_variable("B", values=np.ones(3))
    cdf["B"].add_attribute("UNITS", units)
    name = "B_GSE" if renamed else "B_gse"
    cdf.add_variable(name, values=np.ones(3))
    for k, v in (("CATDESC", "field"), ("UNITS", "nT"), ("FIELDNAM", "B"), ("VAR_TYPE", "data")):
        cdf[name].add_attribute(k, v)
    if extra:
        cdf.add_variable(extra, values=np.ones(2))
    return from_cdf(cdf)


@pytest.fixture
def diff():
    return diff_documents(_doc("nT", extra="gone"), _doc("pT <b>", renamed=True))


def test_hide_identical_drops_unchanged_variables(diff):
    assert "same_var" not in render_html(diff, hide_same=True, side_by_side=False)
    assert "same_var" in render_html(diff, hide_same=False, side_by_side=False)


def test_report_shows_changes_renames_and_escapes_values(diff):
    text = render_html(diff, hide_same=True, side_by_side=False)
    assert "B_gse → B_GSE" in text
    assert "gone" in text and "removed" in text
    assert "pT &lt;b&gt;" in text and "pT <b>" not in text


def test_side_by_side_puts_old_and_new_in_two_columns(diff):
    text = render_html(diff, hide_same=True, side_by_side=True, titles=("a.cdf", "b.cdf"))
    assert "a.cdf" in text and "b.cdf" in text


@pytest.fixture
def compare(qtbot):
    from cdf_workbench.document import DocumentSession
    session = DocumentSession(_doc("nT", extra="gone"))
    view = CompareView(session, _doc("pT <b>", renamed=True), ("a.cdf", "b.cdf"))
    qtbot.addWidget(view)
    return session, view


def test_view_rerenders_when_toggled(qtbot, compare):
    _session, view = compare
    assert "same_var" not in view.html()
    view._hide_same.click()
    assert "same_var" in view.html()
    assert "1 renamed" in view._summary.text() and "1 removed" in view._summary.text()


def _link(view, kind):
    import re
    return re.search(rf'href="({kind}:[^"]*)"', view.html()).group(1).replace("&amp;", "&")


def test_copy_an_attribute_from_the_reference(compare):
    session, view = compare
    view.copy(_link(view, "copy-attr"))

    assert session.document["B"].attributes["UNITS"].value == "pT <b>"
    assert session.is_modified
    assert "UNITS" not in view.html()


def test_copy_all_on_a_renamed_variable_targets_its_old_name():
    from cdf_workbench.document import DocumentSession
    from cdf_workbench.edits import set_variable_attribute
    from cdf_workbench.document import Attribute
    target = _doc("nT")
    reference = set_variable_attribute(_doc("nT", renamed=True), "B_GSE", None, "LABLAXIS",
                                       Attribute("B", pycdfpp.DataType.CDF_CHAR))
    session = DocumentSession(target)
    view = CompareView(session, reference, ("a", "b"))

    view.copy(_link(view, "copy-all"))

    assert session.document["B_gse"].attributes["LABLAXIS"].value == "B"


def test_copy_a_variable_only_in_the_reference_and_undo(compare):
    from cdf_workbench.document import DocumentSession
    session = DocumentSession(_doc("nT"))
    view = CompareView(session, _doc("nT", extra="extra"), ("a", "b"))

    view.copy(_link(view, "copy-var"))
    assert "extra" in session.document
    assert "No differences" in view.html()

    session.undo()
    assert "extra" not in session.document and "copy variable" in view.html()


def test_copy_a_global_attribute(qtbot):
    from cdf_workbench.document import DocumentSession, GlobalAttribute, Attribute
    from cdf_workbench.edits import set_global_attribute
    reference = set_global_attribute(_doc("nT"), None, "Mission",
                                     GlobalAttribute((Attribute("MMS", pycdfpp.DataType.CDF_CHAR),)))
    session = DocumentSession(_doc("nT"))
    view = CompareView(session, reference, ("a", "b"))

    view.copy(_link(view, "copy-attr"))

    assert [e.value for e in session.document.attributes["Mission"].entries] == ["MMS"]
