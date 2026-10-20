"""C1: structural comparison of two documents: variables (type, per-record shape, NRV,
compression, attributes) and global attributes. Values are not compared: that would read
every value of both files. Port of the CDFpp explorer's cdf-diff (411e53b…9955bf4, f3f9a4d,
d7bf3b3)."""
from __future__ import annotations
import html
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from .document import Document, GlobalAttribute, Variable
from .edits import format_value

Status = Literal["same", "added", "removed", "changed", "renamed"]
# A removed and an added variable this similar (Jaccard over properties and attributes, like
# `git diff -M`) are reported as one renamed variable.
RENAME_SIMILARITY = 0.5


@dataclass(frozen=True)
class AttributeDiff:
    name: str
    status: Status
    old: str = ""
    new: str = ""


@dataclass(frozen=True)
class VariableDiff:
    name: str
    status: Status
    old_name: str = ""
    properties: tuple[tuple[str, str, str], ...] = ()  # (property, old, new) that differ
    attributes: tuple[AttributeDiff, ...] = ()


@dataclass(frozen=True)
class DocumentDiff:
    attributes: tuple[AttributeDiff, ...]
    variables: tuple[VariableDiff, ...]

    def summary(self) -> dict[str, int]:
        """How many variables are in each status."""
        return dict(Counter(v.status for v in self.variables))


def _properties(var: Variable) -> dict[str, str]:
    """The record count is left out: two days of one product differ only by it."""
    shape = var.shape if var.is_nrv else var.shape[1:]
    return {"type": var.type.name, "shape": str(tuple(shape)), "nrv": str(var.is_nrv),
            "compression": var.compression.name}


def _attribute_texts(var: Variable) -> dict[str, str]:
    return {name: format_value(attr.value) for name, attr in var.attributes.items()}


def _global_text(attr: GlobalAttribute) -> str:
    return "\n".join(format_value(e.value) for e in attr.entries)


def _diff_mappings(old: dict[str, str], new: dict[str, str]) -> tuple[AttributeDiff, ...]:
    names = list(old) + [n for n in new if n not in old]

    def one(name: str) -> AttributeDiff:
        if name not in new:
            return AttributeDiff(name, "removed", old=old[name])
        if name not in old:
            return AttributeDiff(name, "added", new=new[name])
        return AttributeDiff(name, "same" if old[name] == new[name] else "changed", old[name], new[name])
    return tuple(one(n) for n in names)


def _compare(name: str, old: Variable, new: Variable, old_name: str = "") -> VariableDiff:
    po, pn = _properties(old), _properties(new)
    properties = tuple((k, po[k], pn[k]) for k in po if po[k] != pn[k])
    attributes = _diff_mappings(_attribute_texts(old), _attribute_texts(new))
    changed = bool(properties) or any(a.status != "same" for a in attributes)
    status = "renamed" if old_name else ("changed" if changed else "same")
    return VariableDiff(name, status, old_name, properties, attributes)


def _features(var: Variable) -> set:
    return ({("p", *kv) for kv in _properties(var).items()}
            | {("a", *kv) for kv in _attribute_texts(var).items()})


_SAME_FOR_A_RENAME = ("type", "shape", "nrv")


def _similarity(a: Variable, b: Variable) -> float:
    """A rename keeps type, per-record shape and NRV; otherwise it is honestly a removal plus an
    addition. Properties alone are shared by unrelated variables, so a common attribute is needed too."""
    pa, pb = _properties(a), _properties(b)
    if any(pa[k] != pb[k] for k in _SAME_FOR_A_RENAME):
        return 0.0
    fa, fb = _features(a), _features(b)
    common = fa & fb
    if not any(feature[0] == "a" for feature in common):
        return 0.0
    return len(common) / len(fa | fb)


def _renames(old: Document, new: Document, removed: list[str], added: list[str]) -> dict[str, str]:
    """new name -> old name, pairing the most similar first."""
    # simplify: compares every removed/added pair, O(r*a); fine for the few unmatched variables of
    # real files. Bucket by type and shape first if thousands are renamed at once.
    pairs = sorted(((_similarity(old[r], new[a]), r, a) for r in removed for a in added), reverse=True)
    renames: dict[str, str] = {}
    for score, r, a in pairs:
        if score >= RENAME_SIMILARITY and r not in renames.values() and a not in renames:
            renames[a] = r
    return renames


def diff_documents(old: Document, new: Document) -> DocumentDiff:
    removed = [n for n in old.keys() if n not in new]
    added = [n for n in new.keys() if n not in old]
    renames = _renames(old, new, removed, added)
    renamed_from = {r: a for a, r in renames.items()}

    def entry(name: str) -> VariableDiff:
        if name in renamed_from:
            return _compare(renamed_from[name], old[name], new[renamed_from[name]], old_name=name)
        if name not in new:
            return VariableDiff(name, "removed", attributes=_diff_mappings(_attribute_texts(old[name]), {}))
        return _compare(name, old[name], new[name])

    variables = [entry(n) for n in old.keys()]
    variables += [VariableDiff(n, "added", attributes=_diff_mappings({}, _attribute_texts(new[n])))
                  for n in added if n not in renames]
    attributes = _diff_mappings({k: _global_text(v) for k, v in old.attributes.items()},
                                {k: _global_text(v) for k, v in new.attributes.items()})
    return DocumentDiff(attributes, tuple(variables))


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _mark(tokens: list[str], tag: str) -> str:
    text = "".join(tokens)
    return f"<{tag}>{_escape(text)}</{tag}>" if text else ""


def _word_level(old: str, new: str) -> tuple[str, str]:
    a, b = re.split(r"(\s+)", old), re.split(r"(\s+)", new)
    out_a, out_b = [], []
    for op, i1, i2, j1, j2 in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out_a.append(_escape("".join(a[i1:i2])))
            out_b.append(_escape("".join(b[j1:j2])))
        else:
            out_a.append(_mark(a[i1:i2], "del"))
            out_b.append(_mark(b[j1:j2], "ins"))
    return "".join(out_a), "".join(out_b)


def _similar_lines(a: str, b: str) -> bool:
    return SequenceMatcher(a=a.split(), b=b.split(), autojunk=False).ratio() >= RENAME_SIMILARITY


def word_diff(old: str, new: str) -> tuple[str, str]:
    """HTML of both values: unchanged lines plain; an edited line gets word-level <del>/<ins>
    marks when it still resembles its counterpart, else it is marked whole."""
    a, b = old.split("\n"), new.split("\n")
    out_a, out_b = [], []
    for op, i1, i2, j1, j2 in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out_a += [_escape(line) for line in a[i1:i2]]
            out_b += [_escape(line) for line in b[j1:j2]]
            continue
        old_lines, new_lines = a[i1:i2], b[j1:j2]
        for k in range(max(len(old_lines), len(new_lines))):
            line_a = old_lines[k] if k < len(old_lines) else None
            line_b = new_lines[k] if k < len(new_lines) else None
            if line_a is not None and line_b is not None and _similar_lines(line_a, line_b):
                marked_a, marked_b = _word_level(line_a, line_b)
                out_a.append(marked_a)
                out_b.append(marked_b)
                continue
            if line_a is not None:
                out_a.append(_mark([line_a], "del"))
            if line_b is not None:
                out_b.append(_mark([line_b], "ins"))
    return "\n".join(out_a), "\n".join(out_b)
