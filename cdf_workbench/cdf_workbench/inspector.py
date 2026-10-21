from __future__ import annotations
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QPushButton, QScrollArea, QMenu, QToolButton,
    QTreeWidget, QTreeWidgetItem, QSizePolicy,
)
from .edits import format_value
from .tree_model import VariableInfo
from .quality import QualityReport
from .lint import LintReport, LintIssue
from .presentation import quality_summary


# Room for a menu tool button's padding and arrow beside its text.
_MENU_BUTTON_EXTRA_WIDTH = 48


class _AttributeLabel(QLabel):
    """An attribute's name or value: double-click to edit, right-click to edit or delete."""
    edit_requested = Signal()
    delete_requested = Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setToolTip("Double-click to edit, right-click for more")
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    def mouseDoubleClickEvent(self, event):
        self.edit_requested.emit()

    def _show_menu(self, pos):
        menu = QMenu(self)
        menu.addAction("Edit…", self.edit_requested.emit)
        menu.addAction("Delete", self.delete_requested.emit)
        menu.exec(self.mapToGlobal(pos))


class CdfInspectorWidget(QWidget):
    dependency_clicked = Signal(str)  # variable name
    plot_new_panel = Signal(str)      # variable name
    plot_to_panel = Signal(str, str)  # variable name, panel name
    send_to_console = Signal(str)     # variable name
    # variable name ("" for global attributes), attribute name
    edit_attribute = Signal(str, str)
    delete_attribute = Signal(str, str)
    add_attribute = Signal(str)       # variable name ("" for global attributes)
    export_data = Signal(str)         # variable name

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

        # One primary action: plot in a new panel; the menu has the other destinations.
        btn_layout = QHBoxLayout()
        self._plot = QToolButton()
        self._plot.setText("Plot")
        self._plot.setPopupMode(QToolButton.MenuButtonPopup)
        self._plot.setToolButtonStyle(Qt.ToolButtonTextOnly)
        # Stylesheets shrink a menu tool button to its arrow: leave room for the text.
        self._plot.setMinimumWidth(self._plot.fontMetrics().horizontalAdvance("Plot") + _MENU_BUTTON_EXTRA_WIDTH)
        self._plot.clicked.connect(self._on_new_panel)
        self._plot.setMenu(QMenu(self._plot))
        self._plot.menu().aboutToShow.connect(self._fill_plot_menu)
        btn_layout.addWidget(self._plot)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # Attributes grid (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._attrs_container = QWidget()
        self._attrs_grid = QGridLayout(self._attrs_container)
        scroll.setWidget(self._attrs_container)
        layout.addWidget(scroll, stretch=1)
        add_row = QHBoxLayout()
        self._btn_add_attribute = QPushButton("Add attribute…")
        self._btn_add_attribute.clicked.connect(lambda: self.add_attribute.emit(self._current_var or ""))
        add_row.addWidget(self._btn_add_attribute)
        add_row.addStretch()
        layout.addLayout(add_row)

        # Quality: one line, coloured only when something is missing
        self._quality_line = QLabel()
        self._quality_line.setToolTip("Values that are FILLVAL, outside VALIDMIN/VALIDMAX, and gaps in time")
        layout.addWidget(self._quality_line)

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
        self._plot.setEnabled(enabled)
        self._quality_line.setVisible(enabled and bool(self._quality_line.text()))

    @property
    def current_variable(self) -> str | None:
        return self._current_var

    def update_variable(self, info: VariableInfo, quality: QualityReport | None = None):
        self._current_var = info.name
        self._quality_line.clear()
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
            "Type": str(info.cdf_type),
            "Compression": info.compression,
        }
        for key, val in fixed_attrs.items():
            self._add_attr_row(row, key, val)
            row += 1

        for key, values in info.all_attributes.items():
            display_val = ", ".join(format_value(v) for v in values)
            is_dep = key.startswith("DEPEND_") or key == "LABL_PTR_1"
            self._add_attr_row(row, key, display_val, clickable=is_dep, editable=True)
            row += 1

    def _editable(self, label: _AttributeLabel, key: str) -> _AttributeLabel:
        owner = self._current_var or ""
        label.edit_requested.connect(lambda: self.edit_attribute.emit(owner, key))
        label.delete_requested.connect(lambda: self.delete_attribute.emit(owner, key))
        return label

    def _add_attr_row(self, row: int, key: str, value: str, clickable: bool = False, editable: bool = False):
        key_label = self._editable(_AttributeLabel(f"{key}:"), key) if editable else QLabel(f"{key}:")
        key_label.setStyleSheet("color: gray;")
        self._attrs_grid.addWidget(key_label, row, 0)

        if clickable and value:
            link = QPushButton(f"{value} →")
            link.setFlat(True)
            link.setStyleSheet("color: teal; text-align: left;")
            link.clicked.connect(lambda _, v=value: self.dependency_clicked.emit(v))
            self._attrs_grid.addWidget(link, row, 1)
        else:
            val_label = self._editable(_AttributeLabel(value), key) if editable else QLabel(value)
            self._attrs_grid.addWidget(val_label, row, 1)

    _QUALITY_COLORS = {"ok": "#3aa76d", "warning": "#d18a1f", "error": "#e94560"}

    def _update_quality(self, report: QualityReport):
        text, level = quality_summary(report)
        self._quality_line.setText(text)
        self._quality_line.setProperty("level", level)
        self._quality_line.setStyleSheet(f"color: {self._QUALITY_COLORS[level]};")
        self._quality_line.setVisible(True)

    def _on_new_panel(self):
        if self._current_var:
            self.plot_new_panel.emit(self._current_var)

    def _plot_menu(self) -> QMenu:
        menu = self._plot.menu()
        menu.clear()
        name = self._current_var
        menu.addAction("In a new panel", self._on_new_panel)
        for panel in self._panel_names:
            menu.addAction(f"In {panel}", lambda p=panel: self.plot_to_panel.emit(name, p))
        menu.addSeparator()
        menu.addAction("Send to console", lambda: self.send_to_console.emit(name))
        menu.addAction("Export data…", lambda: self.export_data.emit(name))
        return menu

    def _fill_plot_menu(self):
        self._plot_menu()

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
            display_val = ", ".join(format_value(v) for v in values)
            self._add_attr_row(row, key, display_val, editable=True)
