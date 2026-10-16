"""Opencode backend plugin for SciQLop's generic agent chat dock.

Registers `OpencodeBackend` with the shared agent registry and makes sure the
shared chat dock exists. All chat UI (the docked panel, its toolbar button and
icon, the Tools-menu entry) is owned by SciQLop core — this plugin contributes
only a backend.
"""

import threading
from typing import Callable, List

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
)

from SciQLop.components.agents import ensure_agent_dock, register_agent_backend

from . import installer
from .backend import (
    OpencodeBackend,
    fetch_models,
    is_managed,
    opencode_major_version,
    resolve_opencode_executable,
)


class _InstallSignals(QObject):
    """Cross-thread bridge: signals emitted from the install worker, delivered
    on the Qt main thread via auto-queued connections."""

    line = Signal(str)
    done = Signal()
    failed = Signal(str)


class _InstallDialog(QDialog):
    """Offers a one-click install (or upgrade) command and streams its progress.

    The command runs on a worker thread so a blocking npm install or
    `opencode upgrade` never stalls the Qt main thread.
    """

    def __init__(
        self,
        parent,
        title: str,
        message: str,
        action: str,
        command: Callable[[], List[str]],
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._cancelled = False
        self._command = command

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(message))
        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.hide()
        layout.addWidget(self._log)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self._install_button = buttons.addButton(action, QDialogButtonBox.AcceptRole)
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
            command = self._command()
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
        # Stay open: the upgrade is required, so the way out of a failure is
        # a retry, not a dead end.
        self._log.show()
        self._log.append(f"Failed: {msg}")
        self._install_button.setText("Retry")
        self._install_button.setEnabled(True)

    def reject(self) -> None:
        self._cancelled = True
        super().reject()


def _run_dialog_flow(parent, dialog: _InstallDialog) -> bool:
    """Run an install/upgrade dialog end-to-end. Returns True on success."""
    if dialog.exec() != QDialog.Accepted:
        return False
    # Let Qt render the dialog close before we block the main thread on the
    # model fetch, otherwise the dialog visually lingers until it finishes.
    dialog.deleteLater()
    QApplication.processEvents()
    _refresh_models(parent)
    return True


def _refresh_models(parent) -> None:
    try:
        models = fetch_models()
        if models:
            OpencodeBackend.model_choices = models
    except Exception:
        pass
    # Refresh the dock's model dropdown — it was bound before the install
    # or upgrade, so it still shows the old model list.
    try:
        window = parent.window() if hasattr(parent, "window") else None
        if window is not None:
            dock = ensure_agent_dock(window)
            reload = getattr(dock, "reload_backend_models", None)
            if callable(reload):
                reload()
    except Exception:
        pass


def run_install_flow(parent) -> bool:
    return _run_dialog_flow(parent, _InstallDialog(
        parent,
        title="Install opencode CLI?",
        message=(
            "The opencode CLI was not found on this machine.\n"
            "Install it now with the bundled npm? (~210 MB, no admin rights needed)"
        ),
        action="Install",
        command=lambda: installer.install_command(installer.ensure_managed_prefix()),
    ))


def run_upgrade_flow(parent, exe: str) -> bool:
    if is_managed(exe):
        message = (
            "SciQLop's opencode install is version 1, which is no longer supported.\n"
            "Upgrade it to opencode 2 to use the Opencode backend. (~210 MB download)"
        )
    else:
        message = (
            f"The opencode CLI at {exe} is version 1, which is no longer supported.\n"
            "Upgrade it to opencode 2 to use the Opencode backend. This runs\n"
            "'opencode upgrade --major', which also upgrades opencode in your terminal.\n"
            "Your configuration is kept."
        )
    return _run_dialog_flow(parent, _InstallDialog(
        parent,
        title="opencode 2 required",
        message=message,
        action="Upgrade",
        command=lambda: installer.upgrade_command(exe),
    ))


# Attached to OpencodeBackend so the shared chat dock can call it.
def _backend_on_activated(self) -> None:
    exe = resolve_opencode_executable()
    # Defer the modals so the dock finishes binding the session first.
    if exe is None:
        QTimer.singleShot(0, lambda: run_install_flow(self._main_window))
    elif opencode_major_version(exe) == 1:
        QTimer.singleShot(0, lambda: run_upgrade_flow(self._main_window, exe))


OpencodeBackend.on_activated = _backend_on_activated


def load(main_window):
    models = fetch_models()
    if models:
        OpencodeBackend.model_choices = models

    register_agent_backend(OpencodeBackend)
    return ensure_agent_dock(main_window)
