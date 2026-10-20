"""Exports of a document: its structure as YAML, a variable's plotted data, a subset of variables."""
from __future__ import annotations
import csv
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml

from .document import Attribute, Document
from .edits import referenced_by

if TYPE_CHECKING:
    from .file_view import PlotBundle


def _plain(value: Any) -> Any:
    """YAML-safe: text and numbers as they are, CDF times and numpy scalars as text or Python numbers."""
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_plain(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return str(value)


def _attribute(entries: list[Attribute]) -> dict:
    return {"values": [_plain(e.value) for e in entries], "types": [str(e.type) for e in entries]}


def skeleton(doc: Document) -> dict:
    """Same layout as pycdfpp.to_dict_skeleton, built without reading any value.
    File-level compression is missing: the document doesn't keep it."""
    return {
        "attributes": {name: _attribute(list(attr.entries)) for name, attr in doc.attributes.items()},
        "variables": {
            name: {
                "attributes": {k: _attribute([a]) for k, a in var.attributes.items()},
                "compression": str(var.compression),
                "is_nrv": var.is_nrv,
                "shape": list(var.shape),
                "type": str(var.type),
            }
            for name, var in doc.items()
        },
    }


def skeleton_yaml(doc: Document) -> str:
    return yaml.safe_dump(skeleton(doc), sort_keys=False, allow_unicode=True)


def _times(bundle: "PlotBundle") -> np.ndarray:
    # x is float64 seconds: about 0.24 µs resolution in this era, so ns digits would be noise
    return np.round(bundle.x * 1e6).astype(np.int64).astype("datetime64[us]")


def _column_names(bundle: "PlotBundle") -> list[str]:
    if bundle.values.ndim == 1:
        labels = list(bundle.hints.component_labels or [])
        return labels[:1] or ["value"]
    n = bundle.values.shape[1]
    if bundle.is_spectrogram and bundle.depend_1 is not None:
        rows = bundle.depend_1.reshape(-1, bundle.depend_1.shape[-1])
        if not np.allclose(rows, rows[0], equal_nan=True):  # time-varying bins: use the .npz for them
            return [f"bin {i}" for i in range(n)]
        return [f"{b:g}" for b in rows[0]]
    labels = list(bundle.hints.component_labels or [])
    return labels[:n] + [f"#{i}" for i in range(len(labels), n)]


def write_csv(path: str, bundle: "PlotBundle") -> None:
    """The plotted data: masked, reduced and flipped like the plot. Missing values are empty cells."""
    x = _times(bundle).astype(str) if bundle.is_time_axis else bundle.x
    rows = bundle.values.reshape(len(bundle.values), -1)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["time" if bundle.is_time_axis else "x", *_column_names(bundle)])
        for xi, row in zip(x, rows):
            writer.writerow([xi, *("" if np.isnan(v) else repr(float(v)) for v in row)])


def write_npz(path: str, bundle: "PlotBundle") -> None:
    axes = {"time": _times(bundle)} if bundle.is_time_axis else {"x": bundle.x}
    if bundle.depend_1 is not None:
        axes["depend_1"] = bundle.depend_1
    np.savez(path, values=bundle.values, **axes)


def subset(doc: Document, names: list[str]) -> Document:
    """`names` and, recursively, every variable they point at, in file order."""
    keep, todo = set(), list(names)
    while todo:
        name = todo.pop()
        if name in doc and name not in keep:
            keep.add(name)
            todo.extend(referenced_by(doc[name]))
    return replace(doc, variables={k: v for k, v in doc.items() if k in keep})
