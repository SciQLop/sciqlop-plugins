from __future__ import annotations
import numpy as np
import shiboken6
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout
from SciQLopPlots import SciQLopPlot, SciQLopPlotRange, SciQLopTimeSeriesPlot
try:
    from SciQLopPlots import SciQLopTheme
except ImportError:
    SciQLopTheme = None
from seaborn import color_palette as seaborn_color_palette
from SciQLop.core.plot_hints import PlotHints, apply_plot_hints


def _to_f64(arr: np.ndarray) -> np.ndarray:
    if arr.dtype == np.float64 and arr.flags["C_CONTIGUOUS"]:
        return arr
    return np.ascontiguousarray(arr, dtype=np.float64)


def _sciqlop_palette(n: int = 32) -> list[QColor]:
    return [QColor(int(r * 255), int(g * 255), int(b * 255)) for r, g, b in seaborn_color_palette(n_colors=n)]


def _make_theme():
    # Never pass a parent to SciQLopTheme — set_theme takes ownership and
    # a double-owned theme crashes when the plot is reparented/destroyed.
    if SciQLopTheme is None:
        return None
    try:
        from SciQLop.components.theming.palette import SCIQLOP_PALETTE
        is_dark = QColor(SCIQLOP_PALETTE.get("Window", "#ffffff")).lightnessF() < 0.5
        theme = SciQLopTheme.dark() if is_dark else SciQLopTheme.light()
        _MAP = {
            "set_background": "Base",
            "set_foreground": "Text",
            "set_grid": "Mid",
            "set_sub_grid": "Midlight",
            "set_selection": "Highlight",
            "set_legend_border": "Border",
        }
        for setter, key in _MAP.items():
            if key in SCIQLOP_PALETTE:
                getattr(theme, setter)(QColor(SCIQLOP_PALETTE[key]))
        if "Base" in SCIQLOP_PALETTE:
            c = QColor(SCIQLOP_PALETTE["Base"])
            c.setAlpha(200)
            theme.set_legend_background(c)
        return theme
    except Exception:
        return SciQLopTheme.dark() if SciQLopTheme else None


class CdfPreviewWidget(QWidget):
    """Preview widget using four SciQLopPlot instances.

    SciQLopPlot only supports one colormap per plot, and time-axis formatting
    requires SciQLopTimeSeriesPlot (which installs a QCPAxisTickerDateTime).
    We keep four plots — (line|cmap) x (plain|time) — and show the right one.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._plots = {
            (False, False): SciQLopPlot(self),             # line, plain
            (False, True):  SciQLopTimeSeriesPlot(self),   # line, time
            (True,  False): SciQLopPlot(self),             # cmap, plain
            (True,  True):  SciQLopTimeSeriesPlot(self),   # cmap, time
        }
        palette = _sciqlop_palette()
        for p in self._plots.values():
            p.set_color_palette(palette)
            theme = _make_theme()
            if theme is not None:
                p.set_theme(theme)
            self._layout.addWidget(p)
            p.hide()

        self._graphs = {k: None for k in self._plots}
        self._active_key: tuple[bool, bool] | None = None

    @property
    def _is_colormap(self) -> bool:
        return self._active_key is not None and self._active_key[0]

    def _show_plot(self, key: tuple[bool, bool]) -> SciQLopPlot:
        for k, p in self._plots.items():
            if k == key:
                p.show()
            else:
                p.hide()
        self._active_key = key
        return self._plots[key]

    def plot_variable(
        self,
        values: np.ndarray,
        epochs: np.ndarray | None = None,
        depend_1: np.ndarray | None = None,
        hints: PlotHints | None = None,
        is_time_axis: bool = False,
    ):
        hints = hints or PlotHints()
        x = _to_f64(epochs) if epochs is not None else np.arange(len(values), dtype=np.float64)
        v = _to_f64(values)
        is_spectrogram = hints.display_type == "spectrogram" and v.ndim == 2
        labels = list(hints.component_labels or [])

        if is_spectrogram:
            key = (True, is_time_axis)
            plot = self._show_plot(key)
            y = _to_f64(depend_1) if depend_1 is not None else np.arange(v.shape[1], dtype=np.float64)
            name = labels[0] if labels else "ColorMap"
            if self._graphs[key] is None:
                self._graphs[key] = plot.colormap(x, y, v, name=name)
            else:
                self._graphs[key].set_data(x, y, v)
                self._graphs[key].set_name(name)
            apply_plot_hints(plot, hints)
            if is_time_axis:
                plot.x_axis().set_range(SciQLopPlotRange(float(x[0]), float(x[-1])))
            plot.rescale_axes()
            # y_axis (left) has no plottables for colormaps — hide it so only
            # y2_axis (right, where the colormap data lives) is shown
            plot.y_axis().set_visible(False)
            plot.replot()
        elif v.ndim <= 2:
            key = (False, is_time_axis)
            plot = self._show_plot(key)
            n_components = v.shape[1] if v.ndim == 2 else 1
            if len(labels) < n_components:
                labels = labels + [f"#{i}" for i in range(len(labels), n_components)]
            elif len(labels) > n_components:
                labels = labels[:n_components]
            if self._graphs[key] is not None:
                shiboken6.delete(self._graphs[key])
                self._graphs[key] = None
            self._graphs[key] = plot.line(x, v, labels=labels)
            apply_plot_hints(plot, hints)
            if is_time_axis:
                plot.x_axis().set_range(SciQLopPlotRange(float(x[0]), float(x[-1])))
            plot.rescale_axes()
            plot.replot()

    def clear(self):
        for p in self._plots.values():
            p.hide()
        self._active_key = None

    @property
    def _line_plot(self):
        """Compatibility for tests."""
        if self._active_key and not self._active_key[0]:
            return self._plots[self._active_key]
        return self._plots[(False, False)]

    @property
    def _cmap_plot(self):
        """Compatibility for tests."""
        if self._active_key and self._active_key[0]:
            return self._plots[self._active_key]
        return self._plots[(True, False)]

    @property
    def _line_graph(self):
        """Compatibility for tests."""
        if self._active_key and not self._active_key[0]:
            return self._graphs[self._active_key]
        return self._graphs[(False, False)]

    @property
    def _cmap_graph(self):
        """Compatibility for tests."""
        if self._active_key and self._active_key[0]:
            return self._graphs[self._active_key]
        return self._graphs[(True, False)]
