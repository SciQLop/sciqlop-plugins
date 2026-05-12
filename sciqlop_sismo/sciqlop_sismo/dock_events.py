"""Events tab — pick an earthquake, then list stations around it.

Same threading model as the Stations tab (`QThreadPool` + `QRunnable`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from PySide6.QtCore import (
    QObject, QRunnable, Qt, QThreadPool, Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateTimeEdit, QDoubleSpinBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .fdsn_client import search_events, search_stations


class _EventsSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _SearchEventsRunnable(QRunnable):
    def __init__(self, signals: _EventsSignals, **kwargs):
        super().__init__()
        self._signals = signals
        self._kwargs = kwargs

    def run(self):
        try:
            cat = search_events(**self._kwargs)
            self._signals.completed.emit(cat)
        except Exception as exc:  # noqa: BLE001
            self._signals.failed.emit(f"{type(exc).__name__}: {exc}")


class _StationsSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class _SearchStationsRunnable(QRunnable):
    def __init__(self, signals: _StationsSignals, **kwargs):
        super().__init__()
        self._signals = signals
        self._kwargs = kwargs

    def run(self):
        try:
            inv = search_stations(**self._kwargs)
            self._signals.completed.emit(inv)
        except Exception as exc:  # noqa: BLE001
            self._signals.failed.emit(f"{type(exc).__name__}: {exc}")


class EventsTab(QWidget):
    search_finished = Signal()
    stations_finished = Signal()

    def __init__(self, provider, status_sink: Callable[[str], None], parent=None):
        super().__init__(parent)
        self._provider = provider
        self._status_sink = status_sink
        self._events_signals = _EventsSignals()
        self._events_signals.completed.connect(self._on_events_completed)
        self._events_signals.failed.connect(self._on_events_failed)
        self._stations_signals = _StationsSignals()
        self._stations_signals.completed.connect(self._on_stations_completed)
        self._stations_signals.failed.connect(self._on_stations_failed)
        self._events = []  # cached list of obspy.event.Event from latest search

        root = QVBoxLayout(self)
        row = QHBoxLayout()
        now = datetime.now(tz=timezone.utc)
        self.start_picker = QDateTimeEdit()
        self.start_picker.setCalendarPopup(True)
        self.start_picker.setDateTime(_qt_dt(now.replace(year=now.year - 1)))
        self.end_picker = QDateTimeEdit()
        self.end_picker.setCalendarPopup(True)
        self.end_picker.setDateTime(_qt_dt(now))
        self.min_mag_spin = QDoubleSpinBox()
        self.min_mag_spin.setRange(0.0, 10.0)
        self.min_mag_spin.setSingleStep(0.1)
        self.min_mag_spin.setValue(5.5)
        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["USGS", "EMSC", "ISC"])
        self.search_button = QPushButton("Search events")
        for label, w in (
            ("Start UTC", self.start_picker), ("End UTC", self.end_picker),
            ("Min mag", self.min_mag_spin), ("Catalog", self.provider_combo),
        ):
            row.addWidget(QLabel(label))
            row.addWidget(w)
        row.addWidget(self.search_button)
        root.addLayout(row)

        self.events_table = QTableWidget(0, 5)
        self.events_table.setHorizontalHeaderLabels(
            ["Origin time (UTC)", "Lat", "Lon", "Depth (km)", "Magnitude"]
        )
        self.events_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.events_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.events_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.events_table, 1)

        radius_row = QHBoxLayout()
        self.min_radius_spin = QDoubleSpinBox()
        self.min_radius_spin.setRange(0.0, 180.0)
        self.min_radius_spin.setValue(0.0)
        self.max_radius_spin = QDoubleSpinBox()
        self.max_radius_spin.setRange(0.0, 180.0)
        self.max_radius_spin.setValue(30.0)
        self.channel_edit = QLineEdit("HH?,BH?")
        self.find_stations_button = QPushButton("Find stations")
        self.add_all_button = QPushButton("Add all to inventory")
        for label, w in (
            ("Min radius°", self.min_radius_spin),
            ("Max radius°", self.max_radius_spin),
            ("Chan filter", self.channel_edit),
        ):
            radius_row.addWidget(QLabel(label))
            radius_row.addWidget(w)
        radius_row.addWidget(self.find_stations_button)
        radius_row.addWidget(self.add_all_button)
        root.addLayout(radius_row)

        self.stations_table = QTableWidget(0, 5)
        self.stations_table.setHorizontalHeaderLabels(
            ["Network", "Station", "Loc.Chan", "Sample rate", "Coverage"]
        )
        self.stations_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stations_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.stations_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.stations_table, 1)

        self.search_button.clicked.connect(self._on_search_events)
        self.find_stations_button.clicked.connect(self._on_find_stations)
        self.add_all_button.clicked.connect(self._on_add_all)

    def _on_search_events(self):
        self._status_sink(f"Searching {self.provider_combo.currentText()} events…")
        QThreadPool.globalInstance().start(_SearchEventsRunnable(
            self._events_signals,
            start_time=self.start_picker.dateTime().toPython().replace(tzinfo=timezone.utc),
            end_time=self.end_picker.dateTime().toPython().replace(tzinfo=timezone.utc),
            min_magnitude=self.min_mag_spin.value(),
            provider=self.provider_combo.currentText(),
        ))

    def _on_events_completed(self, catalog):
        self._events = list(catalog)
        self.events_table.setRowCount(len(self._events))
        for row, event in enumerate(self._events):
            origin = event.preferred_origin()
            mag = event.preferred_magnitude()
            t = origin.time.datetime
            self.events_table.setItem(row, 0, QTableWidgetItem(t.isoformat()))
            self.events_table.setItem(row, 1, QTableWidgetItem(f"{origin.latitude:.3f}"))
            self.events_table.setItem(row, 2, QTableWidgetItem(f"{origin.longitude:.3f}"))
            depth_km = (origin.depth or 0.0) / 1000.0
            self.events_table.setItem(row, 3, QTableWidgetItem(f"{depth_km:.1f}"))
            self.events_table.setItem(row, 4, QTableWidgetItem(f"{mag.mag:.1f}"))
        self._status_sink(f"Found {len(self._events)} event(s)")
        self.search_finished.emit()

    def _on_events_failed(self, message: str):
        self._status_sink(f"Event search failed: {message}")
        self.search_finished.emit()

    def _on_find_stations(self):
        idx = self.events_table.currentRow()
        if idx < 0 or idx >= len(self._events):
            self._status_sink("No event selected")
            return
        event = self._events[idx]
        origin = event.preferred_origin()
        t0 = origin.time.datetime
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
        t_start = t0 - timedelta(minutes=5)
        t_end = t0 + timedelta(minutes=25)
        self._status_sink("Searching stations around event…")
        QThreadPool.globalInstance().start(_SearchStationsRunnable(
            self._stations_signals,
            network="*", station="*", location="*",
            channel=self.channel_edit.text(),
            start_time=t_start, end_time=t_end,
            routing="iris-federator",
            latitude=origin.latitude, longitude=origin.longitude,
            min_radius_deg=self.min_radius_spin.value(),
            max_radius_deg=self.max_radius_spin.value(),
        ))

    def _on_stations_completed(self, inv):
        rows = []
        for net in inv.networks:
            for sta in net.stations:
                for chan in sta.channels:
                    rows.append({
                        "network": net.code, "station": sta.code,
                        "location": chan.location_code, "channel": chan.code,
                        "sample_rate": float(chan.sample_rate or 0.0),
                        "start_date": chan.start_date, "end_date": chan.end_date,
                    })
        self.stations_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.stations_table.setItem(r, 0, QTableWidgetItem(row["network"]))
            self.stations_table.setItem(r, 1, QTableWidgetItem(row["station"]))
            self.stations_table.setItem(r, 2, QTableWidgetItem(f"{row['location']}.{row['channel']}"))
            self.stations_table.setItem(r, 3, QTableWidgetItem(f"{row['sample_rate']:.2f} Hz"))
            self.stations_table.setItem(r, 4, QTableWidgetItem(f"{row['start_date']} → {row['end_date']}"))
            item = self.stations_table.item(r, 0)
            item.setData(Qt.ItemDataRole.UserRole, row)
        self._status_sink(f"Found {len(rows)} channel(s) near event")
        self.stations_finished.emit()

    def _on_stations_failed(self, message: str):
        self._status_sink(f"Station search failed: {message}")
        self.stations_finished.emit()

    def _on_add_all(self):
        selected = self.stations_table.selectionModel().selectedRows()
        if not selected:
            self._status_sink("No station rows selected")
            return
        for index in selected:
            row = self.stations_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            self._provider.add_channel(
                network=row["network"], station=row["station"],
                location=row["location"], channel=row["channel"],
                start_date=_obspy_dt(row["start_date"]),
                stop_date=_obspy_dt(row["end_date"]),
                sampling_rate_hz=row["sample_rate"],
                routing="iris-federator",
            )
        self._status_sink(f"Added {len(selected)} channel(s)")


def _qt_dt(dt: datetime):
    from PySide6.QtCore import QDateTime
    return QDateTime.fromString(dt.strftime("%Y-%m-%dT%H:%M:%S"), "yyyy-MM-ddTHH:mm:ss")


def _obspy_dt(value) -> datetime:
    if value is None:
        return datetime.now(tz=timezone.utc)
    if hasattr(value, "datetime"):
        d = value.datetime
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value))
