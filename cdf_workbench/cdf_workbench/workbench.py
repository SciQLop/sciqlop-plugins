from __future__ import annotations
import os
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse
from typing import Optional
from PySide6.QtCore import QEvent, QObject, QRunnable, QThreadPool, Qt, Signal
import pycdfpp
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QTabBar, QStyle, QFileDialog, QMenu, QMessageBox,
    QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QToolBar, QToolButton,
)
from PySide6.QtGui import QAction, QDragEnterEvent, QDropEvent, QIcon, QKeySequence
from .loader import load_cdf, CdfLoadError, DownloadCancelled
from .codec_dialog import CodecDialog
from .compare_view import CompareView
from .compare_rows import short_titles
from .document import DocumentSession, from_cdf, to_cdf
from .export import skeleton_yaml, subset
from .file_view import CdfFileView
from .open_page import OpenPage


def _is_url(source: str) -> bool:
    return source.startswith(("http://", "https://"))


def _source_key(source: str) -> str:
    """Two spellings of one local file (relative, symlink) are the same source."""
    return source if not source or _is_url(source) else os.path.realpath(source)


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
        self.cancelled = False

    def run(self):
        try:
            cdf = load_cdf(self._source, cancelled=lambda: self.cancelled)
        except DownloadCancelled:
            return
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


class _QuitGuard(QObject):
    """SciQLop has no hook for a plugin to cancel quitting, so watch the main window's Close.
    SciQLop sets `_closing` for its own second close and in --batch: no prompt then."""

    def __init__(self, window, panel: "CdfWorkbenchPanel"):
        super().__init__(window)
        self._panel = panel

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Close or getattr(obj, "_closing", False):
            return False
        try:
            allowed = self._panel.confirm_quit()
        except RuntimeError:  # the panel is already gone
            return False
        if not allowed:
            event.ignore()
        return not allowed


