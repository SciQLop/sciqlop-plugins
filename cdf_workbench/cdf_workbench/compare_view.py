"""C1: a tab comparing the target tab's document (A) with a reference (B), and copying from B into A."""
from __future__ import annotations
from html import escape
from typing import Optional

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QTextDocument, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QSplitter,
    QStyle, QStyledItemDelegate, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .compare_rows import Row, build_rows, copy_edit, short_titles
from .diff import DocumentDiff, diff_documents, similar_text, word_diff
from .document import Document, DocumentSession

NAME, OLD, GUTTER, NEW = range(4)
_ROW = Qt.UserRole

# Semi-transparent tints read in light and dark themes alike.
_STATUS_COLOR = {"added": "#4caf50", "removed": "#e94560", "changed": "#e7a33e", "renamed": "#4a9fe7",
                 "same": "#888888"}
_WORD_DEL = "rgba(233, 69, 96, 0.45)"
_WORD_INS = "rgba(76, 175, 80, 0.45)"
_CELL_TINT = {"removed": QColor(233, 69, 96, 40), "added": QColor(76, 175, 80, 40)}
_SUMMARY_ORDER = ("changed", "renamed", "added", "removed", "same")
_SUMMARY_WORD = {"same": "identical"}


def summary_text(diff: DocumentDiff) -> str:
    counts = diff.summary()
    changed_globals = sum(1 for a in diff.attributes if a.status != "same")
    parts = [f"{counts[s]} {_SUMMARY_WORD.get(s, s)}" for s in _SUMMARY_ORDER if counts.get(s)]
    return f"Variables: {', '.join(parts) or 'none'} · global attributes changed: {changed_globals}"


def _marked_html(marked: str) -> str:
    """word_diff output (<del>/<ins>, already escaped) as spans Qt's rich text can colour."""
    return (marked.replace("<del>", f'<span style="background-color: {_WORD_DEL};">')
            .replace("<ins>", f'<span style="background-color: {_WORD_INS};">')
            .replace("</del>", "</span>").replace("</ins>", "</span>"))


def _values_html(row: Row) -> tuple[str, str]:
    """Word marks only where the values share words: the row's status bar already says it changed."""
    if row.status in ("added", "removed") or not similar_text(row.old, row.new):
        return escape(row.old), escape(row.new)
    old, new = word_diff(row.old, row.new)
    return _marked_html(old), _marked_html(new)


def gutter_action(row: Row) -> Optional[str]:
    """The arrow between A and B: copy B's value, or, for a pure rename, take B's name."""
    return row.copy or row.rename


def _is_group(row: Row) -> bool:
    return "/" not in row.key


def detail_html(row: Row, titles: tuple[str, str]) -> str:
    """The selected row in full, values wrapped, for the pane under the tree."""
    old, new = (v.replace("\n", "<br>") for v in _values_html(row))
    status = f"<span style='color: {_STATUS_COLOR[row.status]};'>{row.status}</span>"
    return (f"<p><b>{escape(row.name)}</b> &nbsp; {status}</p>"
            f"<table width='100%' cellspacing='0' cellpadding='4'><tr>"
            f"<th align='left' width='50%'>{escape(titles[0])}</th><th align='left'>{escape(titles[1])}</th></tr>"
            f"<tr><td valign='top'>{old}</td><td valign='top'>{new}</td></tr></table>")


