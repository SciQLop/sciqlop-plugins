"""Create a small variable (labels, support data) from typed values."""
from __future__ import annotations
from typing import Optional

import numpy as np
import pycdfpp
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
    QVBoxLayout,
)

from .edits import ATTRIBUTE_TYPES, read_variable_form


class VariableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New variable")
        self._result = None
        self._name = QLineEdit()
        self._type = QComboBox()
        for t in ATTRIBUTE_TYPES:
            self._type.addItem(t.name, t)
        self._nrv = QCheckBox("Same for all records (NRV)")
        self._nrv.setChecked(True)
        self._values = QPlainTextEdit()
        self._error = QLabel()
        self._error.setStyleSheet("color: #e94560;")
        self._error.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Type", self._type)
        form.addRow("", self._nrv)
        form.addRow("Values", self._values)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Text: one label per line. Numbers and times: comma separated.\n"
                                "Bigger arrays: plugins.cdf_workbench.add_variable(name, array, attrs) "
                                "in the console."))
        layout.addWidget(self._error)
        layout.addWidget(buttons)

    def _accept(self):
        try:
            self._result = read_variable_form(self._name.text(), self._type.currentData(),
                                              self._nrv.isChecked(), self._values.toPlainText())
        except ValueError as e:
            self._error.setText(str(e))
            return
        self.accept()

    def result_variable(self) -> Optional[tuple[str, pycdfpp.DataType, bool, np.ndarray]]:
        return self._result
