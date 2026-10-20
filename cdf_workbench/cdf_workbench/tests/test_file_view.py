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


def test_3d_is_plotted_reduced_to_a_spectrogram_never_as_lines():
    from cdf_workbench.reduce import default_modes, reduced_info
    info = _info((24, 3, 16384))
    assert _is_plottable(info)
    assert reduced_info(info, default_modes(info)).display_type == "spectrogram"


def test_3d_with_an_empty_dimension_is_not_plottable():
    assert not _is_plottable(_info((24, 0, 16)))


def test_text_depend_1_gives_labels_not_a_y_axis(qtbot):
    """ACE BGSEc: DEPEND_1 points to a CDF_CHAR variable of component names."""
    import numpy as np
    from cdf_workbench.document import DocumentSession, from_cdf
    from cdf_workbench.file_view import CdfFileView

    cdf = pycdfpp.CDF()
    cdf.add_variable("B", values=np.ones((4, 3), dtype=np.float32))
    cdf.add_variable("cartesian", values=np.array([b"x_component", b"y_component", b"z_component"]),
                     is_nrv=True)
    cdf["B"].add_attribute("VAR_TYPE", "data")
    cdf["B"].add_attribute("DEPEND_1", "cartesian")
    view = CdfFileView(DocumentSession(from_cdf(cdf)))
    qtbot.addWidget(view)

    bundle = view._read_bundle(view._tree_model.variable_info("B"))

    assert bundle.depend_1 is None
    assert bundle.hints.component_labels == ["x_component", "y_component", "z_component"]
    view.release()


@pytest.mark.parametrize("time_type", [pycdfpp.DataType.CDF_TIME_TT2000, pycdfpp.DataType.CDF_EPOCH,
                                       pycdfpp.DataType.CDF_EPOCH16])
def test_quality_analysis_handles_every_epoch_type(time_type):
    import numpy as np
    from cdf_workbench.document import from_cdf
    from cdf_workbench.file_view import AnalysisWorker
    from cdf_workbench.tree_model import CdfTreeModel

    seconds = np.array([0, 1, 2, 3, 10, 11], dtype="timedelta64[s]")
    cdf = pycdfpp.CDF()
    cdf.add_variable("Epoch", values=np.datetime64("2020-01-01", "ns") + seconds, data_type=time_type)
    cdf.add_variable("B", values=np.arange(6.0))
    cdf["B"].add_attribute("DEPEND_0", "Epoch")
    doc = from_cdf(cdf)
    worker = AnalysisWorker(doc, {"B": CdfTreeModel(doc).variable_info("B")})
    reports = []
    worker.quality_ready.connect(lambda name, report: reports.append(report))

    worker.run()

    assert [r.epoch_gaps for r in reports] == [1]


def test_quality_analysis_handles_a_numeric_depend_0():
    import numpy as np
    from cdf_workbench.document import from_cdf
    from cdf_workbench.file_view import AnalysisWorker
    from cdf_workbench.tree_model import CdfTreeModel

    cdf = pycdfpp.CDF()
    cdf.add_variable("t", values=np.array([0.0, 1, 2, 3, 10, 11]))
    cdf.add_variable("B", values=np.arange(6.0))
    cdf["B"].add_attribute("DEPEND_0", "t")
    doc = from_cdf(cdf)
    worker = AnalysisWorker(doc, {"B": CdfTreeModel(doc).variable_info("B")})
    reports = []
    worker.quality_ready.connect(lambda name, report: reports.append(report))

    worker.run()

    assert [r.epoch_gaps for r in reports] == [1]



def test_labels_follow_columns_when_depend_1_is_flipped(qtbot):
    """_make_ascending reverses a descending DEPEND_1 and the data columns; labels must follow."""
    import numpy as np
    from cdf_workbench.document import DocumentSession, from_cdf
    from cdf_workbench.file_view import CdfFileView

    cdf = pycdfpp.CDF()
    cdf.add_variable("F", values=np.array([[3.0, 2.0, 1.0]] * 4))
    cdf.add_variable("E", values=np.array([300.0, 200.0, 100.0]), is_nrv=True)
    cdf.add_variable("labels", values=np.array([b"high", b"mid", b"low"]), is_nrv=True)
    cdf["F"].add_attribute("DEPEND_1", "E")
    cdf["F"].add_attribute("LABL_PTR_1", "labels")
    view = CdfFileView(DocumentSession(from_cdf(cdf)))
    qtbot.addWidget(view)

    bundle = view._read_bundle(view._tree_model.variable_info("F"))

    assert list(bundle.depend_1.ravel()) == [100.0, 200.0, 300.0]
    assert list(bundle.values[0]) == [1.0, 2.0, 3.0]
    assert bundle.hints.component_labels == ["low", "mid", "high"]
    view.release()


