"""RadioSpectraDock — Fido search/fetch dock that pushes results onto the
SciQLop main timeline as virtual products (per `user_api/virtual_products`).

The dock owns no plot widgets. Each fetched (or local) spectrogram is
converted to a 2-D `SpeasyVariable`, registered as a
`VirtualProductType.Spectrogram` at path `radio/<source>/<file-stem>`,
then plotted on a fresh `create_plot_panel()`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDateTimeEdit, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .fetch import RadioFetchService
from .plot import RadioPlotError, spectrogram_to_speasy_variable
from .reader import open_spectrogram
from .settings import RadioSettings
from .sources import SOURCES, RadioSource


# Extensions radiospectra has a parser for. STEREO/SWAVES also serves
# TDS-max .txt summaries via Fido — those are peak-amplitude time series,
# not dynamic spectra, so radiospectra can't (and shouldn't) read them.
_SUPPORTED_EXTENSIONS = (
    ".cdf", ".fits", ".fit", ".fits.gz", ".fit.gz",
    ".srs",   # RSTN ASCII flux
    ".r1", ".r2",  # Wind/WAVES daily binaries
)


def _is_supported_filename(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(ext) for ext in _SUPPORTED_EXTENSIONS)


def _safe_basename(path: Path) -> str:
    """Filesystem name minus extensions, lowercased, slashes stripped — safe to
    embed in a virtual-product tree path."""
    name = path.name
    for ext in (".fits.gz", ".fit.gz", ".fits", ".fit", ".cdf"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    return name.replace("/", "_")


class RadioSpectraDock(QWidget):
    """Source picker + time range + result list. No embedded plots."""

    _results_changed = Signal()
    _status_changed = Signal()

    def __init__(
        self,
        main_window=None,
        fetch_service: Optional[RadioFetchService] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Radio Spectra")
        self._main_window = main_window
        _cfg = RadioSettings()
        self._svc = fetch_service or RadioFetchService(
            cache_dir=_cfg.cache_dir,
            timeout_s=_cfg.download_timeout_s,
        )
        # Keep VirtualProduct refs alive; SciQLop tree holds the callback weakly.
        self._virtual_products: dict[str, object] = {}

        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.source_combo = QComboBox()
        for src in SOURCES:
            self.source_combo.addItem(src.label, src)
        controls.addWidget(QLabel("Source:"))
        controls.addWidget(self.source_combo, 1)

        self.open_local_button = QPushButton("Open local…")
        controls.addWidget(self.open_local_button)
        root.addLayout(controls)

        times = QHBoxLayout()
        now = QDateTime.currentDateTimeUtc()
        self.start_picker = QDateTimeEdit(now.addDays(-1))
        self.end_picker = QDateTimeEdit(now)
        for w in (self.start_picker, self.end_picker):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd HH:mm")
        times.addWidget(QLabel("Start (UTC):"))
        times.addWidget(self.start_picker)
        times.addWidget(QLabel("End (UTC):"))
        times.addWidget(self.end_picker)
        self.fetch_button = QPushButton("Fetch")
        times.addWidget(self.fetch_button)
        root.addLayout(times)

        self.results_list = QListWidget()
        self.results_list.setSelectionMode(QListWidget.ExtendedSelection)
        root.addWidget(self.results_list, 1)
        self.plot_button = QPushButton("Plot selected")
        root.addWidget(self.plot_button)

        self.status_label = QLabel("ready")
        self.status_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.fetch_button.clicked.connect(self._on_fetch_clicked)
        self.open_local_button.clicked.connect(self._on_open_local_clicked)
        self.plot_button.clicked.connect(self._on_plot_selected_clicked)
        self._svc.searchCompleted.connect(self._on_search_completed)
        self._svc.searchFailed.connect(self._on_search_failed)
        self._svc.fetchCompleted.connect(self._on_fetch_completed)
        self._svc.fetchFailed.connect(self._on_fetch_failed)

    def _on_fetch_clicked(self):
        source: RadioSource = self.source_combo.currentData()
        t0 = self.start_picker.dateTime().toPython().replace(tzinfo=timezone.utc)
        t1 = self.end_picker.dateTime().toPython().replace(tzinfo=timezone.utc)
        if t1 <= t0:
            self._set_status("End time must be after start time")
            return
        if not source.fido_instrument:
            self._set_status(f"{source.label} is local-only — use 'Open local…'")
            return
        self._set_status(f"Searching {source.label}…")
        self.results_list.clear()
        self._results_changed.emit()
        self._svc.search(source, t0, t1)

    def _on_open_local_clicked(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open local radio file", "", "Radio data (*.cdf *.fits *.fit *.fit.gz);;All files (*)"
        )
        if paths:
            self._plot_paths([Path(p) for p in paths], source_key="local")

    def _on_plot_selected_clicked(self):
        rows = [self.results_list.item(i).data(Qt.UserRole)
                for i in range(self.results_list.count())
                if self.results_list.item(i).isSelected()]
        if not rows:
            self._set_status("No rows selected")
            return
        self._set_status(f"Fetching {len(rows)} file(s)…")
        self._svc.fetch(rows)

    def _on_search_completed(self, rows: list):
        self.results_list.clear()
        kept = 0
        skipped: list[str] = []
        for row in rows:
            url = getattr(row, "url", None) or ""
            name = url.rsplit("/", 1)[-1] if url else repr(row)
            if not _is_supported_filename(name):
                skipped.append(name)
                continue
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, row)
            self.results_list.addItem(item)
            kept += 1
        msg = f"Found {kept} file(s)"
        if skipped:
            msg += f"; skipped {len(skipped)} (unsupported format)"
        self._set_status(msg)
        self._results_changed.emit()

    def _on_search_failed(self, message: str):
        self.results_list.clear()
        self._set_status(f"Search failed: {message}")
        self._results_changed.emit()

    def _on_fetch_completed(self, ok: list, failed: list):
        source: RadioSource = self.source_combo.currentData()
        source_key = source.key if source is not None else "fetched"
        self._plot_paths(list(ok), source_key=source_key)
        msg = f"Downloaded {len(ok)} file(s)"
        if failed:
            msg += f"; {len(failed)} failed"
        self._set_status(msg)

    def _on_fetch_failed(self, message: str):
        self._set_status(f"Fetch failed: {message}")

    def _plot_paths(self, paths: list[Path], source_key: str):
        """Convert each spectrogram → SpeasyVariable, register as a virtual
        product, then push onto a fresh main-timeline panel."""
        errors: list[tuple[str, str]] = []
        plotted = 0
        try:
            from SciQLop.user_api.plot import create_plot_panel
            from SciQLop.user_api.virtual_products import (
                create_virtual_product, VirtualProductType,
            )
        except ImportError as exc:
            self._set_status(f"SciQLop user-API unavailable: {exc}")
            return

        panel = None
        for path in paths:
            try:
                spec = open_spectrogram(path)
                variable = spectrogram_to_speasy_variable(spec)
            except RadioPlotError as e:
                errors.append((path.name, str(e)))
                continue
            except Exception as e:  # noqa: BLE001 — final user-facing safety net
                errors.append((path.name, f"{type(e).__name__}: {e}"))
                continue
            vp_path = f"radio/{source_key}/{_safe_basename(path)}"
            callback = _build_static_callback(variable)
            try:
                vp = create_virtual_product(
                    vp_path, callback, VirtualProductType.Spectrogram,
                )
            except Exception as e:  # noqa: BLE001
                errors.append((path.name, f"create_virtual_product: {type(e).__name__}: {e}"))
                continue
            self._virtual_products[vp_path] = vp
            if panel is None:
                panel = create_plot_panel()
            try:
                panel.plot(vp)
                plotted += 1
            except Exception as e:  # noqa: BLE001
                errors.append((path.name, f"plot: {type(e).__name__}: {e}"))

        if errors and plotted == 0:
            detail = "\n\n".join(f"{name}:\n  {err}" for name, err in errors)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Could not plot")
            box.setText(f"None of the {len(paths)} file(s) could be plotted.")
            box.setDetailedText(detail)
            box.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.exec()
            self._set_status(f"Plot failed for {len(errors)} file(s); see dialog for details")
        elif errors:
            self._set_status(
                f"Plotted {plotted} file(s); {len(errors)} failed — last: {errors[-1][1][:120]}"
            )
        elif plotted:
            self._set_status(f"Plotted {plotted} file(s)")

    def _set_status(self, text: str):
        self.status_label.setText(text)
        self._status_changed.emit()


def _build_static_callback(variable):
    """Closure SciQLop will call as `f(start, stop) → SpeasyVariable`.

    Radio data is a fixed time window (whatever was fetched); we return
    the same SpeasyVariable regardless of the requested range — SciQLop
    handles display clipping itself.
    """
    def _callback(start, stop):  # noqa: ARG001
        return variable
    return _callback
