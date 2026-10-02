"""Events tab — pick an earthquake, then list stations around it.

Same threading model as the Stations tab (`QThreadPool` + `QRunnable`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from PySide6.QtCore import (
    QObject, QRunnable, Qt, QThreadPool, Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateTimeEdit, QDoubleSpinBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QVBoxLayout, QWidget,
)

from .dock_stations import _waterfall_supported, open_waterfall
from .fdsn_client import search_events, search_stations
from .sortable import SortableTableItem, sorting_paused


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
        # (origin lat/lon, start, stop) behind the stations table; committed only when
        # results land, so a failed search never pairs old stations with a new event.
        self._stations_query = self._pending_stations_query = None

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
        self.events_table.setSortingEnabled(True)
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
        self.routing_combo = QComboBox()
        self.routing_combo.addItems(["iris-federator", "eida-routing", "IRIS", "RESIF", "GEOFON", "IPGP"])
        self.find_stations_button = QPushButton("Find stations")
        self.add_all_button = QPushButton("Add all to inventory")
        self.plot_waterfall_button = QPushButton("Plot waterfall")
        self.plot_waterfall_button.setToolTip(
            "Selected stations stacked in one plot, nearest first to the event")
        if not _waterfall_supported():
            self.plot_waterfall_button.setEnabled(False)
            self.plot_waterfall_button.setToolTip("Waterfall plots need SciQLop >= 0.13")
        for label, w in (
            ("Min radius°", self.min_radius_spin),
            ("Max radius°", self.max_radius_spin),
            ("Chan filter", self.channel_edit),
            ("Routing", self.routing_combo),
        ):
            radius_row.addWidget(QLabel(label))
            radius_row.addWidget(w)
        radius_row.addWidget(self.find_stations_button)
        radius_row.addWidget(self.add_all_button)
        radius_row.addWidget(self.plot_waterfall_button)
        root.addLayout(radius_row)

        self.stations_table = QTableWidget(0, 5)
        self.stations_table.setHorizontalHeaderLabels(
            ["Network", "Station", "Loc.Chan", "Sample rate", "Coverage"]
        )
        self.stations_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stations_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.stations_table.setSortingEnabled(True)
        self.stations_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.stations_table, 1)

        self.search_button.clicked.connect(self._on_search_events)
        self.find_stations_button.clicked.connect(self._on_find_stations)
        self.add_all_button.clicked.connect(self._on_add_all)
        self.plot_waterfall_button.clicked.connect(self._on_plot_waterfall)

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
        with sorting_paused(self.events_table):
            self.events_table.setRowCount(len(self._events))
            for row, event in enumerate(self._events):
                self._fill_event_row(row, event)
        self._status_sink(f"Found {len(self._events)} event(s)")
        self.search_finished.emit()

    def _fill_event_row(self, row: int, event) -> None:
        origin = event.preferred_origin()
        mag = event.preferred_magnitude()
        depth_km = (origin.depth or 0.0) / 1000.0
        t = origin.time.datetime
        cells = (
            SortableTableItem(t.isoformat()),
            SortableTableItem(f"{origin.latitude:.3f}", float(origin.latitude)),
            SortableTableItem(f"{origin.longitude:.3f}", float(origin.longitude)),
            SortableTableItem(f"{depth_km:.1f}", depth_km),
            SortableTableItem(f"{mag.mag:.1f}", float(mag.mag)),
        )
        cells[0].setData(Qt.ItemDataRole.UserRole, row)  # index into self._events
        for col, cell in enumerate(cells):
            self.events_table.setItem(row, col, cell)

    def _selected_event(self):
        """The selected event — looked up by the index its row carries, since a
        sorted table's row number no longer matches `self._events`."""
        item = self.events_table.item(self.events_table.currentRow(), 0)
        return None if item is None else self._events[item.data(Qt.ItemDataRole.UserRole)]

    def _on_events_failed(self, message: str):
        self._status_sink(f"Event search failed: {message}")
        self.search_finished.emit()

    def selected_origin(self) -> Optional[tuple[float, float]]:
        """(latitude, longitude) of the selected event, or None."""
        event = self._selected_event()
        if event is None:
            return None
        origin = event.preferred_origin()
        return float(origin.latitude), float(origin.longitude)

    def _on_find_stations(self):
        event = self._selected_event()
        if event is None:
            self._status_sink("No event selected")
            return
        origin = event.preferred_origin()
        t0 = origin.time.datetime
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
        t_start = t0 - timedelta(minutes=5)
        t_end = t0 + timedelta(minutes=25)
        self._pending_stations_query = ((origin.latitude, origin.longitude), t_start, t_end)
        self._status_sink("Searching stations around event…")
        QThreadPool.globalInstance().start(_SearchStationsRunnable(
            self._stations_signals,
            network="*", station="*", location="*",
            channel=self.channel_edit.text(),
            start_time=t_start, end_time=t_end,
            routing=self.routing_combo.currentText(),
            latitude=origin.latitude, longitude=origin.longitude,
            min_radius_deg=self.min_radius_spin.value(),
            max_radius_deg=self.max_radius_spin.value(),
        ))

    def _on_stations_completed(self, inv):
        self._stations_query = self._pending_stations_query
        rows = []
        for net in inv.networks:
            for sta in net.stations:
                for chan in sta.channels:
                    rows.append({
                        "network": net.code, "station": sta.code,
                        "latitude": sta.latitude, "longitude": sta.longitude,
                        "location": chan.location_code, "channel": chan.code,
                        "sample_rate": float(chan.sample_rate or 0.0),
                        "start_date": chan.start_date, "end_date": chan.end_date,
                    })
        with sorting_paused(self.stations_table):
            self.stations_table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                self._fill_station_row(r, row)
        self._status_sink(f"Found {len(rows)} channel(s) near event")
        self.stations_finished.emit()

    def _fill_station_row(self, r: int, row: dict) -> None:
        cells = (
            SortableTableItem(row["network"]),
            SortableTableItem(row["station"]),
            SortableTableItem(f"{row['location']}.{row['channel']}"),
            SortableTableItem(f"{row['sample_rate']:.2f} Hz", row["sample_rate"]),
            SortableTableItem(f"{row['start_date']} → {row['end_date']}"),
        )
        cells[0].setData(Qt.ItemDataRole.UserRole, row)
        for col, cell in enumerate(cells):
            self.stations_table.setItem(r, col, cell)

    def _on_stations_failed(self, message: str):
        self._status_sink(f"Station search failed: {message}")
        self.stations_finished.emit()

    def _selected_station_rows(self) -> list[dict]:
        return [self.stations_table.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
                for index in self.stations_table.selectionModel().selectedRows()]

    def _on_plot_waterfall(self):
        rows = self._selected_station_rows()
        if not rows or self._stations_query is None:
            self._status_sink("No station rows selected")
            return
        self._on_add_all()
        origin, start, stop = self._stations_query
        open_waterfall(self._provider, rows, origin, start, stop, status_sink=self._status_sink)

    def _on_add_all(self):
        selected = self._selected_station_rows()
        if not selected:
            self._status_sink("No station rows selected")
            return
        for row in selected:
            self._provider.add_channel(
                defer_refresh=True,
                network=row["network"], station=row["station"],
                location=row["location"], channel=row["channel"],
                start_date=_obspy_dt(row["start_date"]),
                stop_date=_obspy_dt(row["end_date"]),
                sampling_rate_hz=row["sample_rate"],
                routing=self.routing_combo.currentText(),
            )
        self._provider.update_inventory()
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
