"""Editable in-memory copy of a CDF.

A pycdfpp.CDF can't rename variables, drop attributes or overwrite them. So we
never edit it: edits are pure functions over these frozen dataclasses, and
`to_cdf` builds a fresh CDF when saving.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

import numpy as np
import pycdfpp
from PySide6.QtCore import QObject, Signal


@dataclass(frozen=True)
class Attribute:
    """A variable attribute, or one entry of a global attribute."""
    value: Any
    type: pycdfpp.DataType
    # simplify: pycdfpp 0.15 can't write CDF_BYTE or empty attributes from values,
    # so an unedited attribute is copied verbatim from the object it was read from.
    # Drop `origin` once pycdfpp accepts them from values.
    origin: Optional[Any] = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class GlobalAttribute:
    entries: tuple[Attribute, ...]
    origin: Optional[Any] = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class Variable:
    type: pycdfpp.DataType
    shape: tuple
    is_nrv: bool
    compression: pycdfpp.CompressionType
    attributes: dict[str, Attribute]
    load_values: Callable[[], np.ndarray] = field(compare=False, repr=False)

    @property
    def values(self) -> np.ndarray:
        return self.load_values()


@dataclass(frozen=True)
class Document:
    attributes: dict[str, GlobalAttribute]
    variables: dict[str, Variable]

    def __getitem__(self, name: str) -> Variable:
        return self.variables[name]

    def __contains__(self, name: str) -> bool:
        return name in self.variables

    def keys(self) -> Iterator[str]:
        return iter(self.variables.keys())

    def items(self) -> Iterator[tuple[str, Variable]]:
        return iter(self.variables.items())


def attribute_lists(var: Variable) -> dict[str, list]:
    return {name: [attr.value] for name, attr in var.attributes.items()}


def global_attribute_lists(doc: Document) -> dict[str, list]:
    return {name: [e.value for e in attr.entries] for name, attr in doc.attributes.items()}


def from_cdf(cdf: pycdfpp.CDF) -> Document:
    return Document(
        attributes={name: _global_entries(attr) for name, attr in cdf.attributes.items()},
        variables={name: _variable_from(cdf, name, var) for name, var in cdf.items()},
    )


def _global_entries(attr) -> GlobalAttribute:
    return GlobalAttribute(tuple(Attribute(attr[i], attr.type(i)) for i in range(len(attr))), attr)


def _variable_from(cdf: pycdfpp.CDF, name: str, var) -> Variable:
    return Variable(
        type=var.type,
        shape=tuple(var.shape),
        is_nrv=var.is_nrv,
        compression=var.compression,
        attributes={n: Attribute(a.value, a.type(), a) for n, a in var.attributes.items()},
        load_values=lambda: cdf[name].values,
    )


def to_cdf(doc: Document) -> pycdfpp.CDF:
    cdf = pycdfpp.CDF()
    for name, attr in doc.attributes.items():
        _write_global(cdf, name, attr)
    for name, var in doc.variables.items():
        _write_variable(cdf, name, var)
    return cdf


def _same(a, b) -> bool:
    # repr compares lists, strings, numpy arrays and NaN fill values alike
    return repr(a) == repr(b)


def _global_is_pristine(name: str, attr: GlobalAttribute) -> bool:
    origin = attr.origin
    return (origin is not None and origin.name == name and len(origin) == len(attr.entries)
            and all(e.type == origin.type(i) and _same(e.value, origin[i])
                    for i, e in enumerate(attr.entries)))


def _write_global(cdf: pycdfpp.CDF, name: str, attr: GlobalAttribute) -> None:
    if _global_is_pristine(name, attr):
        cdf.add_attribute(attr.origin)
    else:
        cdf.add_attribute(name, [e.value for e in attr.entries], [e.type for e in attr.entries])


def _variable_attribute_is_pristine(name: str, attr: Attribute) -> bool:
    origin = attr.origin
    return (origin is not None and origin.name == name and origin.type() == attr.type
            and _same(origin.value, attr.value))


def _write_variable(cdf: pycdfpp.CDF, name: str, var: Variable) -> None:
    out = cdf.add_variable(name, values=var.values, data_type=var.type,
                           is_nrv=var.is_nrv, compression=var.compression)
    for attr_name, attr in var.attributes.items():
        if _variable_attribute_is_pristine(attr_name, attr):
            out.add_attribute(attr.origin)
        else:
            out.add_attribute(attr_name, attr.value, attr.type)


class DocumentSession(QObject):
    """The current document of one tab, where it is saved, and whether it differs from that."""
    changed = Signal()

    def __init__(self, document: Document, source: str = "", parent=None):
        super().__init__(parent)
        self._document = document
        self._saved = document
        self._source = source

    @property
    def source(self) -> str:
        return self._source

    @property
    def can_save_in_place(self) -> bool:
        return bool(self._source) and not self._source.startswith(("http://", "https://"))

    @property
    def document(self) -> Document:
        return self._document

    @property
    def is_modified(self) -> bool:
        return self._document is not self._saved

    def apply(self, edit: Callable[[Document], Document]) -> None:
        edited = edit(self._document)
        if edited is self._document:
            raise ValueError("an edit must return a new Document, not mutate the current one")
        self._document = edited
        self.changed.emit()

    def mark_saved(self) -> None:
        self._saved = self._document
        self.changed.emit()

    def save(self, path: Optional[str] = None) -> None:
        """Saving over the source file is safe: `to_cdf` reads every value before writing."""
        path = path or self._source
        pycdfpp.save(to_cdf(self._document), path)
        self._source = path
        self.mark_saved()
