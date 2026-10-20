"""E8: edit the values of a small variable (labels, support data) in a table."""
from __future__ import annotations
from typing import Optional

import numpy as np
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from .document import Variable
from .edits import values_from_grid, values_grid


class ValuesDialog(QDialog):
    def __init__(self, name: str, var: Variable, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Values of {name}")
        self._var, self._result = var, None
        grid = values_grid(var)
        self._table = QTableWidget(len(grid), len(grid[0]) if grid else 0)
        for r, row in enumerate(grid):
            for c, text in enumerate(row):
                self._table.setItem(r, c, QTableWidgetItem(text))
        self._table.resizeColumnsToContents()
        self._error = QLabel()
        self._error.setStyleSheet("color: #e94560;")
        hint = ("One record per row." if not var.is_nrv else "The same for every record (NRV): one value per row.")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{var.type.name}. {hint}"))
        layout.addWidget(self._table)
        layout.addWidget(self._error)
        layout.addWidget(buttons)

    def _cells(self) -> list[list[str]]:
        return [[self._table.item(r, c).text() for c in range(self._table.columnCount())]
                for r in range(self._table.rowCount())]

    def _accept(self):
        try:
            self._result = values_from_grid(self._cells(), self._var)
        except ValueError as e:
            self._error.setText(str(e))
            return
        self.accept()

    def result_values(self) -> Optional[np.ndarray]:
        return self._result
