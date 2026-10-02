"""Stations tab — search + add to inventory.

Threading: a `QRunnable` runs `fdsn_client.search_stations` on the
global QThreadPool; results land on a queued `Signal` in the GUI
thread. No qasync (per `feedback_qasync_httpx_async_client`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from PySide6.QtCore import (
    QObject, QRunnable, Qt, QThreadPool, Signal,
)
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateTimeEdit, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTreeView, QVBoxLayout, QWidget,
)

from .fdsn_client import search_stations
from .sortable import SORT_ROLE, sortable_tree_item, sorting_paused
from .waterfall import order_rows, plot_live_waterfall


def _create_plot_panel():
    """Lazy import of SciQLop's plot panel helper.

    Raises ImportError if SciQLop's host runtime is not available
    (e.g. headless test).
    """
    from SciQLop.user_api.plot import create_plot_panel
    return create_plot_panel()


def _time_range(t0, t1):
    """Lazy import of SciQLop's TimeRange, mirroring `_create_plot_panel`."""
    from SciQLop.core import TimeRange
    return TimeRange(t0, t1)


def _waterfall_supported() -> bool:
    try:
        from SciQLop.user_api.plot import Waterfall  # noqa: F401 — SciQLop >= 0.13
    except ImportError:
        return False
    return True


def show_window(panel, start: datetime, stop: datetime) -> list[str]:
    """A fresh panel shows "now", where an archive often has no data yet (IU.ADK lagged
    ~8 h behind real time): show the searched window instead. Widen a shorter zoom
    limit, or SciQLopPlots silently clips the window to it."""
    try:
        span = (stop - start).total_seconds()
        if 0 < panel.zoom_limit_seconds < span:
            panel.zoom_limit_seconds = span
        panel.time_range = _time_range(start.timestamp(), stop.timestamp())
    except Exception as exc:  # noqa: BLE001
        return [f"couldn't set the time range: {exc}"]
    return []


_live_waterfalls = []  # strong refs: a feed must outlive the click handler that made it


def open_waterfall(provider, rows: list[dict], origin: Optional[tuple], start: datetime,
                   stop: datetime, status_sink: Callable[[str], None]) -> None:
    """A new panel with a live waterfall of `rows` (already registered with the
    provider), nearest first to `origin` when given, showing `start`..`stop`."""
    global _live_waterfalls
    try:
        panel = _create_plot_panel()
    except ImportError:
        status_sink("SciQLop main-window plot API unavailable")
        return
    rows = order_rows(rows, origin)
    try:
        feed = plot_live_waterfall(
            panel, rows, fetch=provider.get_data, t0=start.timestamp(), t1=stop.timestamp(),
            on_failures=lambda f: status_sink("Waterfall: failed " + "; ".join(f)),
        )
    except Exception as exc:  # noqa: BLE001
        status_sink(f"Waterfall failed: {type(exc).__name__}: {exc}")
        return
    _live_waterfalls = [w for w in _live_waterfalls if not w.stopped] + [feed]
    failures = show_window(panel, start, stop)
    summary = f"Waterfall of {len(rows)} channel(s)"
    status_sink(f"{summary}; " + "; ".join(failures) if failures else summary)


class _SearchSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _SearchRunnable(QRunnable):
    def __init__(self, signals: _SearchSignals, **kwargs):
        super().__init__()
        self._signals = signals
        self._kwargs = kwargs

    def run(self):
        try:
            inv = search_stations(**self._kwargs)
            self._signals.completed.emit(inv)
        except Exception as exc:  # noqa: BLE001
            self._signals.failed.emit(f"{type(exc).__name__}: {exc}")