@pytest.fixture
def dist_view(qtbot):
    import numpy as np
    from cdf_workbench.document import DocumentSession, from_cdf
    from cdf_workbench.file_view import CdfFileView

    cdf = pycdfpp.CDF()
    epochs = np.datetime64("2020-01-01", "ns") + np.arange(3).astype("timedelta64[s]")
    cdf.add_variable("Epoch", values=epochs, data_type=pycdfpp.DataType.CDF_TIME_TT2000)
    cdf.add_variable("phi", values=np.array([0.0, 180.0], dtype=np.float32), is_nrv=True)
    cdf.add_variable("theta", values=np.array([30.0, 90.0, 150.0], dtype=np.float32), is_nrv=True)
    cdf.add_variable("energy", values=np.array([10.0, 100.0, 1000.0, 10000.0], dtype=np.float32), is_nrv=True)
    cdf["energy"].add_attribute("SCALETYP", "log")
    cdf["energy"].add_attribute("UNITS", "eV")
    cdf.add_variable("dist", values=np.ones((3, 2, 3, 4), dtype=np.float32))
    for name, value in (("VAR_TYPE", "data"), ("DEPEND_0", "Epoch"), ("DEPEND_1", "phi"),
                        ("DEPEND_2", "theta"), ("DEPEND_3", "energy"), ("DISPLAY_TYPE", "spectrogram"),
                        ("SCALETYP", "log")):
        cdf["dist"].add_attribute(name, value)
    view = CdfFileView(DocumentSession(from_cdf(cdf)))
    qtbot.addWidget(view)
    yield view
    view.release()


def test_distribution_defaults_to_the_omnidirectional_energy_spectrogram(dist_view):
    info = dist_view._tree_model.variable_info("dist")
    assert _is_plottable(info)

    bundle = dist_view._read_bundle(info)

    assert bundle.is_time_axis and bundle.is_spectrogram
    assert bundle.values.shape == (3, 4)
    assert bundle.values[0, 0] == 6.0
    assert list(bundle.depend_1.ravel()) == [10.0, 100.0, 1000.0, 10000.0]
    assert bundle.hints.y2.scale == "log"


def test_axis_bar_offers_one_menu_per_dimension(dist_view):
    from cdf_workbench.reduce import PLOT
    info = dist_view._tree_model.variable_info("dist")

    dist_view._update_preview(info)
    assert dist_view._axis_bar.titles() == ["phi", "theta", "energy"]
    assert dist_view._axis_bar.choices(0) == ["plot", "sum", "mean", "= 0", "= 180"]

    dist_view._axis_bar.select(0, PLOT)

    bundle = dist_view._read_bundle(info)
    assert bundle.values.shape == (3, 2)
    assert list(bundle.depend_1.ravel()) == [0.0, 180.0]
    assert bundle.values[0, 0] == 12.0


def _bundle(values, depend_1=None, display_type="line", y_scale=None, y2_scale=None):
    import numpy as np
    from SciQLop.core.plot_hints import AxisHints, PlotHints
    from cdf_workbench.file_view import PlotBundle
    hints = PlotHints(display_type=display_type, y=AxisHints(scale=y_scale), y2=AxisHints(scale=y2_scale))
    values = np.asarray(values, dtype=np.float64)
    return PlotBundle(x=np.arange(len(values), dtype=np.float64), values=values,
                      depend_1=None if depend_1 is None else np.asarray(depend_1, dtype=np.float64),
                      hints=hints, is_time_axis=False)


def test_y_scale_comes_from_the_line_hints_or_defaults_to_linear():
    assert _bundle([1.0, 2.0], y_scale="log").y_scale == "log"
    assert _bundle([1.0, 2.0]).y_scale == "linear"


def test_spectrogram_y_scale_comes_from_depend_1():
    spectro = _bundle([[1.0, 2.0]], depend_1=[10.0, 100.0], display_type="spectrogram", y2_scale="log")
    assert spectro.y_scale == "log"


def test_log_line_hides_values_that_are_not_positive():
    import numpy as np
    logged = _bundle([-1.0, 0.0, 5.0]).with_y_scale("log")

    assert logged.hints.y.scale == "log"
    assert np.isnan(logged.values[:2]).all() and logged.values[2] == 5.0


