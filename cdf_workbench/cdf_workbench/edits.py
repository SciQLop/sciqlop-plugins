"""Attribute edits: typed text <-> values, and pure Document -> Document functions."""
from __future__ import annotations
from dataclasses import replace
from typing import Any, Optional

import numpy as np
import pycdfpp

from .document import Attribute, Document, GlobalAttribute

T = pycdfpp.DataType
_TEXT = {T.CDF_CHAR, T.CDF_UCHAR}
_INTEGER = {T.CDF_BYTE: np.int8, T.CDF_INT1: np.int8, T.CDF_INT2: np.int16, T.CDF_INT4: np.int32,
            T.CDF_INT8: np.int64, T.CDF_UINT1: np.uint8, T.CDF_UINT2: np.uint16, T.CDF_UINT4: np.uint32}
_REAL = {T.CDF_FLOAT: np.float32, T.CDF_REAL4: np.float32, T.CDF_DOUBLE: np.float64, T.CDF_REAL8: np.float64}
_TIME = {T.CDF_EPOCH, T.CDF_EPOCH16, T.CDF_TIME_TT2000}

# The types offered when adding or retyping an attribute, most common first.
ATTRIBUTE_TYPES = (T.CDF_CHAR, T.CDF_DOUBLE, T.CDF_FLOAT, T.CDF_INT4, T.CDF_INT2, T.CDF_INT1, T.CDF_INT8,
                   T.CDF_UINT1, T.CDF_UINT2, T.CDF_UINT4, T.CDF_REAL4, T.CDF_REAL8, T.CDF_TIME_TT2000,
                   T.CDF_EPOCH, T.CDF_EPOCH16, T.CDF_UCHAR)


def _parse_item(item: str, data_type: pycdfpp.DataType):
    if data_type in _INTEGER:
        return np.array(int(item), dtype=_INTEGER[data_type]).item()
    if data_type in _REAL:
        return np.array(float(item), dtype=_REAL[data_type]).item()
    if data_type in _TIME:
        return np.datetime64(item, "ns")
    raise ValueError(f"{data_type.name} attributes can't be edited")


def parse_value(text: str, data_type: pycdfpp.DataType) -> Any:
    """Text as typed by the user: text types as is, others as comma separated values."""
    if data_type in _TEXT:
        return text
    items = [item.strip() for item in text.split(",") if item.strip()]
    if not items:
        raise ValueError("Enter at least one value")
    kind = data_type.name.removeprefix("CDF_")
    values = []
    for item in items:
        try:
            values.append(_parse_item(item, data_type))
        except (ValueError, OverflowError):
            raise ValueError(f"{item!r} is not a valid {kind} value") from None
    return values


def format_value(value: Any) -> str:
    if isinstance(value, (list, tuple, np.ndarray)):
        return ", ".join(str(v) for v in value)
    return str(value)


def _with_key(mapping: dict, old: Optional[str], new: str, value) -> dict:
    """Set `new` in place of `old` (same position), or append it when `old` is None."""
    if new != old and new in mapping:
        raise ValueError(f"{new} already exists")
    if old is None:
        return {**mapping, new: value}
    return {(new if k == old else k): (value if k == old else v) for k, v in mapping.items()}


def set_variable_attribute(doc: Document, var_name: str, old_name: Optional[str], name: str,
                           attr: Attribute) -> Document:
    var = doc[var_name]
    edited = replace(var, attributes=_with_key(var.attributes, old_name, name, attr))
    return replace(doc, variables={**doc.variables, var_name: edited})


def remove_variable_attribute(doc: Document, var_name: str, name: str) -> Document:
    var = doc[var_name]
    edited = replace(var, attributes={k: v for k, v in var.attributes.items() if k != name})
    return replace(doc, variables={**doc.variables, var_name: edited})


def set_global_attribute(doc: Document, old_name: Optional[str], name: str, attr: GlobalAttribute) -> Document:
    return replace(doc, attributes=_with_key(doc.attributes, old_name, name, attr))


def remove_global_attribute(doc: Document, name: str) -> Document:
    return replace(doc, attributes={k: v for k, v in doc.attributes.items() if k != name})


def read_attribute_form(name: str, data_type: pycdfpp.DataType, text: str,
                        multi_entry: bool) -> tuple[str, pycdfpp.DataType, list]:
    """What the attribute dialog returns: a variable attribute has one value, a global
    attribute one entry per non-empty line."""
    name = name.strip()
    if not name:
        raise ValueError("The attribute needs a name")
    lines = [line for line in text.splitlines() if line.strip()] if multi_entry else [text]
    return name, data_type, [parse_value(line, data_type) for line in lines]
