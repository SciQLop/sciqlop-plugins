"""SismoBrowserDock — top-level widget hosting three tabs.

The dock owns no plot widgets. Each tab discovers/imports channels and
calls `provider.add_channel(...)` to make them first-class Speasy
products visible in the SciQLop main inventory.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from .dock_stations import StationsTab


class SismoBrowserDock(QWidget):
    def __init__(self, provider, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Sismo")
        self._provider = provider

        root = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        self.stations_tab = StationsTab(provider=provider, status_sink=self._set_status)
        from .dock_events import EventsTab
        self.events_tab = EventsTab(provider=provider, status_sink=self._set_status)
        self.local_tab = QWidget()
        self.tab_widget.addTab(self.stations_tab, "Stations")
        self.tab_widget.addTab(self.events_tab, "Events")
        self.tab_widget.addTab(self.local_tab, "Local files")
        root.addWidget(self.tab_widget, 1)

        self.status_label = QLabel("ready")
        self.status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
