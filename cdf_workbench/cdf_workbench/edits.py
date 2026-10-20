"""Attribute edits: typed text <-> values, and pure Document -> Document functions."""
from __future__ import annotations
import re
from dataclasses import replace
from math import prod
from typing import Any, Optional

import numpy as np
import pycdfpp

from .document import Attribute, Document, GlobalAttribute, Variable

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


def decode_text(raw: bytes) -> str:
    """CDF text is often Latin-1 in old files: undecodable bytes survive as surrogates, so an
    unedited value encodes back byte-exactly."""
    return raw.decode("utf-8", "surrogateescape")


def encode_text(text: str) -> bytes:
    return text.encode("utf-8", "surrogateescape")


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
    if not lines:
        raise ValueError("Enter at least one entry")
    return name, data_type, [parse_value(line, data_type) for line in lines]


# ISTP attributes whose value is the name of another variable.
_REFERENCE = re.compile(r"DEPEND_\w+|LABL_PTR_\d+|DELTA_(PLUS|MINUS)_VAR|UNIT_PTR|FORM_PTR|COMPONENT_\d+")


def _refers_to(attr_name: str, attr: Attribute, var_name: str) -> bool:
    return attr.type in _TEXT and _REFERENCE.fullmatch(attr_name) is not None and attr.value == var_name


def referenced_by(var: Variable) -> list[str]:
    """Names of the variables `var` points at (DEPEND_*, LABL_PTR_*, DELTA_*_VAR...)."""
    return [a.value for k, a in var.attributes.items()
            if a.type in _TEXT and _REFERENCE.fullmatch(k) and isinstance(a.value, str)]


def references_to(doc: Document, var_name: str) -> list[tuple[str, str]]:
    """(variable, attribute) pairs pointing at `var_name`."""
    return [(name, attr_name) for name, var in doc.items() for attr_name, attr in var.attributes.items()
            if _refers_to(attr_name, attr, var_name)]


def _retargeted(var, old: str, new: str):
    return replace(var, attributes={k: (replace(a, value=new) if _refers_to(k, a, old) else a)
                                    for k, a in var.attributes.items()})


def rename_variable(doc: Document, old: str, new: str, update_references: bool) -> Document:
    new = new.strip()
    if not new:
        raise ValueError("The variable needs a name")
    variables = _with_key(doc.variables, old, new, doc[old])
    if update_references:
        variables = {k: _retargeted(v, old, new) for k, v in variables.items()}
    return replace(doc, variables=variables)


def delete_variable(doc: Document, var_name: str) -> Document:
    return replace(doc, variables={k: v for k, v in doc.variables.items() if k != var_name})


_FROM_DTYPE = {np.dtype(dtype): data_type for data_type, dtype in (*_REAL.items(), *_INTEGER.items())
               if data_type not in (T.CDF_REAL4, T.CDF_REAL8, T.CDF_BYTE)}


def _as_cdf_array(values) -> tuple[np.ndarray, pycdfpp.DataType]:
    array = np.asarray(values)
    if array.dtype.kind in "SU":
        return np.char.encode(array, "utf-8") if array.dtype.kind == "U" else array, T.CDF_CHAR
    if array.dtype.kind == "M":
        return array.astype("datetime64[ns]"), T.CDF_TIME_TT2000
    if array.dtype not in _FROM_DTYPE:
        raise ValueError(f"No CDF type for {array.dtype} values")
    return array, _FROM_DTYPE[array.dtype]


def _attribute_for(value, var_type: pycdfpp.DataType) -> Attribute:
    """Text stays text; numbers take the variable's type (ISTP wants FILLVAL, VALIDMIN... typed
    like the data), or DOUBLE for a text or time variable."""
    if isinstance(value, str):
        return Attribute(value, T.CDF_CHAR)
    numeric_type = var_type if var_type in _INTEGER or var_type in _REAL else T.CDF_DOUBLE
    dtype = _INTEGER.get(numeric_type) or _REAL[numeric_type]
    return Attribute(np.atleast_1d(np.asarray(value, dtype=dtype)), numeric_type)


def new_variable(values, data_type: Optional[pycdfpp.DataType] = None, is_nrv: bool = False,
                 attributes: Optional[dict] = None) -> Variable:
    array, inferred = _as_cdf_array(values)
    data_type = data_type or inferred
    # pycdfpp counts the string length as the last dimension of a CDF_CHAR variable
    shape = array.shape + ((array.dtype.itemsize,) if data_type in _TEXT else ())
    return Variable(type=data_type, shape=shape, is_nrv=is_nrv,
                    compression=pycdfpp.CompressionType.no_compression,
                    attributes={k: _attribute_for(v, data_type) for k, v in (attributes or {}).items()},
                    load_values=lambda: array)


