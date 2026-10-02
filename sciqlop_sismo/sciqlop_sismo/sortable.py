"""Header-click sorting for the dock's tables: cells show formatted text
("100.00 Hz") but sort on a typed key (100.0), so numbers sort as numbers."""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QTableWidgetItem

# UserRole itself carries each row's payload on column 0.
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class SortableTableItem(QTableWidgetItem):
    def __init__(self, text: str, key=None):
        super().__init__(text)
        self.setData(SORT_ROLE, text if key is None else key)

    def __lt__(self, other):
        return self.data(SORT_ROLE) < other.data(SORT_ROLE)


def sortable_tree_item(text: str, key=None) -> QStandardItem:
    """For a QStandardItemModel whose sort role is SORT_ROLE."""
    item = QStandardItem(text)
    item.setEditable(False)
    item.setData(text if key is None else key, SORT_ROLE)
    return item


@contextmanager
def sorting_paused(view):
    """Rows reorder on every insert while sorting is on, scattering a row's
    cells; fill with it off, then re-apply the user's chosen column."""
    view.setSortingEnabled(False)
    try:
        yield
    finally:
        view.setSortingEnabled(True)
