from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pycdfpp

from .document import Document, attribute_lists

# ---------------------------------------------------------------------------
# Conditional Qt base class: works whether PySide6 is real or mocked.
# When running under the test stub (root conftest.py replaces PySide6 with
# MagicMock) the imported "QAbstractItemModel" is a MagicMock *instance*, not
# a real class.  Subclassing it would make Python use MagicMock as metaclass,
# swallowing every method we define.  We therefore fall back to `object` and
# provide a thin stand-in for QModelIndex so the rest of the module never has
# to branch on Qt availability.
# ---------------------------------------------------------------------------
try:
    from PySide6.QtCore import QAbstractItemModel as _QtAIM, QModelIndex, Qt
    _REAL_QT = isinstance(_QtAIM, type)
except Exception:
    _REAL_QT = False

if _REAL_QT:
    _Base = _QtAIM  # type: ignore[assignment]

    def _invalid_index() -> QModelIndex:
        return QModelIndex()

    def _make_index(model, row: int, column: int, node: "TreeNode") -> QModelIndex:
        return model.createIndex(row, column, node)

    def _node_from_qt_index(index) -> Optional["TreeNode"]:
        if index is None or not index.isValid():
            return None
        return index.internalPointer()
else:
    _Base = object  # type: ignore[assignment,misc]

    class _NodeIndex:  # type: ignore[no-redef]
        """Lightweight QModelIndex stand-in used when Qt is not available."""
        __slots__ = ("_row", "_column", "_node")

        def __init__(self, row: int, column: int, node: "TreeNode") -> None:
            self._row = row
            self._column = column
            self._node = node

        def isValid(self) -> bool:
            return True

        def row(self) -> int:
            return self._row

        def column(self) -> int:
            return self._column

        def internalPointer(self) -> "TreeNode":
            return self._node

    def _invalid_index():  # type: ignore[no-redef]
        return None

    def _make_index(model, row: int, column: int, node: "TreeNode"):  # type: ignore[no-redef]
        return _NodeIndex(row, column, node)

    def _node_from_qt_index(index) -> Optional["TreeNode"]:  # type: ignore[no-redef]
        if index is None:
            return None
        if hasattr(index, "isValid") and not index.isValid():
            return None
        return index.internalPointer()


# ---------------------------------------------------------------------------
# VAR_TYPE grouping map
# ---------------------------------------------------------------------------
VAR_TYPE_GROUPS: dict[str, str] = {
    "data": "Data",
    "support_data": "Support Data",
    "metadata": "Metadata",
}
UNCATEGORIZED = "Uncategorized"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class VariableInfo:
    name: str
    shape: tuple
    cdf_type: pycdfpp.DataType
    var_type: str
    units: str = ""
    depend_0: str = ""
    depend_1: str = ""
    display_type: str = ""
    fill_value: Optional[float] = None
    valid_min: Optional[float] = None
    valid_max: Optional[float] = None
    scale_type: str = "linear"
    lablaxis: str = ""
    labl_ptr_1: str = ""
    fieldnam: str = ""
    catdesc: str = ""
    compression: str = ""
    all_attributes: dict = field(default_factory=dict)


@dataclass
class TreeNode:
    name: str
    parent: Optional[TreeNode] = None
    children: list[TreeNode] = field(default_factory=list)
    variable_info: Optional[VariableInfo] = None
    row: int = 0


# ---------------------------------------------------------------------------
# Attribute helpers
# ---------------------------------------------------------------------------
def _get_attr(var, name: str, default: str = "") -> str:
    try:
        return str(var.attributes[name].value)
    except KeyError:
        return default


def _get_numeric_attr(var, name: str) -> Optional[float]:
    try:
        val = var.attributes[name].value
        while isinstance(val, (list, tuple)):
            val = val[0]
        return float(val)
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError):
        return None


