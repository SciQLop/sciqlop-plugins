"""X1: a table of each codec's size and speed for the current document, and a way to adopt one."""
from __future__ import annotations
from typing import Optional

import pycdfpp
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from .codec_compare import CODECS, CodecResult, try_codec, with_compression
from .document import DocumentSession
from .memory import available_memory, decoded_nbytes, format_bytes

_COLUMNS = ("Codec", "Size", "vs file", "Write", "Read", "Values")
# Encoding one codec holds the decoded values, the new CDF and its bytes.
_COPIES_PER_CODEC = 3


class _CodecSignals(QObject):
    result = Signal(object)  # CodecResult


class _CodecTask(QRunnable):
    def __init__(self, doc, signals: _CodecSignals):
        super().__init__()
        self._doc, self._signals = doc, signals
        self.cancelled = False

    def run(self):
        for codec in CODECS:
            if self.cancelled:
                return
            result = try_codec(self._doc, codec)
            try:
                self._signals.result.emit(result)
            except RuntimeError:  # the dialog was closed meanwhile
                return


def _cells(result: CodecResult, original_size: Optional[int]) -> list[str]:
    name = result.codec.name.removesuffix("_compression") + (" (experimental)" if result.experimental else "")
    if result.error:
        return [name, "can't write", "", "", "", result.error]
    change = f"{100 * (result.size / original_size - 1):+.0f} %" if original_size else ""
    return [name, format_bytes(result.size), change, f"{result.write_s:.2f} s", f"{result.read_s:.2f} s",
            "identical" if result.identical else "DIFFERENT"]


class CodecDialog(QDialog):
    def __init__(self, session: DocumentSession, original_size: Optional[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Compare codecs")
        self._session, self._original_size = session, original_size
        self._results: dict[pycdfpp.CompressionType, CodecResult] = {}

        self._table = QTableWidget(len(CODECS), len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for row, codec in enumerate(CODECS):
            self._table.setItem(row, 0, QTableWidgetItem(codec.name.removesuffix("_compression")))
            self._table.setItem(row, 1, QTableWidgetItem("…"))
        self._table.itemSelectionChanged.connect(self._update_use_button)
        self._message = QLabel("Every variable is re-encoded with each codec, then read back and compared.")
        self._message.setWordWrap(True)
        self._use = QPushButton("Use selected codec")
        self._use.setEnabled(False)
        self._use.clicked.connect(self.use_selected)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.addButton(self._use, QDialogButtonBox.AcceptRole)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._message)
        layout.addWidget(self._table)
        layout.addWidget(buttons)
        self.resize(720, 320)
        self._task = self._start()

    def _start(self) -> Optional[_CodecTask]:
        doc = self._session.document
        needed = _COPIES_PER_CODEC * sum(decoded_nbytes(var) for _, var in doc.items())
        if needed > (free := available_memory()):
            self._message.setText(f"Comparing codecs needs about {format_bytes(needed)}, "
                                  f"only {format_bytes(free)} of memory is free.")
            return None
        self._signals = _CodecSignals(self)
        self._signals.result.connect(self._show_result)
        task = _CodecTask(doc, self._signals)
        QThreadPool.globalInstance().start(task)
        return task

    def _show_result(self, result: CodecResult):
        self._results[result.codec] = result
        row = CODECS.index(result.codec)
        for column, text in enumerate(_cells(result, self._original_size)):
            item = QTableWidgetItem(text)
            item.setToolTip(text)
            self._table.setItem(row, column, item)
        self._table.resizeColumnsToContents()
        self._update_use_button()

    def finished_count(self) -> int:
        return len(self._results)

    def select(self, codec: pycdfpp.CompressionType):
        self._table.selectRow(CODECS.index(codec))

    def _selected(self) -> Optional[CodecResult]:
        rows = self._table.selectionModel().selectedRows()
        return self._results.get(CODECS[rows[0].row()]) if rows else None

    def _update_use_button(self):
        result = self._selected()
        self._use.setEnabled(result is not None and result.identical)

    def use_selected(self):
        """An ordinary edit: it undoes, and the next Save writes the file with this codec."""
        result = self._selected()
        if result is not None and result.identical:
            self._session.apply(lambda d: with_compression(d, result.codec))
            self.accept()

    def done(self, code: int):
        if self._task is not None:
            self._task.cancelled = True
        super().done(code)