def install_quit_guard(window, panel: "CdfWorkbenchPanel") -> QObject:
    guard = _QuitGuard(window, panel)
    window.installEventFilter(guard)
    return guard


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
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._tabs)
        self._tabs.currentChanged.connect(self._update_actions)

        self._downloading: dict[str, str] = {}  # URL -> variable to select once open
        self._download_tasks: dict[str, _LoadTask] = {}
        self._load_signals = _LoadSignals(self)
        self._load_signals.loaded.connect(self._add_tab)
        self._load_signals.failed.connect(self._on_load_failed)
        self._add_open_tab()
        self._update_actions()

    def _build_toolbar(self) -> QToolBar:
        """What used to hide in right-click menus, acting on the current tab."""
        toolbar = QToolBar()
        toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        current = self._tabs.currentIndex
        self._actions = {
            "save": self._action("Save", "document-save", lambda: self.save_tab(current()), QKeySequence.Save),
            "save_as": self._action("Save As…", "document-save-as", lambda: self.save_tab_as(current()),
                                    QKeySequence.SaveAs),
            "undo": self._action("Undo", "edit-undo", self.undo_current, QKeySequence.Undo),
            "redo": self._action("Redo", "edit-redo", self.redo_current, QKeySequence.Redo),
            "compare": self._menu_action("Compare with", self._compare_menu),
            "export": self._menu_action("Export", self._export_menu),
            "compression": self._action("Compare compression…", "", lambda: self.compare_codecs(current())),
            "new_variable": self._action("New variable…", "list-add", self._new_variable_in_current),
        }
        for name, action in self._actions.items():
            toolbar.addAction(action)
            if name in ("redo", "export"):
                toolbar.addSeparator()
        for name in ("compare", "export"):
            toolbar.widgetForAction(self._actions[name]).setPopupMode(QToolButton.InstantPopup)
        return toolbar

    def _action(self, text: str, icon: str, slot, keys=None) -> QAction:
        action = QAction(QIcon.fromTheme(icon), text, self)
        if keys is not None:
            action.setShortcut(keys)
            action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self.addAction(action)
        action.triggered.connect(slot)
        return action

    def _menu_action(self, text: str, fill) -> QAction:
        action = QAction(text, self)
        menu = QMenu(self)
        menu.aboutToShow.connect(fill)
        action.setMenu(menu)
        return action

    def _update_actions(self, *_):
        view = self._view_at(self._tabs.currentIndex())
        session = view.session if view is not None else None
        for name, action in self._actions.items():
            action.setEnabled(session is not None)
        if session is not None:
            self._actions["save"].setEnabled(session.is_modified)
            self._actions["undo"].setEnabled(session.can_undo)
            self._actions["redo"].setEnabled(session.can_redo)

    def _fill_compare_menu(self, menu: QMenu, index: int) -> QMenu:
        for other in range(self._tabs.count()):
            if other != index and (view := self._view_at(other)) is not None:
                menu.addAction(_tab_name(view.session.source), lambda o=other: self.compare_tabs(index, o))
        menu.addSeparator()
        menu.addAction("File…", lambda: self.compare_with_file(index))
        return menu

    def _compare_menu(self) -> QMenu:
        menu = self._actions["compare"].menu()
        menu.clear()
        return self._fill_compare_menu(menu, self._tabs.currentIndex())

    def _export_menu(self) -> QMenu:
        menu = self._actions["export"].menu()
        menu.clear()
        index = self._tabs.currentIndex()
        menu.addAction("Structure as YAML…", lambda: self.export_structure(index))
        menu.addAction("Subset of variables…", lambda: self.save_subset(index))
        menu.addAction("Data of the selected variable…", self._export_selected_variable)
        return menu

    def _export_selected_variable(self):
        if (view := self._view_at(self._tabs.currentIndex())) is not None:
            view.export_selected()

    def _new_variable_in_current(self):
        if (view := self._view_at(self._tabs.currentIndex())) is not None:
            view._new_variable()

    def _add_open_tab(self):
        self._open_page = OpenPage()
        self._open_page.browse_requested.connect(self.open_file_dialog)
        self._open_page.open_requested.connect(self.open_file)
        self._open_page.cancel_requested.connect(self.cancel_downloads)
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
        """Local files load right away (lazily); URLs download in the background, once.
        A source that is already open just gets its tab shown."""
        if (view := self._view_of(source)) is not None:
            self._tabs.setCurrentWidget(view)
            if variable:
                view.select_variable(variable)
            return
        if _is_url(source):
            if source in self._downloading:
                self._downloading[source] = self._downloading[source] or variable
                return
            self._downloading[source] = variable
            self._download_tasks[source] = _LoadTask(source, variable, self._load_signals)
            self._show_downloads()
            QThreadPool.globalInstance().start(self._download_tasks[source])
            return
        try:
            cdf = load_cdf(source)
        except CdfLoadError as e:
            self._on_load_failed(source, str(e))
            return
        self._add_tab(source, variable, cdf)

    def _show_downloads(self, message: str = ""):
        names = ", ".join(_tab_name(url) for url in self._downloading)
        downloading = f"Downloading {names}…" if names else ""
        self._open_page.set_status(" ".join(part for part in (message, downloading) if part))
        self._open_page.set_cancellable(bool(self._downloading))

    def _download_done(self, source: str, message: str = ""):
        self._downloading.pop(source, None)
        self._download_tasks.pop(source, None)
        self._show_downloads(message)

    def cancel_downloads(self):
        """Stops at the next 1 MiB chunk; a result arriving anyway is ignored."""
        for task in self._download_tasks.values():
            task.cancelled = True
        self._download_tasks.clear()
        self._downloading.clear()
        self._show_downloads("Download cancelled.")

    def _view_of(self, source: str) -> Optional[CdfFileView]:
        key = _source_key(source)
        views = (self._view_at(i) for i in range(self._tabs.count()))
        return next((v for v in views if v is not None and _source_key(v.session.source) == key), None)

    def _on_load_failed(self, source: str, message: str):
        if _is_url(source) and source not in self._downloading:  # cancelled meanwhile
            return
        self._download_done(source, message)
        self._tabs.setCurrentWidget(self._open_page)

    def _add_tab(self, source: str, variable: str, cdf):
        if _is_url(source) and source not in self._downloading:  # cancelled meanwhile
            return
        variable = self._downloading.get(source) or variable
        self._download_done(source)
        file_view = CdfFileView(DocumentSession(from_cdf(cdf), source=source), source=source,
                                main_window=self._main_window)

        insert_idx = max(0, self._tabs.count() - 1)
        self._tabs.insertTab(insert_idx, file_view, _tab_name(source))
        self._tabs.setCurrentIndex(insert_idx)
        file_view.session.changed.connect(lambda: self._refresh_title(file_view))
        file_view.session.changed.connect(self._update_actions)
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

    def add_variable(self, name: str, values, attributes: Optional[dict] = None, is_nrv: bool = False,
                     data_type=None):
        """Add a variable to the current tab, e.g. from the console:
        plugins.cdf_workbench.add_variable("Bmag", np.linalg.norm(b, axis=1), {"DEPEND_0": "Epoch"})"""
        view = self._view_at(self._tabs.currentIndex())
        if view is None:
            raise ValueError("Open a CDF file in the CDF Workbench first")
        view.add_variable(name, values, attributes, is_nrv, data_type)

    def undo_current(self):
        if (view := self._view_at(self._tabs.currentIndex())) is not None:
            view.session.undo()

    def redo_current(self):
        if (view := self._view_at(self._tabs.currentIndex())) is not None:
            view.session.redo()

    def _show_tab_menu(self, pos):
        index = self._tabs.tabBar().tabAt(pos)
        if self._view_at(index) is None:
            return
        menu = QMenu(self)
        menu.addAction("Save", lambda: self.save_tab(index))
        menu.addAction("Save As…", lambda: self.save_tab_as(index))
        menu.addAction("Save subset…", lambda: self.save_subset(index))
        menu.addAction("Export structure as YAML…", lambda: self.export_structure(index))
        menu.addAction("Compare compression algorithms…", lambda: self.compare_codecs(index))
        self._fill_compare_menu(menu.addMenu("Compare with"), index)
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
        if not path:
            return False
        owner = self._view_of(path)
        if owner is not None and owner is not view:
            view.show_problem(f"{_tab_name(path)} is already open in another tab: close it first.")
            return False
        return self._save(view, path)

    def _save(self, view: CdfFileView, path: Optional[str]) -> bool:
        try:
            view.session.save(path)
        except Exception as e:  # pycdfpp raises OSError, ValueError for unwritable values
            view.show_problem(f"Can't save: {e}")
            return False
        return True

    def save_subset(self, index: int):
        """Chosen variables plus everything they point at, in a new file; the tab is unchanged."""
        view = self._view_at(index)
        if view is None:
            return
        names = self._ask_variables(list(view.session.document.keys()))
        if not names:
            return
        path = self._ask_save_path(f"{PurePosixPath(_tab_name(view.session.source)).stem}_subset.cdf")
        if path:
            self._write(view, lambda: pycdfpp.save(to_cdf(subset(view.session.document, names)), path))

    def export_structure(self, index: int):
        view = self._view_at(index)
        if view is None:
            return
        name = f"{PurePosixPath(_tab_name(view.session.source)).stem}.yaml"
        path = self._ask_export_path(name, "YAML (*.yaml *.yml)")
        if path:
            text = skeleton_yaml(view.session.document)
            self._write(view, lambda: Path(path).write_text(text))

    def compare_tabs(self, index: int, other: int):
        a, b = self._view_at(index), self._view_at(other)
        if a is not None and b is not None:
            self._open_compare(a, b.session.document, _tab_name(b.session.source))

    def compare_with_file(self, index: int):
        view = self._view_at(index)
        if view is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Compare with", "", "CDF Files (*.cdf);;All Files (*)")
        if not path:
            return
        try:
            other = from_cdf(load_cdf(path))
        except CdfLoadError as e:
            view.show_problem(str(e))
            return
        self._open_compare(view, other, _tab_name(path))

    def _open_compare(self, view: CdfFileView, other, other_name: str):
        name = _tab_name(view.session.source)
        compare = CompareView(view.session, other, (name, other_name))
        index = max(0, self._tabs.count() - 1)
        short_a, short_b = short_titles(name, other_name)
        self._tabs.insertTab(index, compare, f"{short_a} ↔ {short_b}")
        self._tabs.setTabToolTip(index, f"{name} ↔ {other_name}")
        self._tabs.setCurrentIndex(index)

    def compare_codecs(self, index: int):
        view = self._view_at(index)
        if view is None:
            return
        source = view.session.source
        size = os.path.getsize(source) if source and not _is_url(source) and os.path.exists(source) else None
        CodecDialog(view.session, original_size=size, parent=self).exec()

    @staticmethod
    def _write(view: CdfFileView, write):
        try:
            write()
        except Exception as e:  # OSError, or values pycdfpp can't write
            view.show_problem(f"Can't write: {e}")

    def _ask_variables(self, names: list[str]) -> list[str]:
        dialog = QDialog(self)
        dialog.setWindowTitle("Save subset: variables to keep")
        variables = QListWidget()
        for name in names:
            item = QListWidgetItem(name)
            item.setCheckState(Qt.Unchecked)
            variables.addItem(item)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(variables)
        layout.addWidget(buttons)
        if not dialog.exec():
            return []
        return [variables.item(i).text() for i in range(variables.count())
                if variables.item(i).checkState() == Qt.Checked]

    def _ask_export_path(self, name: str, filters: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Export", name, filters)
        return path

    def _ask_save_path(self, name: str) -> str:
        path, _ = QFileDialog.getSaveFileName(self, "Save CDF As", name, "CDF Files (*.cdf)")
        return path

    def _ask_unsaved(self, name: str) -> str:
        """'save', 'discard' or 'cancel'."""
        answer = QMessageBox.question(
            self, "Unsaved changes", f"Save the changes to {name}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        return {QMessageBox.Save: "save", QMessageBox.Discard: "discard"}.get(answer, "cancel")

    def confirm_quit(self) -> bool:
        """Before SciQLop quits: True to go on, False to stay (cancelled, or a save failed)."""
        modified = [i for i in range(self._tabs.count())
                    if (view := self._view_at(i)) is not None and view.session.is_modified]
        if not modified:
            return True
        answer = self._ask_unsaved_on_quit([_tab_name(self._view_at(i).session.source) for i in modified])
        if answer == "save":
            return all(self.save_tab(i) for i in modified)
        return answer == "discard"

    def _ask_unsaved_on_quit(self, names: list[str]) -> str:
        """'save', 'discard' or 'cancel'."""
        answer = QMessageBox.question(
            self, "Unsaved CDF files", "Save the changes to these files before quitting?\n\n" + "\n".join(names),
            QMessageBox.SaveAll | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.SaveAll)
        return {QMessageBox.SaveAll: "save", QMessageBox.Discard: "discard"}.get(answer, "cancel")

    def _close_comparisons_of(self, session: DocumentSession):
        """A comparison edits its target tab: it can't outlive it."""
        for i in reversed(range(self._tabs.count())):
            widget = self._tabs.widget(i)
            if isinstance(widget, CompareView) and widget.target is session:
                self._tabs.removeTab(i)
                widget.deleteLater()

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
            if widget.session is not None:
                self._close_comparisons_of(widget.session)
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
