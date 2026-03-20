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
    cdf_type: str
    var_type: str
    units: str = ""
    depend_0: str = ""
    display_type: str = ""
    fill_value: Optional[float] = None
    valid_min: Optional[float] = None
    valid_max: Optional[float] = None
    scale_type: str = "linear"
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
        return float(var.attributes[name][0])
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
        cdf_type=str(var.type),
        var_type=_get_attr(var, "VAR_TYPE"),
        units=_get_attr(var, "UNITS"),
        depend_0=_get_attr(var, "DEPEND_0"),
        display_type=_get_attr(var, "DISPLAY_TYPE"),
        fill_value=_get_numeric_attr(var, "FILLVAL"),
        valid_min=_get_numeric_attr(var, "VALIDMIN"),
        valid_max=_get_numeric_attr(var, "VALIDMAX"),
        scale_type=_get_attr(var, "SCALETYP", "linear"),
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
