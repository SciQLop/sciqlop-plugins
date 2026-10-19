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