def test_spectrogram_with_non_positive_bins_cannot_use_log():
    azimuth = _bundle([[1.0, 2.0, 3.0]], depend_1=[0.0, 120.0, 240.0], display_type="spectrogram")
    energy = _bundle([[1.0, 2.0, 3.0]], depend_1=[10.0, 100.0, 1000.0], display_type="spectrogram")
    assert not azimuth.log_y_allowed
    assert energy.log_y_allowed
    assert energy.with_y_scale("log").hints.y2.scale == "log"


def test_log_y_checkbox_overrides_the_scale_and_survives_axis_mode_changes(dist_view):
    from cdf_workbench.reduce import SUM
    info = dist_view._tree_model.variable_info("dist")
    dist_view._update_preview(info)
    assert dist_view._log_y.isChecked()

    dist_view._log_y.click()
    assert dist_view._read_bundle(info).y_scale == "linear"

    dist_view._axis_bar.select(0, SUM)
    assert not dist_view._log_y.isChecked()
    assert dist_view._read_bundle(info).y_scale == "linear"


def test_log_y_checkbox_is_disabled_for_azimuth_bins(dist_view):
    from cdf_workbench.reduce import PLOT
    info = dist_view._tree_model.variable_info("dist")
    dist_view._update_preview(info)

    dist_view._axis_bar.select(0, PLOT)

    assert not dist_view._log_y.isEnabled()
    assert not dist_view._log_y.isChecked()


def test_preview_explains_a_variable_too_big_for_memory(dist_view, monkeypatch):
    import cdf_workbench.file_view as file_view
    monkeypatch.setattr(file_view, "available_memory", lambda: 10)
    info = dist_view._tree_model.variable_info("dist")

    dist_view._update_preview(info)

    assert "needs" in dist_view._preview_message.text()
    assert not dist_view._preview_message.isHidden()


def test_preview_message_is_hidden_after_a_good_preview(dist_view):
    info = dist_view._tree_model.variable_info("dist")
    dist_view._update_preview(info)
    assert dist_view._preview_message.isHidden()


@pytest.fixture
def b_view(qtbot):
    import numpy as np
    from cdf_workbench.document import DocumentSession, from_cdf
    from cdf_workbench.file_view import CdfFileView
    cdf = pycdfpp.CDF()
    cdf.add_attribute("Project", ["ISTP"])
    cdf.add_variable("B", values=np.ones(3))
    cdf["B"].add_attribute("VAR_TYPE", "data")
    cdf["B"].add_attribute("UNITS", "nT")
    cdf["B"].add_attribute("CATDESC", "field")
    view = CdfFileView(DocumentSession(from_cdf(cdf)))
    qtbot.addWidget(view)
    view.select_variable("B")
    yield view
    view.release()


def test_editing_a_variable_attribute_updates_document_and_inspector(b_view, monkeypatch):
    monkeypatch.setattr(b_view, "_ask_attribute", lambda *args: ("UNITS", pycdfpp.DataType.CDF_CHAR, ["pT"]))

    b_view._inspector.edit_attribute.emit("B", "UNITS")

    assert b_view.session.document["B"].attributes["UNITS"].value == "pT"
    assert b_view._tree_model.variable_info("B").units == "pT"
    assert b_view._inspector.current_variable == "B"


def test_deleting_and_undoing_a_variable_attribute(b_view):
    b_view._inspector.delete_attribute.emit("B", "CATDESC")
    assert "CATDESC" not in b_view._tree_model.variable_info("B").all_attributes

    b_view.session.undo()

    assert b_view._tree_model.variable_info("B").catdesc == "field"


def test_adding_a_global_attribute(b_view, monkeypatch):
    monkeypatch.setattr(b_view, "_ask_attribute",
                        lambda *args: ("Mission", pycdfpp.DataType.CDF_CHAR, ["MMS", "Cluster"]))

    b_view._inspector.add_attribute.emit("")

    assert [e.value for e in b_view.session.document.attributes["Mission"].entries] == ["MMS", "Cluster"]


def test_renaming_onto_an_existing_attribute_is_refused(b_view, monkeypatch):
    monkeypatch.setattr(b_view, "_ask_attribute", lambda *args: ("CATDESC", pycdfpp.DataType.CDF_CHAR, ["x"]))

    b_view._inspector.edit_attribute.emit("B", "UNITS")

    assert not b_view.session.is_modified
    assert "CATDESC already exists" in b_view._preview_message.text()


