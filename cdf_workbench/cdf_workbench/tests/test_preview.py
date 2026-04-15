"""Tests for the CdfPreviewWidget — verifies line/spectrogram switching without crashes."""
import pytest
import gc
import numpy as np

pytest.importorskip("SciQLopPlots")

from PySide6.QtWidgets import QApplication


def process_events():
    QApplication.processEvents()


def force_gc():
    gc.collect()
    QApplication.processEvents()
    gc.collect()


@pytest.fixture
def preview(qtbot):
    from cdf_workbench.preview import CdfPreviewWidget
    w = CdfPreviewWidget()
    qtbot.addWidget(w)
    return w


def _make_line_data(n=100, components=1):
    x = np.arange(n, dtype=np.float64)
    if components == 1:
        y = np.random.rand(n).astype(np.float64)
    else:
        y = np.random.rand(n, components).astype(np.float64)
    return x, y


def _make_spectrogram_data(n=100, bins=32):
    x = np.arange(n, dtype=np.float64)
    y = np.arange(bins, dtype=np.float64)
    z = np.random.rand(n, bins).astype(np.float64)
    return x, y, z


def _line(labels):
    from SciQLop.core.plot_hints import PlotHints
    return PlotHints(component_labels=list(labels))


def _spec(labels):
    from SciQLop.core.plot_hints import PlotHints
    return PlotHints(display_type="spectrogram", component_labels=list(labels))


def test_plot_line(preview):
    x, y = _make_line_data()
    preview.plot_variable(values=y, epochs=x, hints=_line(["test"]))
    assert preview._line_graph is not None
    assert not preview._is_colormap


def test_plot_spectrogram(preview):
    x, y, z = _make_spectrogram_data()
    preview.plot_variable(values=z, epochs=x, depend_1=y, hints=_spec(["spec"]))
    assert preview._cmap_graph is not None
    assert preview._is_colormap


def test_switch_line_to_spectrogram(preview):
    x, y = _make_line_data()
    preview.plot_variable(values=y, epochs=x, hints=_line(["line"]))
    assert not preview._is_colormap

    x2, y2, z2 = _make_spectrogram_data()
    preview.plot_variable(values=z2, epochs=x2, depend_1=y2, hints=_spec(["spec"]))
    assert preview._is_colormap
    assert preview._cmap_graph is not None


def test_switch_spectrogram_to_line(preview):
    x, y, z = _make_spectrogram_data()
    preview.plot_variable(values=z, epochs=x, depend_1=y, hints=_spec(["spec"]))
    assert preview._is_colormap

    x2, y2 = _make_line_data()
    preview.plot_variable(values=y2, epochs=x2, hints=_line(["line"]))
    assert not preview._is_colormap
    assert preview._line_graph is not None


def test_multiple_switches(preview):
    """Switch between line and spectrogram multiple times without crash."""
    for i in range(5):
        x, y = _make_line_data()
        preview.plot_variable(values=y, epochs=x, hints=_line([f"line{i}"]))
        assert not preview._is_colormap

        x2, y2, z2 = _make_spectrogram_data()
        preview.plot_variable(values=z2, epochs=x2, depend_1=y2, hints=_spec([f"spec{i}"]))
        assert preview._is_colormap


def test_multiple_spectrograms_reuses_graph(preview):
    """Plot multiple spectrograms in sequence — graph is reused via set_data."""
    for i in range(5):
        x, y, z = _make_spectrogram_data(n=50 + i * 10)
        preview.plot_variable(values=z, epochs=x, depend_1=y, hints=_spec([f"spec{i}"]))
        assert preview._is_colormap
        assert preview._cmap_graph is not None


def test_multiple_lines_reuses_graph(preview):
    """Plot multiple lines in sequence — graph is reused via set_data."""
    for i in range(5):
        x, y = _make_line_data(n=50 + i * 10)
        preview.plot_variable(values=y, epochs=x, hints=_line([f"line{i}"]))
        assert not preview._is_colormap
        assert preview._line_graph is not None


