from __future__ import annotations
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse
from typing import Optional
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QTabBar, QStyle, QFileDialog, QMenu, QMessageBox,
)
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
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
        self._tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self._tabs.tabBar().customContextMenuRequested.connect(self._show_tab_menu)
        layout.addWidget(self._tabs)
        self._add_shortcut(QKeySequence.Save, lambda: self.save_tab(self._tabs.currentIndex()))
        self._add_shortcut(QKeySequence.SaveAs, lambda: self.save_tab_as(self._tabs.currentIndex()))

        self._load_signals = _LoadSignals(self)
        self._load_signals.loaded.connect(self._add_tab)
        self._load_signals.failed.connect(self._on_load_failed)
        self._add_open_tab()

    def _add_shortcut(self, keys, slot):
        action = QAction(self)
        action.setShortcut(keys)
        action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        action.triggered.connect(slot)
        self.addAction(action)

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
        file_view = CdfFileView(DocumentSession(from_cdf(cdf), source=source), source=source,
                                main_window=self._main_window)

        insert_idx = max(0, self._tabs.count() - 1)
        self._tabs.insertTab(insert_idx, file_view, _tab_name(source))
        self._tabs.setCurrentIndex(insert_idx)
        file_view.session.changed.connect(lambda: self._refresh_title(file_view))
        if variable:
            file_view.select_variable(variable)

    def _refresh_title(self, file_view: CdfFileView):
        index = self._tabs.indexOf(file_view)
        session = file_view.session
        if index >= 0 and session is not None:
            name = _tab_name(session.source)
            self._tabs.setTabText(index, f"{name} •" if session.is_modified else name)

    def _view_at(self, index: int) -> Optional[CdfFileView]:
        widget = self._tabs.widget(index)
        return widget if isinstance(widget, CdfFileView) and widget.session is not None else None

    def _show_tab_menu(self, pos):
        index = self._tabs.tabBar().tabAt(pos)
        if self._view_at(index) is None:
            return
        menu = QMenu(self)
        menu.addAction("Save", lambda: self.save_tab(index))
        menu.addAction("Save As…", lambda: self.save_tab_as(index))
        menu.addSeparator()
        menu.addAction("Close", lambda: self._close_tab(index))
        menu.exec(self._tabs.tabBar().mapToGlobal(pos))

    def save_tab(self, index: int) -> bool:
        """URL-opened files have no file to save to: they go through Save As."""
        view = self._view_at(index)
        if view is None:
            return False
        if not view.session.can_save_in_place:
            return self.save_tab_as(index)
        return self._save(view, None)

    def save_tab_as(self, index: int) -> bool:
        view = self._view_at(index)
        if view is None:
            return False
        path = self._ask_save_path(_tab_name(view.session.source))
        return bool(path) and self._save(view, path)

    def _save(self, view: CdfFileView, path: Optional[str]) -> bool:
        try:
            view.session.save(path)
        except Exception as e:  # pycdfpp raises OSError, ValueError for unwritable values
            view.show_problem(f"Can't save: {e}")
            return False
        return True

    def _ask_save_path(self, name: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Save CDF As", name, "CDF Files (*.cdf)")
        return path

    def _ask_unsaved(self, name: str) -> str:
        """'save', 'discard' or 'cancel'."""
        answer = QMessageBox.question(
            self, "Unsaved changes", f"Save the changes to {name}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        return {QMessageBox.Save: "save", QMessageBox.Discard: "discard"}.get(answer, "cancel")

    def _close_tab(self, index: int):
        if self._tabs.tabText(index) == "+":
            return
        view = self._view_at(index)
        if view is not None and view.session.is_modified:
            answer = self._ask_unsaved(_tab_name(view.session.source))
            if answer == "cancel" or (answer == "save" and not self.save_tab(index)):
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