def test_cancelled_dialog_changes_nothing(b_view, monkeypatch):
    monkeypatch.setattr(b_view, "_ask_attribute", lambda *args: None)
    b_view._inspector.edit_attribute.emit("B", "UNITS")
    assert not b_view.session.is_modified


def test_renaming_a_variable_asks_about_references(dist_view, monkeypatch):
    asked = []
    monkeypatch.setattr(dist_view, "_ask_new_name", lambda name: "E")
    monkeypatch.setattr(dist_view, "_ask_update_references", lambda name, refs: asked.append(refs) or "yes")

    dist_view._rename_variable("energy")

    assert asked == [[("dist", "DEPEND_3")]]
    assert "E" in dist_view.session.document and "energy" not in dist_view.session.document
    assert dist_view._tree_model.variable_info("dist").all_attributes["DEPEND_3"] == ["E"]


def test_cancelling_the_reference_question_renames_nothing(dist_view, monkeypatch):
    monkeypatch.setattr(dist_view, "_ask_new_name", lambda name: "E")
    monkeypatch.setattr(dist_view, "_ask_update_references", lambda name, refs: "cancel")
    dist_view._rename_variable("energy")
    assert not dist_view.session.is_modified


def test_deleting_a_variable_warns_about_references(dist_view, monkeypatch):
    warned = []
    monkeypatch.setattr(dist_view, "_confirm_delete", lambda name, refs: warned.append(refs) or True)

    dist_view._delete_variable("phi")

    assert warned == [[("dist", "DEPEND_1")]]
    assert "phi" not in dist_view.session.document
    assert dist_view._tree_model.variable_info("phi") is None


def test_renaming_the_selected_variable_keeps_it_selected(b_view, monkeypatch):
    monkeypatch.setattr(b_view, "_ask_new_name", lambda name: "B_gse")
    b_view._rename_variable("B")
    assert b_view._inspector.current_variable == "B_gse"


def test_new_variable_from_the_dialog_is_added_and_selected(b_view, monkeypatch):
    import numpy as np
    monkeypatch.setattr(b_view, "_ask_variable",
                        lambda: ("labels", pycdfpp.DataType.CDF_CHAR, True, np.array([b"x", b"y"])))

    b_view._new_variable()

    assert b_view.session.document["labels"].is_nrv
    assert b_view._inspector.current_variable == "labels"


def test_new_variable_with_a_taken_name_is_explained(b_view, monkeypatch):
    import numpy as np
    monkeypatch.setattr(b_view, "_ask_variable", lambda: ("B", pycdfpp.DataType.CDF_DOUBLE, True, np.ones(2)))
    b_view._new_variable()
    assert "B already exists" in b_view._preview_message.text()


def test_an_edit_relints_the_edited_document(b_view, qtbot, monkeypatch):
    linted = []
    monkeypatch.setattr(b_view, "_start_lint", linted.append)

    b_view._inspector.delete_attribute.emit("B", "CATDESC")
    b_view._inspector.delete_attribute.emit("B", "UNITS")

    qtbot.waitUntil(lambda: bool(linted), timeout=3000)
    qtbot.wait(200)
    assert len(linted) == 1
    attributes = pycdfpp.load(linted[0])["B"].attributes
    assert "CATDESC" not in attributes and "UNITS" not in attributes


def test_a_url_file_is_linted_from_memory_not_downloaded_again(qtbot, monkeypatch):
    import numpy as np
    from cdf_workbench.document import DocumentSession, from_cdf
    from cdf_workbench.file_view import CdfFileView
    linted = []
    monkeypatch.setattr(CdfFileView, "_start_lint", lambda self, source: linted.append(source))
    cdf = pycdfpp.CDF()
    cdf.add_variable("B", values=np.ones(3))

    view = CdfFileView(DocumentSession(from_cdf(cdf), source="https://example.org/f.cdf"),
                       source="https://example.org/f.cdf")
    qtbot.addWidget(view)

    qtbot.waitUntil(lambda: bool(linted), timeout=5000)
    assert len(linted) == 1 and isinstance(linted[0], bytes)
    view.release()


def test_export_plotted_data_as_csv(dist_view, tmp_path, monkeypatch):
    target = tmp_path / "dist.csv"
    monkeypatch.setattr(dist_view, "_ask_export_path", lambda name, filters: str(target))

    dist_view._export_data("dist")

    lines = target.read_text().splitlines()
    assert lines[0] == "time,10,100,1000,10000" and len(lines) == 4


