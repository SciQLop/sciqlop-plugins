"""Opencode backend plugin for SciQLop's generic agent chat dock.

Registers `OpencodeBackend` with the shared agent registry and makes sure the
shared chat dock exists. All chat UI (the docked panel, its toolbar button and
icon, the Tools-menu entry) is owned by SciQLop core — this plugin contributes
only a backend.
"""

import threading

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from SciQLop.components.agents import ensure_agent_dock, register_agent_backend

from . import installer
from .backend import OpencodeBackend, fetch_models, resolve_opencode_executable


class _InstallSignals(QObject):
    """Cross-thread bridge: signals emitted from the install worker, delivered
    on the Qt main thread via auto-queued connections."""

    line = Signal(str)
    done = Signal()
    failed = Signal(str)


class _InstallDialog(QDialog):
    """Offers the one-click npm install and streams its progress.

    The worker thread runs `npm install --prefix <user-data>/opencode
    opencode-ai` so a blocking install never stalls the Qt main thread.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Install opencode CLI?")
        self._cancelled = False

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "The opencode CLI was not found on this machine.\n"
                "Install it now with the bundled npm? (~180 MB, no admin rights needed)"
            )
        )
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.hide()
        layout.addWidget(self._log)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self._install_button = buttons.addButton("Install", QDialogButtonBox.AcceptRole)
        self._install_button.clicked.connect(self._start_install)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._signals = _InstallSignals(self)
        self._signals.line.connect(self._on_line)
        self._signals.done.connect(self.accept)
        self._signals.failed.connect(self._on_failure)

    def _start_install(self):
        self._install_button.setEnabled(False)
        self._log.show()
        try:
            prefix = installer.ensure_managed_prefix()
            command = installer.install_command(prefix)
        except Exception as e:
            self._on_failure(str(e))
            return
        self._thread = threading.Thread(
            target=self._install_loop, args=(command,), daemon=True
        )
        self._thread.start()

    def _install_loop(self, command) -> None:
        try:
            installer.run_install(command, on_line=self._signals.line.emit)
        except Exception as e:
            if not self._cancelled:
                self._signals.failed.emit(str(e))
            return
        if not self._cancelled:
            self._signals.done.emit()

    def _on_line(self, line: str) -> None:
        self._log.append(line)

    def _on_failure(self, msg: str) -> None:
        QMessageBox.warning(self, "Install failed", msg)
        self.reject()

    def reject(self) -> None:
        self._cancelled = True
        super().reject()


def run_install_flow(parent) -> bool:
    """Run the install dialog end-to-end. Returns True on success."""
    dialog = _InstallDialog(parent)
    if dialog.exec() != QDialog.Accepted:
        return False
    # Let Qt render the dialog close before we block the main thread on the
    # model fetch, otherwise the install dialog visually lingers until it
    # finishes.
    dialog.deleteLater()
    QApplication.processEvents()
    try:
        models = fetch_models()
        if models:
            OpencodeBackend.model_choices = models
    except Exception:
        pass
    # Refresh the dock's model dropdown — the bind happened before opencode
    # was installed, so `model_choices` was still just [("Default", None)].
    try:
        window = parent.window() if hasattr(parent, "window") else None
        if window is not None:
            dock = ensure_agent_dock(window)
            reload = getattr(dock, "reload_backend_models", None)
            if callable(reload):
                reload()
    except Exception:
        pass
    return True


# Attached to OpencodeBackend so the shared chat dock can call it.
def _backend_on_activated(self) -> None:
    if resolve_opencode_executable() is not None:
        return
    # Defer so the dock finishes binding the session before we pop up a modal.
    QTimer.singleShot(0, lambda: run_install_flow(self._main_window))


OpencodeBackend.on_activated = _backend_on_activated


def load(main_window):
    models = fetch_models()
    if models:
        OpencodeBackend.model_choices = models

    register_agent_backend(OpencodeBackend)
    return ensure_agent_dock(main_window)