def _build_variable_info(name: str, var) -> VariableInfo:
    return VariableInfo(
        name=name,
        shape=var.shape,
        cdf_type=var.type,
        var_type=_get_attr(var, "VAR_TYPE"),
        units=_get_attr(var, "UNITS"),
        depend_0=_get_attr(var, "DEPEND_0"),
        depend_1=_get_attr(var, "DEPEND_1"),
        display_type=_get_attr(var, "DISPLAY_TYPE"),
        fill_value=_get_numeric_attr(var, "FILLVAL"),
        valid_min=_get_numeric_attr(var, "VALIDMIN"),
        valid_max=_get_numeric_attr(var, "VALIDMAX"),
        scale_type=_get_attr(var, "SCALETYP", "linear"),
        lablaxis=_get_attr(var, "LABLAXIS"),
        labl_ptr_1=_get_attr(var, "LABL_PTR_1"),
        fieldnam=_get_attr(var, "FIELDNAM"),
        catdesc=_get_attr(var, "CATDESC"),
        compression=str(var.compression),
        all_attributes=attribute_lists(var),
    )


# ---------------------------------------------------------------------------
# Tree model
# ---------------------------------------------------------------------------
class CdfTreeModel(_Base):  # type: ignore[misc]
    def __init__(self, doc: Document, parent=None):
        if _REAL_QT:
            super().__init__(parent)
        self._root = TreeNode(name="root")
        self._variable_map: dict[str, VariableInfo] = {}
        self._build_tree(doc)

    def _build_tree(self, doc: Document) -> None:
        groups: dict[str, TreeNode] = {}

        for var_name, var in doc.items():
            info = _build_variable_info(var_name, var)
            self._variable_map[var_name] = info

            group_label = VAR_TYPE_GROUPS.get(info.var_type.lower(), UNCATEGORIZED)
            if group_label not in groups:
                group_node = TreeNode(
                    name=group_label,
                    parent=self._root,
                    row=len(self._root.children),
                )
                self._root.children.append(group_node)
                groups[group_label] = group_node

            group_node = groups[group_label]
            child = TreeNode(
                name=var_name,
                parent=group_node,
                variable_info=info,
                row=len(group_node.children),
            )
            group_node.children.append(child)

    # --- Public data-model API ---

    def variable_info(self, name: str) -> Optional[VariableInfo]:
        return self._variable_map.get(name)

    def variable_infos(self) -> dict[str, VariableInfo]:
        return dict(self._variable_map)

    # --- QAbstractItemModel interface ---

    def rowCount(self, parent=None):
        node = self._node_from_index(parent)
        return len(node.children)

    def columnCount(self, parent=None):
        return 1

    def data(self, index, role=None):
        if index is None:
            return None
        node = _node_from_qt_index(index)
        if node is None:
            return None
        if _REAL_QT:
            from PySide6.QtCore import Qt as _Qt
            if role == _Qt.DisplayRole:
                return node.name
            return None
        return node.name  # in test/stub mode, return name regardless of role

    def index(self, row: int, column: int, parent=None):
        parent_node = self._node_from_index(parent)
        if row < 0 or row >= len(parent_node.children):
            return _invalid_index()
        child = parent_node.children[row]
        return _make_index(self, row, column, child)

    def parent(self, index=None):
        if index is None:
            return _invalid_index()
        node = _node_from_qt_index(index)
        if node is None:
            return _invalid_index()
        parent_node = node.parent
        if parent_node is None or parent_node is self._root:
            return _invalid_index()
        return _make_index(self, parent_node.row, 0, parent_node)

    def _node_from_index(self, index) -> TreeNode:
        if index is None:
            return self._root
        node = _node_from_qt_index(index)
        return node if node is not None else self._root