_CLOSE_DURING_ANALYSIS = """
import gc, os, sys, time
import numpy as np, pycdfpp
from PySide6.QtWidgets import QApplication
app = QApplication([])
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QCoreApplication, QEvent
import cdf_workbench.file_view as fv
from cdf_workbench.workbench import CdfWorkbenchPanel
real_analyze = fv.analyze_quality
fv.analyze_quality = lambda **kw: time.sleep(1.5) or real_analyze(**kw)
cdf = pycdfpp.CDF()
for name in ("A", "B"):
    cdf.add_variable(name, values=np.ones(3))
    cdf[name].add_attribute("VAR_TYPE", "data")
path = os.path.join(sys.argv[2], "f.cdf")
pycdfpp.save(cdf, path)
panel = CdfWorkbenchPanel()
panel.open_file(path)
app.processEvents(); time.sleep(0.2)
panel._close_tab(0)
QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
gc.collect()
deadline = time.time() + 4
while time.time() < deadline:
    app.processEvents(); time.sleep(0.05); gc.collect()
print("survived", flush=True)
os._exit(0)
"""


def test_closing_a_tab_during_quality_analysis_does_not_abort(tmp_path):
    """Destroying a running QThread is a qFatal: SciQLop would abort and lose every unsaved tab."""
    import os, subprocess, sys
    plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run([sys.executable, "-c", _CLOSE_DURING_ANALYSIS, plugin_dir, str(tmp_path)],
                            capture_output=True,
                            text=True, timeout=60, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert result.returncode == 0 and "survived" in result.stdout, result.stderr[-2000:]


def test_lint_process_runs_to_completion(qtbot, tmp_path):
    import numpy as np
    from cdf_workbench.document import DocumentSession, from_cdf
    from cdf_workbench.file_view import CdfFileView
    cdf = pycdfpp.CDF()
    cdf.add_variable("B", values=np.ones(3))
    path = str(tmp_path / "f.cdf")
    pycdfpp.save(cdf, path)
    view = CdfFileView(DocumentSession(from_cdf(pycdfpp.load(path)), source=path), source=path)
    qtbot.addWidget(view)

    qtbot.waitUntil(lambda: view._lint_finished, timeout=30000)

    assert view._lint_exit_code == 0
    view.release()


def test_the_document_is_serialized_for_lint_off_the_gui_thread(b_view, qtbot, monkeypatch):
    from PySide6.QtCore import QThread
    import cdf_workbench.file_view as file_view
    on_gui_thread = []
    real = file_view._document_bytes
    monkeypatch.setattr(file_view, "_document_bytes",
                        lambda doc: on_gui_thread.append(QThread.currentThread() is qtbot_main) or real(doc))
    qtbot_main = QThread.currentThread()
    linted = []
    monkeypatch.setattr(b_view, "_start_lint", linted.append)

    b_view._lint_document()

    qtbot.waitUntil(lambda: bool(linted), timeout=5000)
    assert on_gui_thread == [False]


def test_a_document_that_cannot_be_serialized_is_just_not_linted(b_view, qtbot, monkeypatch):
    import cdf_workbench.file_view as file_view
    monkeypatch.setattr(file_view, "_document_bytes", lambda doc: (_ for _ in ()).throw(ValueError("CDF_BYTE")))
    linted = []
    monkeypatch.setattr(b_view, "_start_lint", linted.append)

    b_view._lint_document()

    qtbot.wait(300)
    assert linted == []


def test_replace_fill_on_integer_data_with_a_nan_fillval():
    import numpy as np
    from cdf_workbench.file_view import _replace_fill
    assert _replace_fill(np.array([1, 2], dtype=np.int32), float("nan")).tolist() == [1.0, 2.0]


def test_sparkline_masks_a_float32_fillval():
    import numpy as np
    from cdf_workbench.document import from_cdf
    from cdf_workbench.file_view import AnalysisWorker
    from cdf_workbench.tree_model import CdfTreeModel
    cdf = pycdfpp.CDF()
    cdf.add_variable("B", values=np.array([1.0, -1e31, 3.0], dtype=np.float32))
    cdf["B"].add_attribute("FILLVAL", [np.float32(-1e31)], pycdfpp.DataType.CDF_FLOAT)
    doc = from_cdf(cdf)
    info = CdfTreeModel(doc).variable_info("B")
    info.fill_value = -1e31
    worker = AnalysisWorker(doc, {"B": info})
    samples = []
    worker.sparkline_ready.connect(lambda name, s: samples.append(s))

    worker.run()

    assert samples == [[1.0, 3.0]]
