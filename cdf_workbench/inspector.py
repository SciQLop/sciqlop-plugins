from __future__ import annotations
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QProgressBar, QPushButton, QFrame, QScrollArea, QMenu,
)
from .tree_model import VariableInfo
from .quality import QualityReport


class CdfInspectorWidget(QWidget):
    dependency_clicked = Signal(str)  # variable name
    plot_new_panel = Signal(str)      # variable name
    plot_to_panel = Signal(str, str)  # variable name, panel name
    send_to_console = Signal(str)     # variable name

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Header
        self._header = QLabel("Select a variable")
        self._header.setStyleSheet("font-size: 14px; font-weight: bold;")
        self._description = QLabel("")
        layout.addWidget(self._header)
        layout.addWidget(self._description)

        # Plot buttons
        btn_layout = QHBoxLayout()
        self._btn_new_panel = QPushButton("New Panel")
        self._btn_new_panel.clicked.connect(self._on_new_panel)
        self._btn_add_panel = QPushButton("Add to Panel ▾")
        self._btn_add_panel.clicked.connect(self._on_add_to_panel)
        btn_layout.addWidget(self._btn_new_panel)
        btn_layout.addWidget(self._btn_add_panel)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Attributes grid (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._attrs_container = QWidget()
        self._attrs_grid = QGridLayout(self._attrs_container)
        scroll.setWidget(self._attrs_container)
        layout.addWidget(scroll, stretch=1)

        # Quality bar
        self._quality_frame = QFrame()
        q_layout = QVBoxLayout(self._quality_frame)
        self._quality_label = QLabel("Data Quality")
        self._quality_bar = QProgressBar()
        self._quality_bar.setRange(0, 100)
        self._quality_detail = QLabel("")
        q_layout.addWidget(self._quality_label)
        q_layout.addWidget(self._quality_bar)
        q_layout.addWidget(self._quality_detail)
        layout.addWidget(self._quality_frame)

        self._current_var = None
        self._panel_names: list[str] = []
        self._set_enabled(False)

    def _set_enabled(self, enabled: bool):
        self._btn_new_panel.setEnabled(enabled)
        self._btn_add_panel.setEnabled(enabled)
        self._quality_frame.setVisible(enabled)

    def update_variable(self, info: VariableInfo, quality: QualityReport | None = None):
        self._current_var = info.name
        self._header.setText(info.name)
        self._description.setText(info.catdesc)
        self._set_enabled(True)
        self._populate_attributes(info)
        if quality:
            self._update_quality(quality)

    def _populate_attributes(self, info: VariableInfo):
        while self._attrs_grid.count():
            item = self._attrs_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        row = 0
        fixed_attrs = {
            "Shape": str(info.shape),
            "Type": info.cdf_type,
            "Compression": info.compression,
        }
        for key, val in fixed_attrs.items():
            self._add_attr_row(row, key, val)
            row += 1

        for key, values in info.all_attributes.items():
            display_val = ", ".join(str(v) for v in values) if values else ""
            is_dep = key.startswith("DEPEND_") or key == "LABL_PTR_1"
            self._add_attr_row(row, key, display_val, clickable=is_dep)
            row += 1

    def _add_attr_row(self, row: int, key: str, value: str, clickable: bool = False):
        key_label = QLabel(f"{key}:")
        key_label.setStyleSheet("color: gray;")
        self._attrs_grid.addWidget(key_label, row, 0)

        if clickable and value:
            link = QPushButton(f"{value} →")
            link.setFlat(True)
            link.setStyleSheet("color: teal; text-align: left;")
            link.clicked.connect(lambda _, v=value: self.dependency_clicked.emit(v))
            self._attrs_grid.addWidget(link, row, 1)
        else:
            val_label = QLabel(value)
            self._attrs_grid.addWidget(val_label, row, 1)

    def _update_quality(self, report: QualityReport):
        self._quality_bar.setValue(int(report.valid_percentage))
        self._quality_detail.setText(
            f"Fill: {report.fill_percentage:.1f}%  "
            f"Out of range: {report.out_of_range_percentage:.1f}%  "
            f"Epoch gaps: {report.epoch_gaps}"
        )

    def _on_new_panel(self):
        if self._current_var:
            self.plot_new_panel.emit(self._current_var)

    def _on_add_to_panel(self):
        if not self._current_var:
            return
        menu = QMenu(self)
        if not self._panel_names:
            menu.addAction("No panels open").setEnabled(False)
        else:
            for name in self._panel_names:
                menu.addAction(name, lambda n=name: self.plot_to_panel.emit(self._current_var, n))
        menu.exec(self._btn_add_panel.mapToGlobal(self._btn_add_panel.rect().bottomLeft()))

    def set_panel_names(self, names: list[str]):
        self._panel_names = names

    def show_global_attributes(self, attrs: dict):
        self._header.setText("Global Attributes")
        self._description.setText("")
        self._set_enabled(False)

        while self._attrs_grid.count():
            item = self._attrs_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for row, (key, values) in enumerate(attrs.items()):
            display_val = ", ".join(str(v) for v in values)
            self._add_attr_row(row, key, display_val)