class StationsTab(QWidget):
    search_finished = Signal()

    def __init__(self, provider, status_sink: Callable[[str], None], parent=None):
        super().__init__(parent)
        self._provider = provider
        self._status_sink = status_sink
        self.event_origin: Callable[[], Optional[tuple]] = lambda: None
        self._signals = _SearchSignals()
        self._signals.completed.connect(self._on_search_completed)
        self._signals.failed.connect(self._on_search_failed)

        root = QVBoxLayout(self)
        form = QHBoxLayout()
        self.network_edit = QLineEdit("G,FR,IU")
        self.station_edit = QLineEdit("*")
        self.location_edit = QLineEdit("*")
        self.channel_edit = QLineEdit("HH?,BH?")
        for label, w in (("Net", self.network_edit), ("Sta", self.station_edit),
                          ("Loc", self.location_edit), ("Chan", self.channel_edit)):
            form.addWidget(QLabel(label))
            form.addWidget(w)
        root.addLayout(form)

        times = QHBoxLayout()
        now = datetime.now(tz=timezone.utc)
        self.start_picker = QDateTimeEdit()
        self.start_picker.setCalendarPopup(True)
        self.start_picker.setDateTime(_to_qdatetime(now.replace(hour=0, minute=0, second=0, microsecond=0)))
        self.end_picker = QDateTimeEdit()
        self.end_picker.setCalendarPopup(True)
        self.end_picker.setDateTime(_to_qdatetime(now))
        for label, w in (("Start UTC", self.start_picker), ("End UTC", self.end_picker)):
            times.addWidget(QLabel(label))
            times.addWidget(w)
        self.routing_combo = QComboBox()
        self.routing_combo.addItems(
            ["iris-federator", "eida-routing", "IRIS", "RESIF", "GEOFON", "IPGP"]
        )
        times.addWidget(QLabel("Routing"))
        times.addWidget(self.routing_combo)
        self.search_button = QPushButton("Search")
        times.addWidget(self.search_button)
        root.addLayout(times)

        self.results_tree = QTreeView()
        self.results_tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.results_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["Code", "Sample rate", "Coverage"])
        self.results_tree.setModel(self._model)
        self.results_tree.setSortingEnabled(True)
        root.addWidget(self.results_tree, 1)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add to inventory")
        self.plot_waveform_button = QPushButton("Plot waveform")
        self.plot_spectrogram_button = QPushButton("Plot spectrogram")
        self.plot_waterfall_button = QPushButton("Plot waterfall")
        self.plot_waterfall_button.setToolTip(
            "Selected waveforms stacked in one plot, nearest first to the event "
            "selected in the Events tab")
        if not _waterfall_supported():
            self.plot_waterfall_button.setEnabled(False)
            self.plot_waterfall_button.setToolTip("Waterfall plots need SciQLop >= 0.13")
        for b in (self.add_button, self.plot_waveform_button, self.plot_spectrogram_button,
                  self.plot_waterfall_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.search_button.clicked.connect(self._on_search_clicked)
        self.add_button.clicked.connect(self._on_add_clicked)
        self.plot_waveform_button.clicked.connect(lambda: self._on_plot_clicked("waveform"))
        self.plot_spectrogram_button.clicked.connect(lambda: self._on_plot_clicked("spectrogram"))
        self.plot_waterfall_button.clicked.connect(self._on_waterfall_clicked)

    def _on_search_clicked(self):
        self._status_sink(f"Searching {self.routing_combo.currentText()}…")
        QThreadPool.globalInstance().start(_SearchRunnable(
            self._signals,
            network=self.network_edit.text(),
            station=self.station_edit.text(),
            location=self.location_edit.text(),
            channel=self.channel_edit.text(),
            start_time=self._picked_window()[0],
            end_time=self._picked_window()[1],
            routing=self.routing_combo.currentText(),
        ))

    def _picked_window(self) -> tuple:
        """The Start/End UTC pickers as aware UTC datetimes."""
        return tuple(p.dateTime().toPython().replace(tzinfo=timezone.utc)
                     for p in (self.start_picker, self.end_picker))

    def _on_search_completed(self, inv):
        self._populate_tree(inv)
        n_chans = sum(
            len(s.channels) for net in inv.networks for s in net.stations
        )
        self._status_sink(f"Found {n_chans} channel(s)")
        self.search_finished.emit()

    def _on_search_failed(self, message: str):
        self._status_sink(f"Search failed: {message}")
        self.search_finished.emit()

    def _populate_tree(self, inv):
        with sorting_paused(self.results_tree):
            self._model.clear()
            self._model.setSortRole(SORT_ROLE)
            self._model.setHorizontalHeaderLabels(["Code", "Sample rate", "Coverage"])
            for net in inv.networks:
                net_item = sortable_tree_item(net.code)
                for sta in net.stations:
                    sta_item = sortable_tree_item(sta.code)
                    for chan in sta.channels:
                        sta_item.appendRow(_channel_tree_row(net, sta, chan))
                    net_item.appendRow(_full_width_row(sta_item))
                self._model.appendRow(_full_width_row(net_item))
        self.results_tree.expandAll()

    def _on_add_clicked(self):
        rows = self._selected_channel_rows()
        if not rows:
            self._status_sink("No channel selected")
            return
        for payload in rows:
            self._provider.add_channel(
                defer_refresh=True,
                network=payload["network"], station=payload["station"],
                location=payload["location"], channel=payload["channel"],
                start_date=_obspy_to_dt(payload["start_date"]),
                stop_date=_obspy_to_dt(payload["end_date"]),
                sampling_rate_hz=payload["sample_rate"],
                routing=self.routing_combo.currentText(),
            )
        self._provider.update_inventory()
        self._status_sink(f"Added {len(rows)} channel(s) to inventory")

    def _on_plot_clicked(self, kind: str):
        rows = self._selected_channel_rows()
        if not rows:
            self._status_sink("No channel selected")
            return
        # Ensure channels are added to the SciQLop product tree as virtual
        # products (provider.add_channel registers them).
        self._on_add_clicked()
        try:
            panel = _create_plot_panel()
        except ImportError:
            self._status_sink("SciQLop main-window plot API unavailable")
            return
        failures = []
        for payload in rows:
            path = (
                f"sismo/{payload['network']}/{payload['station']}/"
                f"{payload['location']}.{payload['channel']}/{kind}"
            )
            # By path: the provider keeps raw EasyProvider objects, which panel.plot()
            # rejects (it takes user_api VirtualProducts), the registered path it takes.
            try:
                panel.plot_product(path)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{path}: {type(exc).__name__}: {exc}")
        failures += self._show_searched_window(panel)
        plotted = len(rows) - sum(1 for f in failures if f.startswith("sismo/"))
        summary = f"Plotted {plotted}/{len(rows)} {kind}(s)"
        self._status_sink(f"{summary}; failed: " + "; ".join(failures) if failures else summary)

    def _show_searched_window(self, panel) -> list[str]:
        return show_window(panel, *self._picked_window())

    def _on_waterfall_clicked(self):
        rows = self._selected_channel_rows()
        if not rows:
            self._status_sink("No channel selected")
            return
        self._on_add_clicked()
        open_waterfall(self._provider, rows, self.event_origin(), *self._picked_window(),
                       status_sink=self._status_sink)

    def _selected_channel_rows(self) -> list[dict]:
        rows = []
        for index in self.results_tree.selectionModel().selectedIndexes():
            if index.column() != 0:
                continue
            payload = self._model.itemFromIndex(index).data(Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict) and "channel" in payload:
                rows.append(payload)
        return rows


def _full_width_row(item) -> list:
    """Qt's tree sort stops descending at a parent with fewer columns than the
    sort column, so network/station rows get empty cells across all columns."""
    return [item, sortable_tree_item(""), sortable_tree_item("")]


def _channel_tree_row(net, sta, chan) -> list:
    rate = float(chan.sample_rate or 0.0)
    chan_item = sortable_tree_item(f"{chan.location_code}.{chan.code}")
    chan_item.setData({
        "network": net.code, "station": sta.code,
        "latitude": sta.latitude, "longitude": sta.longitude,
        "location": chan.location_code, "channel": chan.code,
        "sample_rate": rate,
        "start_date": chan.start_date,
        "end_date": chan.end_date,
    }, Qt.ItemDataRole.UserRole)
    return [chan_item,
            sortable_tree_item(f"{rate:.2f} Hz", rate),
            sortable_tree_item(f"{chan.start_date} → {chan.end_date}")]


def _to_qdatetime(dt: datetime):
    from PySide6.QtCore import QDateTime
    return QDateTime.fromString(dt.strftime("%Y-%m-%dT%H:%M:%S"), "yyyy-MM-ddTHH:mm:ss")


def _obspy_to_dt(value) -> datetime:
    if value is None:
        return datetime.now(tz=timezone.utc)
    if hasattr(value, "datetime"):
        d = value.datetime
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value))
