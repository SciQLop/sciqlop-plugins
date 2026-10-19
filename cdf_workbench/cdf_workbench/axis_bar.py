"""One menu per non-record dimension of a distribution: plot / sum / mean / = slice."""
from __future__ import annotations
from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from .reduce import MEAN, PLOT, SUM, Mode, with_axis_mode


@dataclass(frozen=True)
class Axis:
    title: str
    slice_labels: tuple[str, ...]


def _options(axis: Axis) -> list[tuple[str, Mode]]:
    return [("plot", PLOT), ("sum", SUM), ("mean", MEAN)] + [
        (f"= {label}", index) for index, label in enumerate(axis.slice_labels)]


class AxisModeBar(QWidget):
    modes_changed = Signal(object)  # tuple[Mode, ...]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 2, 4, 2)
        self._combos: list[QComboBox] = []
        self._titles: list[str] = []
        self._modes: tuple[Mode, ...] = ()
        self.hide()

    def show_axes(self, axes: list[Axis], modes: tuple[Mode, ...]):
        self._clear_widgets()
        self._titles = [a.title for a in axes]
        for k, axis in enumerate(axes):
            combo = QComboBox()
            for text, mode in _options(axis):
                combo.addItem(text, mode)
            combo.activated.connect(lambda _row, k=k, c=combo: self.select(k, c.currentData()))
            self._layout.addWidget(QLabel(axis.title))
            self._layout.addWidget(combo)
            self._combos.append(combo)
        self._layout.addStretch()
        self._show_modes(modes)
        self.show()

    def clear(self):
        self._clear_widgets()
        self.hide()

    def titles(self) -> list[str]:
        return list(self._titles)

    def choices(self, axis: int) -> list[str]:
        combo = self._combos[axis]
        return [combo.itemText(i) for i in range(combo.count())]

    def select(self, axis: int, mode: Mode):
        self._show_modes(with_axis_mode(self._modes, axis, mode))
        self.modes_changed.emit(self._modes)

    def _show_modes(self, modes: tuple[Mode, ...]):
        self._modes = modes
        for combo, mode in zip(self._combos, modes):
            combo.setCurrentIndex(combo.findData(mode))

    def _clear_widgets(self):
        while (item := self._layout.takeAt(0)) is not None:
            if item.widget() is not None:
                item.widget().deleteLater()
        self._combos = []
        self._titles = []
