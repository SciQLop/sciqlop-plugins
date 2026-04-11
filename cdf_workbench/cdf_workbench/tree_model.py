from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pycdfpp

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
        return str(var.attributes[name][0])
    except (KeyError, IndexError, RuntimeError):
        return default


def _get_numeric_attr(var, name: str) -> Optional[float]:
    try:
        val = var.attributes[name][0]
        # pycdfpp may return a list for single-element attributes
        while isinstance(val, (list, tuple)):
            val = val[0]
        return float(val)
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError):
        return None


def _build_variable_info(name: str, var) -> VariableInfo:
    all_attrs: dict = {}
    for attr_name, attr in var.attributes.items():
        try:
            all_attrs[attr_name] = [attr[i] for i in range(len(attr))]
        except Exception:
            all_attrs[attr_name] = []

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
        compression=str(var.compression) if hasattr(var, "compression") else "",
        all_attributes=all_attrs,
    )


# ---------------------------------------------------------------------------
# Tree model
# ---------------------------------------------------------------------------
class CdfTreeModel(_Base):  # type: ignore[misc]
    def __init__(self, cdf: pycdfpp.CDF, parent=None):
        if _REAL_QT:
            super().__init__(parent)
        self._root = TreeNode(name="root")
        self._variable_map: dict[str, VariableInfo] = {}
        self._build_tree(cdf)

    def _build_tree(self, cdf: pycdfpp.CDF) -> None:
        groups: dict[str, TreeNode] = {}

        for var_name, var in cdf.items():
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

    _DISPLAY_TYPE_LABELS: dict[str, tuple[str, str]] = {
        "time_series": ("TS", "#5b9bd5"),
        "spectrogram": ("SP", "#c678dd"),
        "stack_plot": ("SK", "#e5c07b"),
        "no_plot": ("--", "#666666"),
    }

    _DIM_COLORS = ["#888888", "#56b6c2", "#c678dd", "#e5c07b"]

    def _dim_tag(shape: tuple) -> tuple[str, str]:
        ndim = len(shape)
        return f"{ndim}D", _DIM_COLORS[min(ndim, len(_DIM_COLORS) - 1)]

    class CdfItemDelegate(QStyledItemDelegate):
        SPARKLINE_WIDTH = 60
        SPARKLINE_HEIGHT = 14
        BADGE_WIDTH = 40
        TAG_WIDTH = 24
        DIM_TAG_WIDTH = 22

        def __init__(self, parent=None):
            super().__init__(parent)
            self._sparklines: dict[str, list[float]] = {}
            self._quality: dict[str, float] = {}

        def set_sparkline(self, var_name: str, samples: list[float]):
            self._sparklines[var_name] = samples

        def set_quality(self, var_name: str, valid_pct: float):
            self._quality[var_name] = valid_pct

        def sizeHint(self, option, index):
            base = super().sizeHint(option, index)
            extra = self.DIM_TAG_WIDTH + self.TAG_WIDTH + self.SPARKLINE_WIDTH + self.BADGE_WIDTH + 32
            return QSize(base.width() + extra, max(base.height(), 22))

        def paint(self, painter, option, index):
            model = index.model()
            if hasattr(model, "mapToSource"):
                source_index = model.mapToSource(index)
                node = source_index.internalPointer()
            else:
                node = index.internalPointer()

            if node is None or node.variable_info is None:
                super().paint(painter, option, index)
                return

            painter.save()

            is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
            if is_selected:
                painter.fillRect(option.rect, option.palette.highlight())
                painter.setPen(option.palette.highlightedText().color())
            else:
                painter.setPen(option.palette.text().color())

            right_margin = self.DIM_TAG_WIDTH + self.SPARKLINE_WIDTH + self.BADGE_WIDTH + self.TAG_WIDTH + 32
            name_rect = QRect(option.rect)
            name_rect.setWidth(option.rect.width() - right_margin)
            painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, node.name)

            var_name = node.name
            info = node.variable_info
            x_cursor = option.rect.right() - self.SPARKLINE_WIDTH - self.BADGE_WIDTH - self.TAG_WIDTH - self.DIM_TAG_WIDTH - 24

            # Dimension tag
            dim_label, dim_color = _dim_tag(info.shape)
            dim_rect = QRect(
                x_cursor,
                option.rect.top() + (option.rect.height() - 14) // 2,
                self.DIM_TAG_WIDTH,
                14,
            )
            self._draw_tag(painter, dim_rect, dim_label, dim_color)
            x_cursor += self.DIM_TAG_WIDTH + 4

            # Display type tag
            dt_key = info.display_type.lower().strip() if info else ""
            tag_label, tag_color = _DISPLAY_TYPE_LABELS.get(dt_key, ("", ""))
            if tag_label:
                tag_rect = QRect(
                    x_cursor,
                    option.rect.top() + (option.rect.height() - 14) // 2,
                    self.TAG_WIDTH,
                    14,
                )
                self._draw_tag(painter, tag_rect, tag_label, tag_color)

            if var_name in self._sparklines:
                spark_rect = QRect(
                    option.rect.right() - self.SPARKLINE_WIDTH - self.BADGE_WIDTH - 12,
                    option.rect.top() + (option.rect.height() - self.SPARKLINE_HEIGHT) // 2,
                    self.SPARKLINE_WIDTH,
                    self.SPARKLINE_HEIGHT,
                )
                self._draw_sparkline(painter, spark_rect, self._sparklines[var_name])

            if var_name in self._quality:
                badge_rect = QRect(
                    option.rect.right() - self.BADGE_WIDTH - 4,
                    option.rect.top() + (option.rect.height() - 16) // 2,
                    self.BADGE_WIDTH,
                    16,
                )
                self._draw_badge(painter, badge_rect, self._quality[var_name])

            painter.restore()

        def _draw_tag(self, painter, rect, label, color_hex):
            color = QColor(color_hex)
            color.setAlpha(40)
            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 3, 3)

            painter.setPen(QColor(color_hex))
            font = painter.font()
            font.setPointSize(7)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, label)

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

        def _draw_badge(self, painter, rect, valid_pct):
            if valid_pct > 80:
                color = QColor("#4ecca3")
                text_color = QColor("#000")
            elif valid_pct > 50:
                color = QColor("#e7c94c")
                text_color = QColor("#000")
            else:
                color = QColor("#e94560")
                text_color = QColor("#fff")

            painter.setBrush(color)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, 3, 3)

            painter.setPen(text_color)
            font = painter.font()
            font.setPointSize(8)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignCenter, f"{valid_pct:.0f}%")
else:
    class CdfItemDelegate:  # type: ignore[no-redef]
        """Stub used when Qt is not available (e.g. in tests)."""

        def set_sparkline(self, var_name: str, samples: list) -> None:
            pass

        def set_quality(self, var_name: str, valid_pct: float) -> None:
            pass
