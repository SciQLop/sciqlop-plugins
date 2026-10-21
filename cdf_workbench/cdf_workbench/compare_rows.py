"""C1: a comparison as tree rows (groups and their differing items), and the copy actions."""
from __future__ import annotations
from dataclasses import dataclass, replace
from functools import reduce
from os.path import commonprefix
from typing import Callable, Optional
from urllib.parse import parse_qs, urlencode

from .diff import AttributeDiff, DocumentDiff, Status, VariableDiff
from .document import Document
from .edits import copy_attribute, copy_variable, rename_variable


@dataclass(frozen=True)
class Row:
    key: str
    name: str
    status: Status
    old: str = ""
    new: str = ""
    note: str = ""                 # e.g. "2 changed", "4 attributes"
    copy: Optional[str] = None     # action taking B's value into A
    rename: Optional[str] = None   # action giving A's variable B's name
    expanded: bool = False
    children: tuple["Row", ...] = ()


def _action(kind: str, **params: str) -> str:
    return f"{kind}:{urlencode(params)}"


def _copyable(attr: AttributeDiff) -> bool:
    """The reference (B) has a value the target (A) lacks or differs from."""
    return attr.status in ("added", "changed")


def _attribute_row(key: str, attr: AttributeDiff, copy: Optional[str]) -> Row:
    return Row(f"{key}/{attr.name}", attr.name, attr.status, attr.old, attr.new,
               copy=copy if _copyable(attr) else None)


def _global_group(diff: DocumentDiff, hide_same: bool) -> Optional[Row]:
    shown = [a for a in diff.attributes if not (hide_same and a.status == "same")]
    if not shown:
        return None
    changed = sum(1 for a in diff.attributes if a.status != "same")
    children = tuple(_attribute_row("globals", a, _action("copy-attr", t="", s="", a=a.name)) for a in shown)
    return Row("globals", "Global attributes", "changed" if changed else "same", note=f"{changed} changed",
               expanded=True, children=children)


def _variable_group(var: VariableDiff, hide_same: bool) -> Row:
    """A renamed variable copies from its new name (reference) to its old one (target)."""
    target, source = var.old_name or var.name, var.name
    whole = var.status in ("added", "removed")
    attrs = [a for a in var.attributes if whole or not (hide_same and a.status == "same")]
    can_copy = var.status in ("changed", "renamed")
    children = tuple(Row(f"{target}/property/{p}", p, "changed", old, new) for p, old, new in var.properties)
    children += tuple(_attribute_row(target, a, _action("copy-attr", t=target, s=source, a=a.name) if can_copy else None)
                      for a in attrs)
    differing = sum(1 for a in var.attributes if a.status != "same") + len(var.properties)
    copy = (_action("copy-var", n=var.name) if var.status == "added"
            else _action("copy-all", t=target, s=source) if can_copy and any(_copyable(a) for a in var.attributes)
            else None)
    return Row(target, f"{var.old_name} → {var.name}" if var.old_name else var.name, var.status,
               note=f"{len(var.attributes)} attributes" if whole else f"{differing} changed" if differing else "",
               copy=copy, rename=_action("copy-rename", t=target, s=source) if var.status == "renamed" else None,
               expanded=not whole, children=children)


def _matches(row: Row, text: str) -> bool:
    return any(text in field.lower() for field in (row.name, row.old, row.new))


def _filtered(row: Row, text: str) -> Optional[Row]:
    """A group stays when its name matches (whole) or any child does (only those)."""
    if not text or _matches(row, text):
        return row
    children = tuple(c for c in row.children if _matches(c, text))
    return replace(row, children=children, expanded=True) if children else None


def build_rows(diff: DocumentDiff, hide_same: bool, text: str = "") -> list[Row]:
    groups = [_global_group(diff, hide_same)]
    groups += [_variable_group(v, hide_same) for v in diff.variables if not (hide_same and v.status == "same")]
    text = text.strip().lower()
    return [g for g in (_filtered(g, text) for g in groups if g is not None) if g is not None]


def copy_edit(action: str, reference: Document, diff: DocumentDiff) -> Callable[[Document], Document]:
    """The edit of the target that an action from build_rows stands for."""
    kind, _, query = action.partition(":")
    p = {k: v[0] for k, v in parse_qs(query, keep_blank_values=True).items()}
    if kind == "copy-var":
        return lambda d: copy_variable(d, reference, p["n"])
    if kind == "copy-attr":
        return lambda d: copy_attribute(d, reference, p["a"], p["t"], p["s"])
    if kind == "copy-rename":
        return lambda d: rename_variable(d, p["t"], p["s"], update_references=True)
    var = next(v for v in diff.variables if (v.old_name or v.name) == p["t"])
    names = [a.name for a in var.attributes if _copyable(a)]
    return lambda d: reduce(lambda acc, name: copy_attribute(acc, reference, name, p["t"], p["s"]), names, d)


def short_titles(a: str, b: str) -> tuple[str, str]:
    """Column titles: without ".cdf", and without the prefix both names share (up to an underscore)."""
    a, b = (name.removesuffix(".cdf") for name in (a, b))
    cut = commonprefix([a, b]).rfind("_") + 1
    return (f"…{a[cut:]}", f"…{b[cut:]}") if cut >= 4 else (a, b)
