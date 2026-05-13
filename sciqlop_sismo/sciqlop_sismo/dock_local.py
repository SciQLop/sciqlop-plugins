"""Local files tab — open miniSEED / SAC via ObsPy."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)

from .local_files import import_file


class LocalFilesTab(QWidget):
    def __init__(self, provider, status_sink: Callable[[str], None], parent=None):
        super().__init__(parent)
        self._provider = provider
        self._status_sink = status_sink

        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.open_button = QPushButton("Open local…")
        controls.addWidget(self.open_button)
        controls.addStretch(1)
        root.addLayout(controls)

        self.files_list = QListWidget()
        root.addWidget(self.files_list, 1)

        self.open_button.clicked.connect(self._on_open_clicked)

    def _on_open_clicked(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open seismic file",
            "", "Seismic files (*.mseed *.sac);;All files (*)",
        )
        if not paths:
            return
        added = 0
        errors: list[tuple[str, str]] = []
        for p in paths:
            try:
                for info in import_file(Path(p)):
                    self._provider.add_channel_from_local(info, defer_refresh=True)
                    item = QListWidgetItem(
                        f"{info.network}.{info.station}.{info.location}.{info.channel}  {p}"
                    )
                    item.setData(Qt.ItemDataRole.UserRole, info)
                    self.files_list.addItem(item)
                    added += 1
            except Exception as exc:  # noqa: BLE001
                errors.append((str(p), f"{type(exc).__name__}: {exc}"))
        if added:
            self._provider.update_inventory()
        if errors and added == 0:
            self._status_sink(
                f"Failed to import any of {len(paths)} file(s); last: {errors[-1][1]}"
            )
        elif errors:
            self._status_sink(
                f"Imported {added} channel(s); {len(errors)} file(s) failed"
            )
        else:
            self._status_sink(f"Imported {added} channel(s)")
