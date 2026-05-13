"""Stations tab — search + add to inventory.

Threading: a `QRunnable` runs `fdsn_client.search_stations` on the
global QThreadPool; results land on a queued `Signal` in the GUI
thread. No qasync (per `feedback_qasync_httpx_async_client`).
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Callable


def _get_logger():
    """Prefer SciQLop's logging plumbing so messages appear in its log widget."""
    try:
        from SciQLop.components import sciqlop_logging
        return sciqlop_logging.getLogger(__name__)
    except ImportError:
        return logging.getLogger(__name__)

from PySide6.QtCore import (
    QObject, QRunnable, Qt, QThreadPool, Signal,
)
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateTimeEdit, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTreeView, QVBoxLayout, QWidget,
)

from .fdsn_client import search_stations


def _create_plot_panel():
    """Lazy import of SciQLop's plot panel helper.

    Raises ImportError if SciQLop's host runtime is not available
    (e.g. headless test).
    """
    from SciQLop.user_api.plot import create_plot_panel
    return create_plot_panel()


_log = _get_logger()
_BUILD_TAG = "45e82dd+trace"  # bump on every push so we can see if SciQLop reloaded


def _trace(msg, *args):
    """Belt-and-braces: log AND print to stderr so it can't be filtered out."""
    try:
        _log.warning(msg, *args)
    except Exception:
        pass
    try:
        rendered = (msg % args) if args else msg
        print(f"[sismo] {rendered}", file=sys.stderr, flush=True)
    except Exception:
        pass


def _build_plot_callback(provider, uid: str):
    """Closure SciQLop will call as `f(start_epoch, stop_epoch) → arrays`.

    Bypasses SciQLop's ProductsModel (which is built once at startup
    and doesn't know about runtime-added channels) by feeding the panel
    directly via `plot_function(callback)`.
    """
    import numpy as np

    def _callback(start, stop):
        _trace("callback fired uid=%s start=%s stop=%s", uid, start, stop)
        try:
            t0 = datetime.fromtimestamp(float(start), tz=timezone.utc)
            t1 = datetime.fromtimestamp(float(stop), tz=timezone.utc)
            var = provider.get_data(uid, t0, t1)
        except Exception as exc:  # noqa: BLE001
            _trace("callback: provider.get_data raised for %s: %r", uid, exc)
            return []
        if var is None:
            _trace("callback: provider.get_data returned None for %s", uid)
            return []
        time = var.time.astype("datetime64[ns]").astype("int64").astype("float64") / 1e9
        values = np.ascontiguousarray(var.values.astype("float64"))
        _trace("callback returning time.shape=%s values.shape=%s axes=%s",
               time.shape, values.shape, len(var.axes))
        if values.ndim == 2 and len(var.axes) >= 2 and np.issubdtype(var.axes[1].values.dtype, np.number):
            return [time, var.axes[1].values.astype("float64"), values]
        return [time, values]

    return _callback


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
        root.addWidget(self.results_tree, 1)

        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add to inventory")
        self.plot_waveform_button = QPushButton("Plot waveform")
        self.plot_spectrogram_button = QPushButton("Plot spectrogram")
        for b in (self.add_button, self.plot_waveform_button, self.plot_spectrogram_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.search_button.clicked.connect(self._on_search_clicked)
        self.add_button.clicked.connect(self._on_add_clicked)
        self.plot_waveform_button.clicked.connect(lambda: self._on_plot_clicked("waveform"))
        self.plot_spectrogram_button.clicked.connect(lambda: self._on_plot_clicked("spectrogram"))

    def _on_search_clicked(self):
        self._status_sink(f"Searching {self.routing_combo.currentText()}…")
        QThreadPool.globalInstance().start(_SearchRunnable(
            self._signals,
            network=self.network_edit.text(),
            station=self.station_edit.text(),
            location=self.location_edit.text(),
            channel=self.channel_edit.text(),
            start_time=self.start_picker.dateTime().toPython().replace(tzinfo=timezone.utc),
            end_time=self.end_picker.dateTime().toPython().replace(tzinfo=timezone.utc),
            routing=self.routing_combo.currentText(),
        ))

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
        self._model.clear()
        self._model.setHorizontalHeaderLabels(["Code", "Sample rate", "Coverage"])
        for net in inv.networks:
            net_item = QStandardItem(net.code)
            net_item.setEditable(False)
            for sta in net.stations:
                sta_item = QStandardItem(sta.code)
                sta_item.setEditable(False)
                for chan in sta.channels:
                    loc_chan = f"{chan.location_code}.{chan.code}"
                    chan_item = QStandardItem(loc_chan)
                    chan_item.setEditable(False)
                    chan_item.setData({
                        "network": net.code, "station": sta.code,
                        "location": chan.location_code, "channel": chan.code,
                        "sample_rate": float(chan.sample_rate or 0.0),
                        "start_date": chan.start_date,
                        "end_date": chan.end_date,
                    }, Qt.ItemDataRole.UserRole)
                    rate_item = QStandardItem(f"{chan.sample_rate or 0:.2f} Hz")
                    rate_item.setEditable(False)
                    coverage = f"{chan.start_date} → {chan.end_date}"
                    cov_item = QStandardItem(coverage)
                    cov_item.setEditable(False)
                    sta_item.appendRow([chan_item, rate_item, cov_item])
                net_item.appendRow([sta_item])
            self._model.appendRow([net_item])
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
        _trace("plot button clicked kind=%s", kind)
        rows = self._selected_channel_rows()
        _trace("plot: %d row(s) selected", len(rows))
        # Always show clicked-button confirmation in the status bar (visible no matter what).
        self._status_sink(f"[sismo build {_BUILD_TAG}] Plot {kind} clicked, {len(rows)} row(s) selected")
        if not rows:
            return
        self._on_add_clicked()
        params = list(self._provider.flat_inventory.parameters.keys())
        _trace("plot: inventory parameters: %s", params)
        try:
            panel = _create_plot_panel()
            _trace("plot: panel created: %r", panel)
        except ImportError as exc:
            _trace("plot: create_plot_panel failed: %r", exc)
            self._status_sink("SciQLop main-window plot API unavailable")
            return
        plot_kwargs: dict = {}
        if kind == "spectrogram":
            try:
                from SciQLop.core.enums import GraphType
                plot_kwargs["graph_type"] = GraphType.ColorMap
                plot_kwargs["y_log_scale"] = True
                plot_kwargs["z_log_scale"] = False  # power is already in dB
            except ImportError:
                pass
        for payload in rows:
            param_uid = (
                f"{payload['network']}/{payload['station']}/"
                f"{payload['location']}.{payload['channel']}/{kind}"
            )
            label = (
                f"{payload['network']}.{payload['station']}."
                f"{payload['location']}.{payload['channel']}/{kind}"
            )
            callback = _build_plot_callback(self._provider, param_uid)
            try:
                result = panel.plot_function(callback, name=label, **plot_kwargs)
                _trace("plot: plot_function returned %r for uid=%s", result, param_uid)
            except Exception as exc:  # noqa: BLE001
                _trace("plot: plot_function raised for uid=%s: %r", param_uid, exc)
        self._status_sink(f"Plotted {len(rows)} {kind}(s)")

    def _selected_channel_rows(self) -> list[dict]:
        rows = []
        for index in self.results_tree.selectionModel().selectedIndexes():
            if index.column() != 0:
                continue
            payload = self._model.itemFromIndex(index).data(Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict) and "channel" in payload:
                rows.append(payload)
        return rows


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