def add_variable(doc: Document, name: str, var: Variable) -> Document:
    name = name.strip()
    if not name:
        raise ValueError("The variable needs a name")
    return replace(doc, variables=_with_key(doc.variables, None, name, var))


def parse_values(text: str, data_type: pycdfpp.DataType) -> np.ndarray:
    """Values typed in the new variable dialog: labels one per line, numbers and times comma separated."""
    if data_type in _TEXT:
        return np.array([encode_text(line.strip()) for line in text.splitlines() if line.strip()])
    values = parse_value(text, data_type)
    dtype = _INTEGER.get(data_type) or _REAL.get(data_type) or "datetime64[ns]"
    return np.array(values, dtype=dtype)


def read_variable_form(name: str, data_type: pycdfpp.DataType, is_nrv: bool,
                       text: str) -> tuple[str, pycdfpp.DataType, bool, np.ndarray]:
    name = name.strip()
    if not name:
        raise ValueError("The variable needs a name")
    values = parse_values(text, data_type)
    if values.size == 0:
        raise ValueError("Enter at least one value")
    return name, data_type, is_nrv, values


def copy_attribute(target: Document, source: Document, name: str, target_var: str = "",
                   source_var: str = "") -> Document:
    """Copy one attribute from `source` (global when no variable is given), replacing the target's.
    The attribute keeps its origin, so even types pycdfpp can't write from values copy faithfully."""
    if not target_var:
        old = name if name in target.attributes else None
        return set_global_attribute(target, old, name, source.attributes[name])
    old = name if name in target[target_var].attributes else None
    return set_variable_attribute(target, target_var, old, name, source[source_var].attributes[name])


def copy_variable(target: Document, source: Document, name: str) -> Document:
    """The copy keeps reading its values lazily from the source file."""
    return add_variable(target, name, source[name])


# Editing values cell by cell only makes sense for labels and support data.
EDITABLE_CELLS = 10_000


def _values_shape(var: Variable) -> tuple:
    """pycdfpp counts a CDF_CHAR's string length as its last dimension; the values don't have it."""
    return tuple(var.shape[:-1]) if var.type in _TEXT else tuple(var.shape)


def values_editable(var: Variable) -> bool:
    editable_type = var.type in _TEXT or var.type in _INTEGER or var.type in _REAL or var.type in _TIME
    return editable_type and 0 < prod(_values_shape(var)) <= EDITABLE_CELLS


def _grid_orientation(var: Variable, records_by_columns: np.ndarray) -> np.ndarray:
    """Records as rows; a single-record (NRV) variable as one column, so labels read downwards."""
    return records_by_columns.T if var.is_nrv else records_by_columns


def _cell_text(value) -> str:
    return decode_text(value) if isinstance(value, bytes) else str(value)


def values_grid(var: Variable) -> list[list[str]]:
    values = var.values
    if var.type in _TIME:  # tolist() would turn ns datetimes into plain integers
        values = pycdfpp.to_datetime64(values).astype(str)
    grid = _grid_orientation(var, np.asarray(values).reshape(max(len(values), 1), -1))
    return [[_cell_text(v) for v in row] for row in grid.tolist()]


def _parse_cell(text: str, data_type: pycdfpp.DataType, row: int, column: int):
    if data_type in _TEXT:
        return encode_text(text)
    try:
        return _parse_item(text.strip(), data_type)
    except (ValueError, OverflowError):
        raise ValueError(f"row {row + 1}, column {column + 1}: {text!r} is not a valid "
                         f"{data_type.name.removeprefix('CDF_')} value") from None


def values_from_grid(cells: list[list[str]], var: Variable) -> np.ndarray:
    """The inverse of values_grid; raises ValueError naming the first bad cell."""
    parsed = [[_parse_cell(text, var.type, r, c) for c, text in enumerate(row)] for r, row in enumerate(cells)]
    dtype = _INTEGER.get(var.type) or _REAL.get(var.type) or ("datetime64[ns]" if var.type in _TIME else None)
    grid = np.array(parsed, dtype=dtype)
    return _grid_orientation(var, grid).reshape(_values_shape(var))


def set_variable_values(doc: Document, name: str, values: np.ndarray) -> Document:
    var = doc[name]
    shape = values.shape + ((values.dtype.itemsize,) if var.type in _TEXT else ())
    edited = replace(var, shape=shape, load_values=lambda: values)
    return replace(doc, variables={**doc.variables, name: edited})
