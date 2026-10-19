"""Add or edit one attribute: name, type and value(s)."""
from __future__ import annotations
from typing import Optional

import pycdfpp
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout,
)

from .edits import ATTRIBUTE_TYPES, read_attribute_form


class AttributeDialog(QDialog):
    def __init__(self, title: str, name: str, data_type: pycdfpp.DataType, entries: list[str],
                 multi_entry: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._multi_entry = multi_entry
        self._result = None

        self._name = QLineEdit(name)
        self._type = QComboBox()
        types = ATTRIBUTE_TYPES if data_type in ATTRIBUTE_TYPES else (data_type, *ATTRIBUTE_TYPES)
        for t in types:
            self._type.addItem(t.name, t)
        self._type.setCurrentIndex(self._type.findData(data_type))
        if multi_entry:
            self._value = QPlainTextEdit("\n".join(entries))
            hint = "One entry per line. Numbers and times are comma separated."
        else:
            self._value = QLineEdit(entries[0] if entries else "")
            hint = "Numbers and times are comma separated."
        self._error = QLabel()
        self._error.setStyleSheet("color: #e94560;")
        self._error.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Name", self._name)
        form.addRow("Type", self._type)
        form.addRow("Value", self._value)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel(hint))
        layout.addWidget(self._error)
        layout.addWidget(buttons)

    def _text(self) -> str:
        return self._value.toPlainText() if self._multi_entry else self._value.text()

    def _accept(self):
        try:
            self._result = read_attribute_form(self._name.text(), self._type.currentData(), self._text(),
                                               self._multi_entry)
        except ValueError as e:
            self._error.setText(str(e))
            return
        self.accept()

    def result_attribute(self) -> Optional[tuple[str, pycdfpp.DataType, list]]:
        return self._result
