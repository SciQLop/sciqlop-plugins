"""C1: a tab showing the differences between two documents."""
from __future__ import annotations
from functools import reduce
from html import escape
from typing import Callable, Optional
from urllib.parse import parse_qs, urlencode

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget

from .diff import AttributeDiff, DocumentDiff, VariableDiff, diff_documents, word_diff
from .document import Document, DocumentSession
from .edits import copy_attribute, copy_variable

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


def _href(kind: str, **params: str) -> str:
    return escape(f"{kind}:{urlencode(params)}", quote=True)


def _copy_link(href: Optional[str], label: str = "← copy") -> str:
    return f' <a href="{href}">{label}</a>' if href else ""


def _rows(name: str, old: str, new: str, status: str, side_by_side: bool, copy_href: Optional[str] = None) -> str:
    """Side by side: one row, old | new. Inline: a − row for the old value, a + row for the new."""
    html_old, html_new = _values(old, new, status)
    html_new += _copy_link(copy_href)
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


def _copyable(attr: AttributeDiff) -> bool:
    """The reference (B) has a value the target (A) lacks or differs from."""
    return attr.status in ("added", "changed")


def _attribute_rows(attrs: tuple[AttributeDiff, ...], hide_same: bool, side_by_side: bool,
                    href: Callable[[AttributeDiff], Optional[str]]) -> list[str]:
    return [_rows(a.name, a.old, a.new, a.status, side_by_side, href(a) if _copyable(a) else None)
            for a in attrs if not (hide_same and a.status == "same")]


def _badge(status: str) -> str:
    return f"<span style='color: {_STATUS_COLOR[status]};'>{status}</span>"


def _variable(var: VariableDiff, hide_same: bool, side_by_side: bool, titles: tuple[str, str],
              copyable: bool) -> str:
    """A renamed variable copies from its new name (reference) to its old one (target)."""
    target, source = var.old_name or var.name, var.name
    title = escape(f"{var.old_name} → {var.name}" if var.old_name else var.name)
    can_copy_attributes = copyable and var.status in ("changed", "renamed")
    href = (lambda a: _href("copy-attr", t=target, s=source, a=a.name)) if can_copy_attributes else (lambda a: None)
    header_link = ""
    if copyable and var.status == "added":
        header_link = _copy_link(_href("copy-var", n=var.name), "← copy variable")
    elif can_copy_attributes and any(_copyable(a) for a in var.attributes):
        header_link = _copy_link(_href("copy-all", t=target, s=source), "← copy all")
    rows = [_rows(p, old, new, "changed", side_by_side) for p, old, new in var.properties]
    rows += _attribute_rows(var.attributes, hide_same and var.status not in ("added", "removed"),
                            side_by_side, href)
    return f"<h3>{title} {_badge(var.status)}{header_link}</h3>{_table(rows, side_by_side, titles)}"


def render_html(diff: DocumentDiff, hide_same: bool, side_by_side: bool,
                titles: tuple[str, str] = ("A", "B"), copyable: bool = False) -> str:
    """`copyable` adds "← copy" links taking a value from B (the reference) into A."""
    global_href = (lambda a: _href("copy-attr", t="", s="", a=a.name)) if copyable else (lambda a: None)
    globals_rows = _attribute_rows(diff.attributes, hide_same, side_by_side, global_href)
    variables = [v for v in diff.variables if not (hide_same and v.status == "same")]
    parts = []
    if globals_rows:
        parts.append(f"<h2>Global attributes</h2>{_table(globals_rows, side_by_side, titles)}")
    if variables:
        parts.append("<h2>Variables</h2>" + "".join(_variable(v, hide_same, side_by_side, titles, copyable)
                                                    for v in variables))
    return "".join(parts) or "<p>No differences.</p>"


def summary_text(diff: DocumentDiff) -> str:
    counts = diff.summary()
    changed_globals = sum(1 for a in diff.attributes if a.status != "same")
    parts = [f"{counts[s]} {_SUMMARY_WORD.get(s, s)}" for s in _SUMMARY_ORDER if counts.get(s)]
    return f"Variables: {', '.join(parts) or 'none'}. Global attributes changed: {changed_globals}."


def _copy_edit(link: str, reference: Document, diff: DocumentDiff) -> Callable[[Document], Document]:
    kind, _, query = link.partition(":")
    p = {k: v[0] for k, v in parse_qs(query, keep_blank_values=True).items()}
    if kind == "copy-var":
        return lambda d: copy_variable(d, reference, p["n"])
    if kind == "copy-attr":
        return lambda d: copy_attribute(d, reference, p["a"], p["t"], p["s"])
    var = next(v for v in diff.variables if (v.old_name or v.name) == p["t"])
    names = [a.name for a in var.attributes if _copyable(a)]
    return lambda d: reduce(lambda acc, name: copy_attribute(acc, reference, name, p["t"], p["s"]), names, d)


class CompareView(QWidget):
    """Compares the target tab's current document (A) with a reference (B), and copies from B
    into A on request. Follows A's edits and undo; B is an immutable snapshot."""

    def __init__(self, target: DocumentSession, reference: Document, titles: tuple[str, str], parent=None):
        super().__init__(parent)
        self._target, self._reference, self._titles = target, reference, titles
        self._summary = QLabel()
        self._message = QLabel()
        self._message.setStyleSheet("color: #e94560;")
        self._hide_same = QCheckBox("Hide identical")
        self._hide_same.setChecked(True)
        self._side_by_side = QCheckBox("Side by side")
        for box in (self._hide_same, self._side_by_side):
            box.toggled.connect(self._render)
        self._browser = QTextBrowser()
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(lambda url: self.copy(url.toString()))
        bar = QHBoxLayout()
        bar.addWidget(QLabel(f"<b>{escape(titles[0])}</b> ↔ <b>{escape(titles[1])}</b>"))
        bar.addWidget(self._summary, 1)
        bar.addWidget(self._hide_same)
        bar.addWidget(self._side_by_side)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self._message)
        layout.addWidget(self._browser)
        target.changed.connect(self._render)
        self._render()

    def _render(self):
        self._diff = diff_documents(self._target.document, self._reference)
        self._summary.setText(summary_text(self._diff))
        self._html = render_html(self._diff, self._hide_same.isChecked(), self._side_by_side.isChecked(),
                                 self._titles, copyable=True)
        scroll = self._browser.verticalScrollBar().value()
        self._browser.setHtml(self._html)
        self._browser.verticalScrollBar().setValue(scroll)

    def copy(self, link: str):
        """A copy is an ordinary edit of the target: it undoes, and the target tab gets its •."""
        try:
            self._target.apply(_copy_edit(link, self._reference, self._diff))
            self._message.clear()
        except (ValueError, KeyError, StopIteration) as e:
            self._message.setText(f"Can't copy: {e}")

    def html(self) -> str:
        return self._html
