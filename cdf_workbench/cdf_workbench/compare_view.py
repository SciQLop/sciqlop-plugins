"""C1: a tab showing the differences between two documents."""
from __future__ import annotations
from html import escape

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from .diff import AttributeDiff, DocumentDiff, VariableDiff, word_diff

# Semi-transparent tints read in light and dark themes alike. Qt's rich text has no <del>/<ins>
# styling, so the marks become spans.
_DEL = '<span style="background-color: rgba(233, 69, 96, 0.35);">'
_INS = '<span style="background-color: rgba(76, 175, 80, 0.35);">'
_STATUS_COLOR = {"added": "#4caf50", "removed": "#e94560", "changed": "#e7a33e", "renamed": "#4a9fe7",
                 "same": "#888888"}
_SUMMARY_ORDER = ("changed", "renamed", "added", "removed", "same")
_SUMMARY_WORD = {"same": "identical"}


def _spans(marked: str) -> str:
    return (marked.replace("<del>", _DEL).replace("</del>", "</span>")
            .replace("<ins>", _INS).replace("</ins>", "</span>").replace("\n", "<br>"))


def _values(old: str, new: str, status: str) -> tuple[str, str]:
    if status == "added":
        return "", _INS + _spans(word_diff("", new)[1]) + "</span>"
    if status == "removed":
        return _DEL + _spans(word_diff(old, "")[0]) + "</span>", ""
    marked_old, marked_new = word_diff(old, new)
    return _spans(marked_old), _spans(marked_new)


def _rows(name: str, old: str, new: str, status: str, side_by_side: bool) -> str:
    """Side by side: one row, old | new. Inline: a − row for the old value, a + row for the new."""
    html_old, html_new = _values(old, new, status)
    label = f"<b>{escape(name)}</b>"
    if side_by_side:
        return f"<tr><td>{label}</td><td>{html_old}</td><td>{html_new}</td></tr>"
    if status == "same":
        return f"<tr><td>{label}</td><td>{html_old}</td></tr>"
    lines = ([("−", html_old)] if status != "added" else []) + ([("+", html_new)] if status != "removed" else [])
    return "".join(f"<tr><td>{label if k == 0 else ''}</td><td>{sign} {value}</td></tr>"
                   for k, (sign, value) in enumerate(lines))


def _table(rows: list[str], side_by_side: bool, titles: tuple[str, str]) -> str:
    if not rows:
        return ""
    header = (f"<tr><th></th><th align='left'>{escape(titles[0])}</th>"
              f"<th align='left'>{escape(titles[1])}</th></tr>"
              if side_by_side else "")
    return f"<table cellspacing='0' cellpadding='3' width='100%'>{header}{''.join(rows)}</table>"


def _attribute_rows(attrs: tuple[AttributeDiff, ...], hide_same: bool, side_by_side: bool) -> list[str]:
    return [_rows(a.name, a.old, a.new, a.status, side_by_side) for a in attrs
            if not (hide_same and a.status == "same")]


def _badge(status: str) -> str:
    return f"<span style='color: {_STATUS_COLOR[status]};'>{status}</span>"


def _variable(var: VariableDiff, hide_same: bool, side_by_side: bool, titles: tuple[str, str]) -> str:
    title = escape(f"{var.old_name} → {var.name}" if var.old_name else var.name)
    rows = [_rows(p, old, new, "changed", side_by_side) for p, old, new in var.properties]
    rows += _attribute_rows(var.attributes, hide_same and var.status != "added" and var.status != "removed",
                            side_by_side)
    return f"<h3>{title} {_badge(var.status)}</h3>{_table(rows, side_by_side, titles)}"


def render_html(diff: DocumentDiff, hide_same: bool, side_by_side: bool,
                titles: tuple[str, str] = ("A", "B")) -> str:
    globals_rows = _attribute_rows(diff.attributes, hide_same, side_by_side)
    variables = [v for v in diff.variables if not (hide_same and v.status == "same")]
    parts = []
    if globals_rows:
        parts.append(f"<h2>Global attributes</h2>{_table(globals_rows, side_by_side, titles)}")
    if variables:
        parts.append("<h2>Variables</h2>" + "".join(_variable(v, hide_same, side_by_side, titles)
                                                    for v in variables))
    return "".join(parts) or "<p>No differences.</p>"


def summary_text(diff: DocumentDiff) -> str:
    counts = diff.summary()
    changed_globals = sum(1 for a in diff.attributes if a.status != "same")
    parts = [f"{counts[s]} {_SUMMARY_WORD.get(s, s)}" for s in _SUMMARY_ORDER if counts.get(s)]
    return f"Variables: {', '.join(parts) or 'none'}. Global attributes changed: {changed_globals}."


class CompareView(QWidget):
    """Read-only. The documents are immutable, so this stays a consistent snapshot."""

    def __init__(self, diff: DocumentDiff, titles: tuple[str, str], parent=None):
        super().__init__(parent)
        self._diff, self._titles = diff, titles
        self._summary = QLabel(summary_text(diff))
        self._hide_same = QCheckBox("Hide identical")
        self._hide_same.setChecked(True)
        self._side_by_side = QCheckBox("Side by side")
        for box in (self._hide_same, self._side_by_side):
            box.toggled.connect(self._render)
        self._browser = QTextBrowser()
        bar = QHBoxLayout()
        bar.addWidget(QLabel(f"<b>{escape(titles[0])}</b> ↔ <b>{escape(titles[1])}</b>"))
        bar.addWidget(self._summary, 1)
        bar.addWidget(self._hide_same)
        bar.addWidget(self._side_by_side)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self._browser)
        self._render()

    def _render(self):
        self._html = render_html(self._diff, self._hide_same.isChecked(), self._side_by_side.isChecked(),
                                 self._titles)
        self._browser.setHtml(self._html)

    def html(self) -> str:
        return self._html