class _DiffDelegate(QStyledItemDelegate):
    """Status bar and pill on the names, one clipped line of highlighted text per value, a copy
    arrow in the gutter."""

    def sizeHint(self, option, index):
        hint = super().sizeHint(option, index)
        return QSize(hint.width(), hint.height() + 8)

    def paint(self, painter, option, index):
        row: Optional[Row] = index.data(_ROW)
        if row is None:
            return super().paint(painter, option, index)
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
        text = (option.palette.highlightedText() if selected else option.palette.text()).color()
        paint = {NAME: self._paint_name, OLD: self._paint_value, NEW: self._paint_value, GUTTER: self._paint_gutter}
        paint[index.column()](painter, option.rect, row, index.column(), text)
        painter.restore()

    def _paint_name(self, painter, rect, row, _column, text):
        if row.status != "same":
            painter.fillRect(QRect(rect.left(), rect.top() + 3, 3, rect.height() - 6), QColor(_STATUS_COLOR[row.status]))
        font = painter.font()
        font.setBold(_is_group(row))
        painter.setFont(font)
        painter.setPen(text)
        area = rect.adjusted(10, 0, -4, 0)
        painter.drawText(area, Qt.AlignVCenter | Qt.AlignLeft, row.name)
        x = area.left() + painter.fontMetrics().horizontalAdvance(row.name) + 10
        if _is_group(row) and row.key != "globals" and row.status != "same":
            x = self._paint_pill(painter, x, rect, row.status) + 8
        if row.note:
            font.setBold(False)
            painter.setFont(font)
            muted = QColor(text)
            muted.setAlpha(130)
            painter.setPen(muted)
            painter.drawText(QRect(x, rect.top(), max(rect.right() - x, 0), rect.height()),
                             Qt.AlignVCenter | Qt.AlignLeft, row.note)

    def _paint_pill(self, painter, x, rect, status) -> int:
        font = painter.font()
        font.setBold(False)
        font.setPointSizeF(max(font.pointSizeF() - 1.5, 7))
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(status) + 12
        pill = QRect(x, rect.top() + (rect.height() - 16) // 2, width, 16)
        fill = QColor(_STATUS_COLOR[status])
        fill.setAlpha(45)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(pill, 8, 8)
        painter.setPen(QColor(_STATUS_COLOR[status]))
        painter.drawText(pill, Qt.AlignCenter, status)
        return pill.right()

    def _paint_value(self, painter, rect, row, column, text):
        value = row.old if column == OLD else row.new
        if not value:
            return
        tint = _CELL_TINT.get(row.status)
        if tint is not None:
            painter.fillRect(rect.adjusted(0, 2, 0, -2), tint)
        old, new = _values_html(row)
        doc = QTextDocument()
        doc.setDefaultFont(painter.font())
        doc.setDefaultTextOption(QTextOption(Qt.AlignLeft))
        doc.setDocumentMargin(0)
        doc.setHtml(f"<div style='color: {text.name()}; white-space: pre;'>"
                    f"{(old if column == OLD else new).replace(chr(10), ' ⏎ ')}</div>")
        painter.setClipRect(rect.adjusted(6, 0, -4, 0))
        painter.translate(rect.left() + 6, rect.top() + (rect.height() - doc.size().height()) / 2)
        doc.drawContents(painter)

    def _paint_gutter(self, painter, rect, row, _column, text):
        if gutter_action(row) is None:
            return
        muted = QColor(text)
        muted.setAlpha(150)
        painter.setPen(muted)
        painter.drawText(rect, Qt.AlignCenter, "←")


class CompareView(QWidget):
    """Follows A's edits and undo; B is an immutable snapshot."""

    def __init__(self, target: DocumentSession, reference: Document, titles: tuple[str, str], parent=None):
        super().__init__(parent)
        self._target, self._reference = target, reference
        self._full_titles = titles
        self._titles = short_titles(*titles)
        self._expanded: dict[str, bool] = {}
        self._rows: list[Row] = []

        self._summary = QLabel()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter attributes and variables…")
        self._filter.setClearButtonEnabled(True)
        self._filter.setMinimumWidth(260)
        self._filter.textChanged.connect(self._render)
        self._hide_same = QCheckBox("Hide identical")
        self._hide_same.setChecked(True)
        self._hide_same.toggled.connect(self._render)
        self._message = QLabel()
        self._message.setStyleSheet("color: #e94560;")
        self._message.hide()

        self._tree = self._build_tree()
        self._detail = QTextBrowser()
        self._detail.setPlaceholderText("Select a row to see both values in full.")
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self._tree)
        splitter.addWidget(self._detail)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        bar = QHBoxLayout()
        bar.addWidget(self._summary, 1)
        bar.addWidget(self._filter)
        bar.addWidget(self._hide_same)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self._message)
        layout.addWidget(splitter)
        target.changed.connect(self._render)
        self._render()

    def _build_tree(self) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setColumnCount(4)
        tree.setHeaderLabels(["", self._titles[0], "", self._titles[1]])
        for column, title in ((OLD, self._full_titles[0]), (NEW, self._full_titles[1])):
            tree.headerItem().setToolTip(column, title)
        tree.setItemDelegate(_DiffDelegate(tree))
        tree.setUniformRowHeights(True)
        tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        tree.setContextMenuPolicy(Qt.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._show_menu)
        tree.itemClicked.connect(self._on_clicked)
        tree.itemExpanded.connect(lambda item: self._remember(item, True))
        tree.itemCollapsed.connect(lambda item: self._remember(item, False))
        tree.currentItemChanged.connect(self._show_detail)
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(NAME, QHeaderView.Interactive)
        header.setSectionResizeMode(OLD, QHeaderView.Stretch)
        header.setSectionResizeMode(GUTTER, QHeaderView.Fixed)
        header.setSectionResizeMode(NEW, QHeaderView.Stretch)
        header.resizeSection(NAME, 280)
        header.resizeSection(GUTTER, 28)
        return tree

    @property
    def target(self) -> DocumentSession:
        return self._target

    def rows(self) -> list[Row]:
        return self._rows

    def _render(self, *_):
        current = self._tree.currentItem()
        current_key = current.data(NAME, _ROW).key if current is not None else None
        self._diff = diff_documents(self._target.document, self._reference)
        self._summary.setText(summary_text(self._diff))
        self._rows = build_rows(self._diff, self._hide_same.isChecked(), self._filter.text())
        scroll = self._tree.verticalScrollBar().value()
        self._tree.clear()
        for row in self._rows:
            self._add_item(self._tree.invisibleRootItem(), row, current_key)
        self._tree.verticalScrollBar().setValue(scroll)
        if self._tree.currentItem() is None:
            self._detail.clear()

    def _add_item(self, parent: QTreeWidgetItem, row: Row, current_key: Optional[str]):
        item = QTreeWidgetItem(parent)
        for column in (NAME, OLD, GUTTER, NEW):
            item.setData(column, _ROW, row)
        item.setToolTip(OLD, row.old[:2000])
        item.setToolTip(NEW, row.new[:2000])
        if row.copy is not None:
            item.setToolTip(GUTTER, f"Copy from {self._full_titles[1]}")
        elif row.rename is not None:
            item.setToolTip(GUTTER, f"Rename to {row.name.split(' → ')[-1]}")
        for child in row.children:
            self._add_item(item, child, current_key)
        item.setExpanded(self._expanded.get(row.key, row.expanded))
        if row.key == current_key:
            self._tree.setCurrentItem(item)

    def _remember(self, item: QTreeWidgetItem, expanded: bool):
        self._expanded[item.data(NAME, _ROW).key] = expanded

    def _show_detail(self, item: Optional[QTreeWidgetItem], _previous=None):
        row = item.data(NAME, _ROW) if item is not None else None
        if row is None or not (row.old or row.new):
            self._detail.clear()
            return
        self._detail.setHtml(detail_html(row, self._full_titles))

    def _on_clicked(self, item: QTreeWidgetItem, column: int):
        action = gutter_action(item.data(NAME, _ROW))
        if column == GUTTER and action is not None:
            self.copy(action)

    def _show_menu(self, pos):
        selected = [item.data(NAME, _ROW) for item in self._tree.selectedItems()]
        copies = [row.copy for row in selected if row.copy is not None]
        renames = [row for row in selected if row.rename is not None]
        if not copies and not renames:
            return
        menu = QMenu(self)
        if copies:
            label = f"Copy {len(copies)} from {self._titles[1]}" if len(copies) > 1 else f"Copy from {self._titles[1]}"
            menu.addAction(label, lambda: self.copy(*copies))
        for row in renames:
            menu.addAction(f"Rename to {row.name.split(' → ')[-1]}", lambda a=row.rename: self.copy(a))
        menu.exec(self._tree.viewport().mapToGlobal(pos))

    def copy(self, *actions: str):
        """One undoable edit of the target, whatever the number of actions."""
        edits = [copy_edit(action, self._reference, self._diff) for action in actions]

        def apply_all(doc: Document) -> Document:
            for edit in edits:
                doc = edit(doc)
            return doc
        try:
            self._target.apply(apply_all)
            self._message.hide()
        except (ValueError, KeyError, StopIteration) as e:
            self._message.setText(f"Can't copy: {e}")
            self._message.show()
