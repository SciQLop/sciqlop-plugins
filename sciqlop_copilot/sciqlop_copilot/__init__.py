"""GitHub Copilot chat backend plugin for SciQLop's agent chat dock."""
import threading
import time
from pathlib import Path

__version__ = "0.1.0"

import PySide6QtAds as QtAds
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from SciQLop.components.agents import ensure_agent_dock, register_agent_backend
from SciQLop.components.theming.icons import register_icon, theme_adapted_icon

from .auth import DeviceFlowError, poll_access_token, request_device_code
from .backend import CopilotBackend, fetch_models
from .settings import load_github_token, save_github_token

_ICON_NAME = "sciqlop_copilot_chat"
_ICON_PATH = str(Path(__file__).parent / "resources" / "chat.svg")
_DOCK_TITLE = "Agents"


class _PollSignals(QObject):
    """Cross-thread bridge: signals emitted from the poll worker, delivered
    on the Qt main thread via auto-queued connections."""
    done = Signal(str)
    failed = Signal(str)


class _DeviceLoginDialog(QDialog):
    """Shows the device code + verification URL and polls GitHub until login completes.

    Polling runs in a worker thread so a blocking HTTP call never stalls the
    Qt main thread — and so the success signal reaches us even while the
    nested QDialog.exec() event loop is running under qasync.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in to GitHub Copilot")
        self._token: str | None = None
        self._code = request_device_code()
        self._cancelled = False

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "1. Open the link below in your browser\n"
            "2. Enter the code\n"
            "3. Authorize the app — this dialog will close automatically"
        ))
        url_label = QLabel(f'<a href="{self._code.verification_uri}">{self._code.verification_uri}</a>')
        url_label.setOpenExternalLinks(True)
        url_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(url_label)

        code_label = QLabel(f"<h2><code>{self._code.user_code}</code></h2>")
        code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(code_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        QDesktopServices.openUrl(self._code.verification_uri)

        self._signals = _PollSignals(self)
        self._signals.done.connect(self._on_success)
        self._signals.failed.connect(self._on_failure)
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _poll_loop(self) -> None:
        deadline = time.monotonic() + self._code.expires_in
        interval = max(self._code.interval, 1)
        while not self._cancelled and time.monotonic() < deadline:
            try:
                token = poll_access_token(self._code.device_code)
            except DeviceFlowError as e:
                self._signals.failed.emit(str(e))
                return
            except Exception as e:
                self._signals.failed.emit(f"{type(e).__name__}: {e}")
                return
            if token:
                self._signals.done.emit(token)
                return
            # Sleep in small slices so cancel is responsive.
            slept = 0.0
            while slept < interval and not self._cancelled:
                time.sleep(0.25)
                slept += 0.25
        if not self._cancelled:
            self._signals.failed.emit("device code expired — sign-in timed out")

    def _on_success(self, token: str) -> None:
        self._token = token
        self.accept()

    def _on_failure(self, msg: str) -> None:
        if self._cancelled:
            return
        QMessageBox.warning(self, "Sign-in failed", msg)
        self.reject()

    def reject(self) -> None:
        self._cancelled = True
        super().reject()

    @property
    def token(self) -> str | None:
        return self._token


def run_sign_in_flow(parent) -> bool:
    """Run the device-flow login dialog end-to-end. Returns True on success."""
    dialog = _DeviceLoginDialog(parent)
    if dialog.exec() != QDialog.Accepted or not dialog.token:
        return False
    save_github_token(dialog.token)
    # Let Qt render the dialog close before we block the main thread on the
    # token-exchange + /models HTTP calls inside fetch_models(), otherwise the
    # login dialog visually lingers until the fetch finishes.
    dialog.deleteLater()
    QApplication.processEvents()
    try:
        models = fetch_models()
        if models:
            CopilotBackend.model_choices = models
    except Exception:
        pass
    # Refresh the dock's model dropdown — the bind happened before the user
    # was signed in, so `model_choices` was still just [("Default", None)].
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


# Attached to CopilotBackend so the shared chat dock can call it.
def _backend_on_activated(self) -> None:
    if load_github_token():
        return
    # Defer so the dock finishes binding the session before we pop up a modal.
    QTimer.singleShot(0, lambda: run_sign_in_flow(self._main_window))


CopilotBackend.on_activated = _backend_on_activated


def load(main_window):
    register_icon(_ICON_NAME, lambda: QIcon(_ICON_PATH))
    icon = theme_adapted_icon(_ICON_NAME)

    if load_github_token():
        try:
            models = fetch_models()
            if models:
                CopilotBackend.model_choices = models
        except Exception:
            pass

    register_agent_backend(CopilotBackend)
    dock = ensure_agent_dock(main_window)
    dock.setWindowTitle(_DOCK_TITLE)
    dock.setWindowIcon(icon)

    dock_widget = main_window.dock_manager.findDockWidget(_DOCK_TITLE)
    if dock_widget is None:
        main_window.addWidgetIntoDock(QtAds.DockWidgetArea.RightDockWidgetArea, dock)
        dock_widget = main_window.dock_manager.findDockWidget(_DOCK_TITLE)
        if dock_widget:
            dock_widget.setIcon(icon)
            dock_widget.toggleView(False)
            toggle_action = dock_widget.toggleViewAction()
            toggle_action.setIcon(icon)
            main_window.toolBar.addAction(toggle_action)

    main_window.toolsMenu.addAction(icon, "Agent Chat", dock.show)

    return dock
