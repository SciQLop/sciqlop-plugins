"""Tests for the CdfWorkbenchPanel tab lifecycle."""
import gc
import pytest
import numpy as np
import pycdfpp

pytest.importorskip("SciQLopPlots")

from PySide6.QtWidgets import QApplication


def force_gc():
    gc.collect()
    QApplication.processEvents()
    gc.collect()


@pytest.fixture
def cdf_file(tmp_path):
    path = tmp_path / "sample.cdf"
    cdf = pycdfpp.CDF()
    epochs = np.arange(
        np.datetime64("2020-01-01"),
        np.datetime64("2020-01-01T00:00:10"),
        np.timedelta64(1, "s"),
    ).astype("datetime64[ns]")
    cdf.add_variable("Epoch", values=epochs, is_nrv=False)
    cdf.add_variable(
        "Bt",
        values=np.random.rand(10).astype(np.float32),
        is_nrv=False,
    )
    cdf["Bt"].add_attribute("VAR_TYPE", "data")
    cdf["Bt"].add_attribute("DEPEND_0", "Epoch")
    cdf["Bt"].add_attribute("UNITS", "nT")
    cdf["Bt"].add_attribute("FILLVAL", [np.float32(-1e31)])
    cdf["Bt"].add_attribute("VALIDMIN", [np.float32(0.0)])
    cdf["Bt"].add_attribute("VALIDMAX", [np.float32(100.0)])
    cdf["Epoch"].add_attribute("VAR_TYPE", "support_data")
    pycdfpp.save(cdf, str(path))
    return str(path)


@pytest.fixture
def panel(qtbot):
    from cdf_workbench.workbench import CdfWorkbenchPanel
    w = CdfWorkbenchPanel()
    qtbot.addWidget(w)
    w.show()
    return w


def test_open_and_close_tab(panel, cdf_file, qtbot):
    """Opening a file then closing its tab must not crash."""
    panel.open_file(cdf_file)
    qtbot.wait(50)
    assert panel._tabs.count() == 2  # file tab + "+"
    panel._close_tab(0)
    qtbot.wait(50)
    force_gc()
    assert panel._tabs.count() == 1


def test_open_close_multiple_tabs(panel, cdf_file, qtbot):
    """Opening and closing multiple tabs in sequence must not crash."""
    for _ in range(3):
        panel.open_file(cdf_file)
        qtbot.wait(20)
    assert panel._tabs.count() == 4
    while panel._tabs.count() > 1:
        panel._close_tab(0)
        qtbot.wait(20)
        force_gc()
    assert panel._tabs.count() == 1