# ---------------------------------------------------------------------------
# Item delegate — full implementation requires real Qt; a no-op stub is
# provided so the name is always importable (tests never instantiate it).
# ---------------------------------------------------------------------------
if _REAL_QT:
    from PySide6.QtWidgets import QStyledItemDelegate, QStyleOptionViewItem, QStyle
    from PySide6.QtGui import QPainter, QColor, QPen
    from PySide6.QtCore import QRect, QSize

    class CdfItemDelegate(QStyledItemDelegate):
        SPARKLINE_WIDTH = 60
        SPARKLINE_HEIGHT = 14
        BADGE_WIDTH = 36
        LABEL_WIDTH = 52
        GAP = 6

        def __init__(self, parent=None):
            super().__init__(parent)
            self._sparklines: dict[str, list[float]] = {}
            self._quality: dict[str, float] = {}
            self._prefix = ""

        def set_sparkline(self, var_name: str, samples: list[float]):
            self._sparklines[var_name] = samples

        def set_quality(self, var_name: str, valid_pct: float):
            self._quality[var_name] = valid_pct

        def set_prefix(self, prefix: str):
            """Drawn dimmed in front of every name, so the distinctive part stands out."""
            self._prefix = prefix

        def _right_width(self) -> int:
            return self.LABEL_WIDTH + self.SPARKLINE_WIDTH + self.BADGE_WIDTH + 4 * self.GAP

        def sizeHint(self, option, index):
            base = super().sizeHint(option, index)
            return QSize(base.width() + self._right_width(), max(base.height(), 22))

        def paint(self, painter, option, index):
            from .presentation import quality_badge, row_label
            model = index.model()
            node = (model.mapToSource(index) if hasattr(model, "mapToSource") else index).internalPointer()
            if node is None or node.variable_info is None:
                super().paint(painter, option, index)
                return

            painter.save()
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            if selected:
                painter.fillRect(option.rect, option.palette.highlight())
            text = (option.palette.highlightedText() if selected else option.palette.text()).color()
            muted = QColor(text)
            muted.setAlpha(120)

            name_rect = QRect(option.rect)
            name_rect.setWidth(option.rect.width() - self._right_width())
            self._draw_name(painter, name_rect, node.name, text, muted)

            x = option.rect.right() - self._right_width() + self.GAP
            mid = option.rect.top() + option.rect.height() // 2
            painter.setPen(muted)
            small = painter.font()
            small.setPointSizeF(max(small.pointSizeF() - 2, 7))
            painter.setFont(small)
            painter.drawText(QRect(x, option.rect.top(), self.LABEL_WIDTH, option.rect.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, row_label(node.variable_info))
            x += self.LABEL_WIDTH + self.GAP

            if node.name in self._sparklines:
                self._draw_sparkline(painter, QRect(x, mid - self.SPARKLINE_HEIGHT // 2, self.SPARKLINE_WIDTH,
                                                    self.SPARKLINE_HEIGHT), self._sparklines[node.name])
            x += self.SPARKLINE_WIDTH + self.GAP

            badge = quality_badge(self._quality[node.name]) if node.name in self._quality else None
            if badge is not None:
                self._draw_badge(painter, QRect(x, mid - 8, self.BADGE_WIDTH, 16), *badge)
            painter.restore()

        def _draw_name(self, painter, rect, name, color, muted):
            prefix = self._prefix if self._prefix and name.startswith(self._prefix) else ""
            painter.setPen(muted)
            painter.drawText(rect, Qt.AlignVCenter | Qt.AlignLeft, prefix)
            offset = painter.fontMetrics().horizontalAdvance(prefix)
            painter.setPen(color)
            painter.drawText(rect.adjusted(offset, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, name[len(prefix):])

        def _draw_sparkline(self, painter, rect, samples):
            if not samples:
                return
            mn, mx = min(samples), max(samples)
            rng = mx - mn if mx != mn else 1.0

            pen = QPen(QColor("#4ecca3"), 1.5)
            painter.setPen(pen)

            n = len(samples)
            points = [
                (
                    int(rect.left() + i * rect.width() / max(n - 1, 1)),
                    int(rect.bottom() - ((v - mn) / rng) * rect.height()),
                )
                for i, v in enumerate(samples)
            ]

            for i in range(len(points) - 1):
                painter.drawLine(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])

        _BADGE_COLORS = {"warning": ("#e7a33e", "#000"), "error": ("#e94560", "#fff")}

        def _draw_badge(self, painter, rect, text, level):
            fill, ink = self._BADGE_COLORS[level]
            painter.setBrush(QColor(fill))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor(ink))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, text)
else:
    class CdfItemDelegate:  # type: ignore[no-redef]
        """Stub used when Qt is not available (e.g. in tests)."""

        def set_sparkline(self, var_name: str, samples: list) -> None:
            pass

        def set_quality(self, var_name: str, valid_pct: float) -> None:
            pass

        def set_prefix(self, prefix: str) -> None:
            pass
