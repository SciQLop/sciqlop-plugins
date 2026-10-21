"""The inspector's quality line and its Plot button."""
import pycdfpp
import pytest

from cdf_workbench.inspector import CdfInspectorWidget
from cdf_workbench.quality import QualityReport
from cdf_workbench.tree_model import VariableInfo


@pytest.fixture
def inspector(qtbot):
    w = CdfInspectorWidget()
    qtbot.addWidget(w)
    w.update_variable(VariableInfo(name="B", shape=(3,), cdf_type=pycdfpp.DataType.CDF_DOUBLE, var_type="data"))
    return w


def test_quality_is_one_line_coloured_by_level(inspector):
    inspector._update_quality(QualityReport(2.5, 0.0, 1, 10))
    assert inspector._quality_line.text() == "97.5% valid · 2.5% fill · 0% out of range · 1 gaps"
    assert inspector._quality_line.property("level") == "warning"


def test_plot_button_plots_in_a_new_panel(inspector, qtbot):
    with qtbot.waitSignal(inspector.plot_new_panel) as signal:
        inspector._plot.click()
    assert signal.args == ["B"]


def test_plot_menu_offers_panels_console_and_export(inspector, qtbot):
    inspector.set_panel_names(["Panel 1"])
    menu = inspector._plot_menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["In a new panel", "In Panel 1", "Send to console", "Export data…"]
    with qtbot.waitSignal(inspector.export_data) as signal:
        menu.actions()[-1].trigger()
    assert signal.args == ["B"]
