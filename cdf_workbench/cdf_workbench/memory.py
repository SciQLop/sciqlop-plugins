"""Refuse to read a variable whose values can't fit in free memory, instead of crashing SciQLop."""
from __future__ import annotations
from math import prod
from typing import Optional

import psutil
import pycdfpp

from .document import Variable

_T = pycdfpp.DataType
_ITEM_SIZE = {
    _T.CDF_BYTE: 1, _T.CDF_CHAR: 1, _T.CDF_UCHAR: 1, _T.CDF_INT1: 1, _T.CDF_UINT1: 1,
    _T.CDF_INT2: 2, _T.CDF_UINT2: 2,
    _T.CDF_INT4: 4, _T.CDF_UINT4: 4, _T.CDF_FLOAT: 4, _T.CDF_REAL4: 4,
    _T.CDF_INT8: 8, _T.CDF_DOUBLE: 8, _T.CDF_REAL8: 8, _T.CDF_EPOCH: 8, _T.CDF_TIME_TT2000: 8,
    _T.CDF_EPOCH16: 16, _T.CDF_NONE: 0,
}

# Reading for a plot holds the decoded values, a float64 copy and a validity mask.
_PLOT_OVERHEAD_PER_VALUE = 8 + 1


def decoded_nbytes(var: Variable) -> int:
    """Size of the decoded values, from shape and type only. CDF_CHAR shapes include the string length."""
    return prod(var.shape) * _ITEM_SIZE[var.type]


def available_memory() -> int:
    return psutil.virtual_memory().available


def format_bytes(n: float) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    k = 0
    while n >= 1024 and k < len(units) - 1:
        n, k = n / 1024, k + 1
    return f"{n:.0f} B" if k == 0 else f"{n:.1f} {units[k]}"


def memory_problem(name: str, var: Variable, available: int) -> Optional[str]:
    values = prod(var.shape)
    needed = decoded_nbytes(var) + values * _PLOT_OVERHEAD_PER_VALUE
    if needed <= available:
        return None
    return (f"{name} needs about {format_bytes(needed)}, "
            f"only {format_bytes(available)} of memory is free.")
