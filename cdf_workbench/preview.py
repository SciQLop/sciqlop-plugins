from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import QWidget, QVBoxLayout
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class CdfPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._figure = Figure(figsize=(5, 2), dpi=100)
        self._figure.set_facecolor("none")
        self._canvas = FigureCanvasQTAgg(self._figure)
        layout.addWidget(self._canvas)

        self._ax = self._figure.add_subplot(111)

    def plot_variable(
        self,
        values: np.ndarray,
        epochs: np.ndarray | None = None,
        label: str = "",
        units: str = "",
        scale_type: str = "linear",
        display_type: str = "",
    ):
        self._ax.clear()

        x = epochs if epochs is not None else np.arange(len(values))
        is_spectrogram = display_type.lower() == "spectrogram"

        if values.ndim == 1:
            self._ax.plot(x, values, linewidth=0.8)
        elif values.ndim == 2 and is_spectrogram:
            self._ax.pcolormesh(x, np.arange(values.shape[1]), values.T, shading="auto")
        elif values.ndim == 2:
            for i in range(values.shape[1]):
                self._ax.plot(x, values[:, i], linewidth=0.8)
        else:
            self._ax.pcolormesh(values, shading="auto")

        if units:
            self._ax.set_ylabel(units)
        if label:
            self._ax.set_title(label, fontsize=10)
        if scale_type == "log":
            self._ax.set_yscale("log")

        self._figure.tight_layout()
        self._canvas.draw()

    def clear(self):
        self._ax.clear()
        self._canvas.draw()
