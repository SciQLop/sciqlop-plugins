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


@dataclass(frozen=True)
class GlobalAttribute:
    entries: tuple[Attribute, ...]


@dataclass(frozen=True)
class Variable:
    type: pycdfpp.DataType
    shape: tuple
    is_nrv: bool
    compression: pycdfpp.CompressionType
    attributes: dict[str, Attribute]
    load_values: Callable[[], np.ndarray] = field(compare=False, repr=False)
    compression_level: int = 6
    sparse_records: pycdfpp.SparseRecords = pycdfpp.SparseRecords.no_sparse_records
    pad_value: Any = field(default=None, compare=False)
    # One bool per record, True for records the file doesn't store; None: all stored.
    virtual_records: Optional[np.ndarray] = field(default=None, compare=False, repr=False)

    @property
    def values(self) -> np.ndarray:
        return self.load_values()


@dataclass(frozen=True)
class FileProperties:
    """What a CDF declares beside its attributes and variables, saved back as loaded."""
    compression: pycdfpp.CompressionType
    compression_level: int
    majority: pycdfpp.Majority
    encoding: pycdfpp.Encoding
    checksum: pycdfpp.Checksum
    declared_variable_attributes: tuple[str, ...]
    # Declared but used by no variable when loaded (masters do that): kept even though unused.
    unused_variable_attributes: tuple[str, ...]

    @staticmethod
    def of(cdf: pycdfpp.CDF) -> "FileProperties":
        declared = tuple(cdf.declared_variable_attributes)
        used = {name for _, var in cdf.items() for name in var.attributes.keys()}
        return FileProperties(cdf.compression, cdf.compression_level, cdf.majority, cdf.encoding,
                              cdf.checksum, declared, tuple(n for n in declared if n not in used))


_NEW_FILE = FileProperties.of(pycdfpp.CDF())


@dataclass(frozen=True)
class Document:
    attributes: dict[str, GlobalAttribute]
    variables: dict[str, Variable]
    properties: FileProperties = _NEW_FILE

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
        properties=FileProperties.of(cdf),
    )


def _global_entries(attr) -> GlobalAttribute:
    return GlobalAttribute(tuple(Attribute(attr[i], attr.type(i)) for i in range(len(attr))))


def _variable_from(cdf: pycdfpp.CDF, name: str, var) -> Variable:
    return Variable(
        type=var.type,
        shape=tuple(var.shape),
        is_nrv=var.is_nrv,
        compression=var.compression,
        attributes={n: Attribute(a.value, a.type()) for n, a in var.attributes.items()},
        load_values=lambda: cdf[name].values,
        compression_level=var.compression_level,
        sparse_records=var.sparse_records,
        pad_value=var.pad_value,
        virtual_records=np.asarray(var.virtual_records) if np.any(var.virtual_records) else None,
    )


def to_cdf(doc: Document) -> pycdfpp.CDF:
    cdf = pycdfpp.CDF()
    for name, attr in doc.attributes.items():
        _write_global(cdf, name, attr)
    for name, var in doc.variables.items():
        _write_variable(cdf, name, var)
    _write_file_properties(cdf, doc)
    return cdf


def _declared_variable_attributes(doc: Document) -> list[str]:
    """The loaded order, minus names an edit left unused, plus names an edit introduced."""
    props = doc.properties
    used = list(dict.fromkeys(name for _, var in doc.items() for name in var.attributes))
    kept = [n for n in props.declared_variable_attributes if n in used or n in props.unused_variable_attributes]
    return kept + [n for n in used if n not in kept]


def _write_file_properties(cdf: pycdfpp.CDF, doc: Document) -> None:
    props = doc.properties
    cdf.compression = props.compression
    cdf.compression_level = props.compression_level
    cdf.majority = props.majority
    cdf.encoding = props.encoding
    cdf.checksum = props.checksum
    cdf.declared_variable_attributes = _declared_variable_attributes(doc)


def _write_global(cdf: pycdfpp.CDF, name: str, attr: GlobalAttribute) -> None:
    cdf.add_attribute(name, [e.value for e in attr.entries], [e.type for e in attr.entries])


def _write_variable(cdf: pycdfpp.CDF, name: str, var: Variable) -> None:
    out = cdf.add_variable(name, values=var.values, data_type=var.type, is_nrv=var.is_nrv,
                           compression=var.compression, compression_level=var.compression_level,
                           sparse_records=var.sparse_records, pad_value=var.pad_value,
                           virtual_records=var.virtual_records)
    for attr_name, attr in var.attributes.items():
        out.add_attribute(attr_name, attr.value, attr.type)


class DocumentSession(QObject):
    """The current document of one tab, where it is saved, and whether it differs from that."""
    changed = Signal()

    def __init__(self, document: Document, source: str = "", parent=None):
        super().__init__(parent)
        # simplify: unbounded history. Documents share unchanged data, so it only grows with
        # edited values (E8); cap its length if value edits on big variables make it heavy.
        self._history = [document]
        self._index = 0
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
        return self._history[self._index]

    @property
    def is_modified(self) -> bool:
        return self.document is not self._saved

    @property
    def can_undo(self) -> bool:
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        return self._index < len(self._history) - 1

    def apply(self, edit: Callable[[Document], Document]) -> None:
        edited = edit(self.document)
        if edited is self.document:
            raise ValueError("an edit must return a new Document, not mutate the current one")
        self._history = self._history[:self._index + 1] + [edited]
        self._index += 1
        self.changed.emit()

    def undo(self) -> None:
        if self.can_undo:
            self._index -= 1
            self.changed.emit()

    def redo(self) -> None:
        if self.can_redo:
            self._index += 1
            self.changed.emit()

    def mark_saved(self) -> None:
        self._saved = self.document
        self.changed.emit()

    def save(self, path: Optional[str] = None) -> None:
        """Saving over the source file is safe: `to_cdf` reads every value before writing."""
        path = path or self._source
        pycdfpp.save(to_cdf(self.document), path)
        self._source = path
        self.mark_saved()
