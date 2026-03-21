from __future__ import annotations
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QProgressBar, QPushButton, QFrame, QScrollArea, QMenu,
    QTreeWidget, QTreeWidgetItem, QSizePolicy,
)
from .tree_model import VariableInfo
from .quality import QualityReport
from .lint import LintReport, LintIssue


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

        # Lint section — collapsible toggle + tree
        self._lint_toggle = QPushButton("ISTP Conformance")
        self._lint_toggle.setFlat(True)
        self._lint_toggle.setStyleSheet("font-weight: bold; text-align: left;")
        self._lint_toggle.setCheckable(True)
        self._lint_toggle.setChecked(False)
        self._lint_toggle.toggled.connect(self._on_lint_toggled)
        self._lint_toggle.setVisible(False)
        layout.addWidget(self._lint_toggle)

        self._lint_tree = QTreeWidget()
        self._lint_tree.setHeaderHidden(True)
        self._lint_tree.setRootIsDecorated(False)
        self._lint_tree.setVisible(False)
        self._lint_tree.setMaximumHeight(200)
        layout.addWidget(self._lint_tree)

        self._current_var = None
        self._panel_names: list[str] = []
        self._lint_report: LintReport | None = None
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
        self._update_lint_display()

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

    def set_lint_report(self, report: LintReport):
        self._lint_report = report
        self._update_lint_display()

    def _on_lint_toggled(self, checked: bool):
        self._lint_tree.setVisible(checked)
        # Update arrow without rebuilding tree
        current_text = self._lint_toggle.text()
        if current_text.startswith("\u25b6") or current_text.startswith("\u25bc"):
            arrow = "\u25bc" if checked else "\u25b6"
            self._lint_toggle.setText(arrow + current_text[1:])

    def _update_lint_display(self):
        if self._lint_report is None:
            self._lint_toggle.setVisible(False)
            self._lint_tree.setVisible(False)
            return

        if self._current_var:
            issues = self._lint_report.issues_for_variable(self._current_var)
            n_err = sum(1 for i in issues if i.severity == "ERROR")
            n_warn = sum(1 for i in issues if i.severity == "WARNING")
        else:
            issues = self._lint_report.file_level_issues()
            n_err = sum(1 for i in issues if i.severity == "ERROR")
            n_warn = sum(1 for i in issues if i.severity == "WARNING")

        if not issues:
            self._lint_toggle.setVisible(False)
            self._lint_tree.setVisible(False)
            return

        arrow = "\u25bc" if self._lint_toggle.isChecked() else "\u25b6"
        self._lint_toggle.setText(f"{arrow} ISTP Conformance ({n_err}E / {n_warn}W)")
        self._lint_toggle.setVisible(True)
        self._lint_tree.setVisible(self._lint_toggle.isChecked())

        self._lint_tree.clear()
        severity_colors = {"ERROR": "#e94560", "WARNING": "#e7c94c", "INFO": "#888888"}
        for issue in issues:
            item = QTreeWidgetItem([f"[{issue.severity}] {issue.message}"])
            color = severity_colors.get(issue.severity, "")
            if color:
                item.setForeground(0, QColor(color))
            self._lint_tree.addTopLevelItem(item)

    def show_global_attributes(self, attrs: dict):
        self._current_var = None
        self._header.setText("Global Attributes")
        self._description.setText("")
        self._set_enabled(False)
        self._update_lint_display()

        while self._attrs_grid.count():
            item = self._attrs_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for row, (key, values) in enumerate(attrs.items()):
            display_val = ", ".join(str(v) for v in values)
            self._add_attr_row(row, key, display_val)
