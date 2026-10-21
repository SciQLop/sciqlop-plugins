"""C1/C2: the comparison tab: a tree of differences, a detail pane, copying from B into A."""
import numpy as np
import pycdfpp
import pytest

from cdf_workbench.compare_view import NAME, GUTTER, CompareView, detail_html, gutter_action, summary_text
from cdf_workbench.diff import diff_documents
from cdf_workbench.document import Attribute, DocumentSession, GlobalAttribute, from_cdf
from cdf_workbench.edits import set_global_attribute, set_variable_attribute


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
def compare(qtbot):
    session = DocumentSession(_doc("nT", extra="gone"))
    view = CompareView(session, _doc("pT <b>", renamed=True), ("a.cdf", "b.cdf"))
    qtbot.addWidget(view)
    return session, view


def _top_names(view):
    tree = view._tree
    return [tree.topLevelItem(i).data(NAME, 256).name for i in range(tree.topLevelItemCount())]


def _row(view, name):
    def walk(rows):
        for r in rows:
            if r.name == name:
                return r
            if (found := walk(r.children)) is not None:
                return found
    return walk(view.rows())


def test_tree_lists_the_differences(compare):
    _session, view = compare
    assert _top_names(view) == ["B", "B_gse → B_GSE", "gone"]
    view._hide_same.click()
    assert "same_var" in _top_names(view)
    assert "renamed" in view._summary.text() and "removed" in view._summary.text()


def test_filter_narrows_the_tree(compare):
    _session, view = compare
    view._filter.setText("gone")
    assert _top_names(view) == ["gone"]


def test_detail_shows_both_values_escaped(compare):
    _session, view = compare
    html = detail_html(_row(view, "UNITS"), ("a.cdf", "b.cdf"))
    assert "pT &lt;b&gt;" in html and "pT <b>" not in html


def test_word_marks_only_where_the_values_resemble_each_other():
    from cdf_workbench.compare_rows import Row
    similar = Row("B/CATDESC", "CATDESC", "changed", "Magnetic field in GSE", "Magnetic field in RTN")
    different = Row("B/TITLE", "TITLE", "changed", "ACE> Magnetometer Parameters", "ACE> Solar Isotope Spectrometer")
    assert "background-color" in detail_html(similar, ("a", "b"))
    assert "background-color" not in detail_html(different, ("a", "b"))


def test_gutter_click_copies_and_the_tree_follows(compare):
    session, view = compare
    b = view._tree.topLevelItem(0)
    units = b.child(0)

    view._on_clicked(units, GUTTER)

    assert session.document["B"].attributes["UNITS"].value == "pT <b>"
    assert _top_names(view) == ["B_gse → B_GSE", "gone"]
    session.undo()
    assert _top_names(view) == ["B", "B_gse → B_GSE", "gone"]


def test_a_pure_rename_is_taken_from_the_gutter(compare):
    session, view = compare
    renamed = _row(view, "B_gse → B_GSE")
    assert gutter_action(renamed) == renamed.rename

    view.copy(gutter_action(renamed))

    assert "B_GSE" in session.document and "B_gse" not in session.document


def test_several_copies_are_one_undo_step(qtbot):
    reference = set_global_attribute(_doc("pT"), None, "Mission",
                                     GlobalAttribute((Attribute("MMS", pycdfpp.DataType.CDF_CHAR),)))
    session = DocumentSession(_doc("nT"))
    view = CompareView(session, reference, ("a", "b"))
    qtbot.addWidget(view)
    actions = [r.copy for r in view.rows()[0].children] + [_row(view, "UNITS").copy]

    view.copy(*actions)

    assert "Mission" in session.document.attributes and session.document["B"].attributes["UNITS"].value == "pT"
    session.undo()
    assert not session.is_modified


def test_copy_all_on_a_renamed_variable_targets_its_old_name(qtbot):
    reference = set_variable_attribute(_doc("nT", renamed=True), "B_GSE", None, "LABLAXIS",
                                       Attribute("B", pycdfpp.DataType.CDF_CHAR))
    session = DocumentSession(_doc("nT"))
    view = CompareView(session, reference, ("a", "b"))
    qtbot.addWidget(view)

    view.copy(_row(view, "B_gse → B_GSE").copy)

    assert session.document["B_gse"].attributes["LABLAXIS"].value == "B"


def test_copy_a_variable_only_in_the_reference(qtbot):
    session = DocumentSession(_doc("nT"))
    view = CompareView(session, _doc("nT", extra="extra"), ("a", "b"))
    qtbot.addWidget(view)

    view.copy(_row(view, "extra").copy)

    assert "extra" in session.document and view.rows() == []


def test_summary_counts():
    diff = diff_documents(_doc("nT", extra="gone"), _doc("pT", renamed=True))
    assert summary_text(diff) == "Variables: 1 changed, 1 renamed, 1 removed, 1 identical · global attributes changed: 0"
