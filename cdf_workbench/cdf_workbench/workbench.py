from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QLabel, QFileDialog, QMessageBox,
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from .loader import load_cdf, CdfLoadError
from .file_view import CdfFileView


class CdfWorkbenchPanel(QWidget):
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self.setWindowTitle("CDF Workbench")
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.tabBarDoubleClicked.connect(self._on_tab_double_clicked)
        layout.addWidget(self._tabs)

        self._add_open_tab()

    def _add_open_tab(self):
        placeholder = QLabel("Drop CDF files here or double-click to open")
        placeholder.setAlignment(Qt.AlignCenter)
        self._tabs.addTab(placeholder, "+")

    def _on_tab_double_clicked(self, index: int):
        if self._tabs.tabText(index) == "+":
            self.open_file_dialog()

    def open_file_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open CDF Files", "", "CDF Files (*.cdf);;All Files (*)"
        )
        for path in paths:
            self.open_file(path)

    def open_file(self, source: str):
        try:
            cdf = load_cdf(source)
        except CdfLoadError as e:
            QMessageBox.warning(self, "Failed to open CDF", str(e))
            return

        file_view = CdfFileView(cdf, source=source, main_window=self._main_window)
        name = Path(source).name if not source.startswith("http") else source.split("/")[-1]

        insert_idx = max(0, self._tabs.count() - 1)
        self._tabs.insertTab(insert_idx, file_view, name)
        self._tabs.setCurrentIndex(insert_idx)

    def _close_tab(self, index: int):
        if self._tabs.tabText(index) == "+":
            return
        widget = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if isinstance(widget, CdfFileView):
            widget.release()
        widget.deleteLater()

    def dragEnterEvent(self, event: QDragEnterEvent):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile() or url.toString()
                self.open_file(path)
        elif mime.hasText():
            text = mime.text().strip()
            if text.endswith(".cdf"):
                self.open_file(text)
