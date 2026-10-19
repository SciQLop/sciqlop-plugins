from __future__ import annotations
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QTabBar, QStyle, QFileDialog,
)
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from .loader import load_cdf, CdfLoadError
from .document import DocumentSession, from_cdf
from .file_view import CdfFileView
from .open_page import OpenPage


def _is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _tab_name(source: str) -> str:
    """File name of a path or URL; MMS SDC URLs carry it in ?file=."""
    if not _is_url(source):
        return PurePosixPath(source).name
    url = urlparse(source)
    return parse_qs(url.query).get("file", [PurePosixPath(url.path).name])[0]


class _LoadSignals(QObject):
    loaded = Signal(str, str, object)  # source, variable, pycdfpp.CDF
    failed = Signal(str, str)          # source, message


class _LoadTask(QRunnable):
    """Downloads and parses a URL off the GUI thread."""

    def __init__(self, source: str, variable: str, signals: _LoadSignals):
        super().__init__()
        self._source, self._variable, self._signals = source, variable, signals

    def run(self):
        try:
            cdf = load_cdf(self._source)
        except Exception as e:  # httpx.InvalidURL & co. are not CdfLoadError
            self._emit(self._signals.failed, self._source, str(e))
            return
        self._emit(self._signals.loaded, self._source, self._variable, cdf)

    @staticmethod
    def _emit(signal, *args):
        try:
            signal.emit(*args)
        except RuntimeError:  # the panel was closed during the download
            pass


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

        self._load_signals = _LoadSignals(self)
        self._load_signals.loaded.connect(self._add_tab)
        self._load_signals.failed.connect(self._on_load_failed)
        self._add_open_tab()

    def _add_open_tab(self):
        self._open_page = OpenPage()
        self._open_page.browse_requested.connect(self.open_file_dialog)
        self._open_page.open_requested.connect(self.open_file)
        index = self._tabs.addTab(self._open_page, "+")
        self._remove_close_button(index)

    def _remove_close_button(self, index: int):
        bar = self._tabs.tabBar()
        side = QTabBar.ButtonPosition(
            bar.style().styleHint(QStyle.SH_TabBar_CloseButtonPosition, None, bar)
        )
        bar.setTabButton(index, side, None)

    def _on_tab_double_clicked(self, index: int):
        if self._tabs.tabText(index) == "+":
            self.open_file_dialog()

    def open_file_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open CDF Files", "", "CDF Files (*.cdf);;All Files (*)"
        )
        for path in paths:
            self.open_file(path)

    def open_file(self, source: str, variable: str = ""):
        """Local files load right away (lazily); URLs download in the background."""
        if _is_url(source):
            self._open_page.set_status(f"Downloading {_tab_name(source)}…")
            QThreadPool.globalInstance().start(_LoadTask(source, variable, self._load_signals))
            return
        try:
            cdf = load_cdf(source)
        except CdfLoadError as e:
            self._on_load_failed(source, str(e))
            return
        self._add_tab(source, variable, cdf)

    def _on_load_failed(self, source: str, message: str):
        self._open_page.set_status(message)
        self._tabs.setCurrentWidget(self._open_page)

    def _add_tab(self, source: str, variable: str, cdf):
        self._open_page.set_status("")
        file_view = CdfFileView(DocumentSession(from_cdf(cdf)), source=source,
                                main_window=self._main_window)
        name = _tab_name(source)

        insert_idx = max(0, self._tabs.count() - 1)
        self._tabs.insertTab(insert_idx, file_view, name)
        self._tabs.setCurrentIndex(insert_idx)
        file_view.session.changed.connect(lambda: self._refresh_title(file_view, name))
        if variable:
            file_view.select_variable(variable)

    def _refresh_title(self, file_view: CdfFileView, name: str):
        index = self._tabs.indexOf(file_view)
        if index >= 0:
            modified = file_view.session is not None and file_view.session.is_modified
            self._tabs.setTabText(index, f"{name} •" if modified else name)

    def _close_tab(self, index: int):
        if self._tabs.tabText(index) == "+":
            return
        widget = self._tabs.widget(index)
        self._tabs.removeTab(index)
        if isinstance(widget, CdfFileView):
            widget.release()
        widget.deleteLater()

    def _release_all(self):
        for i in range(self._tabs.count()):
            w = self._tabs.widget(i)
            if isinstance(w, CdfFileView):
                w.release()

    def closeEvent(self, event):
        self._release_all()
        super().closeEvent(event)

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
