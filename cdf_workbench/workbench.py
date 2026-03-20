from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QLabel


class CdfWorkbenchPanel(QWidget):
    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self._main_window = main_window
        self.setWindowTitle("CDF Workbench")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setTabsClosable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        layout.addWidget(self._tabs)

        # Placeholder for empty state
        self._empty_label = QLabel("Drop a CDF file here or use File → Open")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._tabs.addTab(self._empty_label, "+")

    def _close_tab(self, index: int):
        widget = self._tabs.widget(index)
        if widget is not self._empty_label:
            self._tabs.removeTab(index)
            widget.deleteLater()
