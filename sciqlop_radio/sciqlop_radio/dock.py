"""RadioSpectraDock — the one widget the user sees.

Owns a fetch service and a QTabWidget. Selecting "Fetch" runs a Fido
search; clicking a result then "Plot selected" downloads (if not
cached) and opens each result in a new tab containing the colormap.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDateTimeEdit, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

from .fetch import RadioFetchService
from .plot import spectrogram_to_plot, RadioPlotError
from .reader import open_spectrogram
from .settings import RadioSettings
from .sources import SOURCES, RadioSource


class RadioSpectraDock(QWidget):
    """Source picker + time range + result list + plot tabs."""

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
        # Cancel is out-of-scope for the MVP; revisit when long-running EOVSA / SWAVES fetches surface as a real pain point.
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

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        root.addWidget(self.tabs, 2)

        # Wiring
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
            self._open_paths([Path(p) for p in paths])

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
        for row in rows:
            url = getattr(row, "url", None) or ""
            name = url.rsplit("/", 1)[-1] if url else repr(row)
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, row)
            self.results_list.addItem(item)
        self._set_status(f"Found {len(rows)} file(s)")
        self._results_changed.emit()

    def _on_search_failed(self, message: str):
        self.results_list.clear()
        self._set_status(f"Search failed: {message}")
        self._results_changed.emit()

    def _on_fetch_completed(self, ok: list, failed: list):
        self._open_paths(list(ok))
        msg = f"Downloaded {len(ok)} file(s)"
        if failed:
            msg += f"; {len(failed)} failed"
        self._set_status(msg)

    def _on_fetch_failed(self, message: str):
        self._set_status(f"Fetch failed: {message}")

    def _open_paths(self, paths: list[Path]):
        for path in paths:
            try:
                spec = open_spectrogram(path)
                plot = spectrogram_to_plot(spec, parent=self)
            except RadioPlotError as e:
                self._set_status(f"Failed to plot {path.name}: {e}")
                continue
            except Exception as e:  # noqa: BLE001 — final user-facing safety net
                self._set_status(f"Failed to plot {path.name}: {e}")
                continue
            self.tabs.addTab(plot, path.name)
            self.tabs.setCurrentWidget(plot)

    def _close_tab(self, index: int):
        widget = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if widget is not None:
            widget.deleteLater()

    def _set_status(self, text: str):
        self.status_label.setText(text)
        self._status_changed.emit()