def test_labels_updated_on_reuse(preview):
    """Labels are updated when reusing a line graph."""
    x, y = _make_line_data()
    preview.plot_variable(values=y, epochs=x, hints=_line(["first"]))
    assert preview._line_graph.labels() == ["first"]

    x2, y2 = _make_line_data()
    preview.plot_variable(values=y2, epochs=x2, hints=_line(["second"]))
    assert preview._line_graph.labels() == ["second"]


def test_multicomponent_labels(preview):
    """Multi-component data gets correct labels."""
    x, y = _make_line_data(components=3)
    preview.plot_variable(values=y, epochs=x, hints=_line(["Bx", "By", "Bz"]))
    assert preview._line_graph.labels() == ["Bx", "By", "Bz"]


def test_component_count_change(preview):
    """Switching from 3-component to 1-component line graph."""
    x, y = _make_line_data(components=3)
    preview.plot_variable(values=y, epochs=x, hints=_line(["Bx", "By", "Bz"]))
    assert preview._line_graph.line_count() == 3

    x2, y2 = _make_line_data(components=1)
    preview.plot_variable(values=y2, epochs=x2, hints=_line(["Bt"]))
    assert preview._line_graph.line_count() == 1


def test_component_count_increase(preview):
    """Switching from 1-component to 3-component line graph."""
    x, y = _make_line_data(components=1)
    preview.plot_variable(values=y, epochs=x, hints=_line(["Bt"]))

    x2, y2 = _make_line_data(components=3)
    preview.plot_variable(values=y2, epochs=x2, hints=_line(["Bx", "By", "Bz"]))
    assert preview._line_graph.line_count() == 3


def test_label_count_mismatch_fewer(preview):
    """Fewer labels than components — should pad, not crash."""
    x, y = _make_line_data(components=3)
    preview.plot_variable(values=y, epochs=x, hints=_line(["only_one"]))
    assert preview._line_graph is not None
    assert preview._line_graph.line_count() == 3


def test_label_count_mismatch_more(preview):
    """More labels than components — should truncate, not crash."""
    x, y = _make_line_data(components=1)
    preview.plot_variable(values=y, epochs=x, hints=_line(["a", "b", "c"]))
    assert preview._line_graph is not None
    assert preview._line_graph.line_count() == 1


def test_reuse_with_mismatched_labels(preview):
    """Reuse graph: first 3 components, then 3 components with 1 label."""
    x, y = _make_line_data(components=3)
    preview.plot_variable(values=y, epochs=x, hints=_line(["Bx", "By", "Bz"]))

    x2, y2 = _make_line_data(components=3)
    preview.plot_variable(values=y2, epochs=x2, hints=_line(["Bt"]))
    assert preview._line_graph.line_count() == 3


def test_clear(preview):
    x, y = _make_line_data()
    preview.plot_variable(values=y, epochs=x, hints=_line(["test"]))
    preview.clear()
    assert not preview._is_colormap


def test_clear_then_plot(preview):
    x, y = _make_line_data()
    preview.plot_variable(values=y, epochs=x, hints=_line(["test"]))
    preview.clear()

    x2, y2, z2 = _make_spectrogram_data()
    preview.plot_variable(values=z2, epochs=x2, depend_1=y2, hints=_spec(["spec"]))
    assert preview._is_colormap
    assert preview._cmap_graph is not None


def test_destroy_with_graphs(preview, qtbot):
    """Widget with graphs can be destroyed without crash."""
    x, y = _make_line_data()
    preview.plot_variable(values=y, epochs=x, hints=_line(["test"]))

    x2, y2, z2 = _make_spectrogram_data()
    preview.plot_variable(values=z2, epochs=x2, depend_1=y2, hints=_spec(["spec"]))
    del preview
    force_gc()
