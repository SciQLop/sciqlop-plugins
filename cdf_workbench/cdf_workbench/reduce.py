"""Reduce rank > 2 variables (particle distributions) to a time series or a spectrogram.

Each non-record axis gets a mode: PLOT (becomes the y axis, at most one), SUM or MEAN
(collapsed), or an int (keep that single slice). Port of the CDFpp explorer (d640f2b).
"""
from __future__ import annotations
import re
from dataclasses import replace
from typing import Optional, Union

import numpy as np
import pycdfpp

from .tree_model import VariableInfo

PLOT = "plot"
SUM = "sum"
MEAN = "mean"
Mode = Union[str, int]

_ENERGY = re.compile("energ", re.IGNORECASE)
_NOT_REDUCIBLE = {pycdfpp.DataType.CDF_CHAR, pycdfpp.DataType.CDF_UCHAR, pycdfpp.DataType.CDF_NONE,
                  pycdfpp.DataType.CDF_EPOCH, pycdfpp.DataType.CDF_EPOCH16,
                  pycdfpp.DataType.CDF_TIME_TT2000}


def needs_reduction(info: VariableInfo) -> bool:
    return info.cdf_type not in _NOT_REDUCIBLE and len(info.shape) > 2 and info.shape[0] > 0


def axis_attribute(info: VariableInfo, key: str, axis: int) -> str:
    """`key`_k of non-record axis `axis` (0-based), e.g. DEPEND_3 for axis 2."""
    values = info.all_attributes.get(f"{key}_{axis + 1}") or [""]
    return str(values[0])


def default_modes(info: VariableInfo) -> tuple[Mode, ...]:
    """Plot the energy axis (found from its DEPEND_k name), else the last one; sum the others."""
    axes = range(len(info.shape) - 1)
    plotted = next((k for k in axes if _ENERGY.search(axis_attribute(info, "DEPEND", k))), axes[-1])
    return tuple(PLOT if k == plotted else SUM for k in axes)


def with_axis_mode(modes: tuple[Mode, ...], axis: int, mode: Mode) -> tuple[Mode, ...]:
    return tuple(mode if k == axis else SUM if mode == PLOT and m == PLOT else m
                 for k, m in enumerate(modes))


def _valid_only(values: np.ndarray, fill_value, valid_min, valid_max) -> np.ndarray:
    data = values.astype(np.float64)
    invalid = ~np.isfinite(data)
    if fill_value is not None:
        invalid |= values == np.array(fill_value, dtype=values.dtype)
    if valid_min is not None:
        invalid |= data < valid_min
    if valid_max is not None:
        invalid |= data > valid_max
    data[invalid] = np.nan
    return data


def _collapse(data: np.ndarray, axes: tuple[int, ...], mode: str) -> np.ndarray:
    if not axes:
        return data
    count = np.sum(np.isfinite(data), axis=axes)
    total = np.nansum(data, axis=axes)
    with np.errstate(invalid="ignore", divide="ignore"):
        result = total / count if mode == MEAN else total
    return np.where(count > 0, result, np.nan)


def reduce_values(values: np.ndarray, modes: tuple[Mode, ...], fill_value=None,
                  valid_min: Optional[float] = None, valid_max: Optional[float] = None) -> np.ndarray:
    """Invalid values (FILLVAL, out of VALIDMIN/VALIDMAX, non-finite) are left out of sums and means.

    Sums run before means, so mixing them averages the sums.
    """
    # simplify: masks a float64 copy of the whole variable. Fine for a preview of
    # files that fit in memory; reduce chunk by chunk of records for huge burst files.
    data = _valid_only(values, fill_value, valid_min, valid_max)
    data = data[(slice(None),) + tuple(m if isinstance(m, int) else slice(None) for m in modes)]
    remaining = [m for m in modes if not isinstance(m, int)]
    data = _collapse(data, tuple(k + 1 for k, m in enumerate(remaining) if m == SUM), SUM)
    remaining = [m for m in remaining if m != SUM]
    return _collapse(data, tuple(k + 1 for k, m in enumerate(remaining) if m == MEAN), MEAN)


def reduced_info(info: VariableInfo, modes: tuple[Mode, ...]) -> VariableInfo:
    """Metadata of the reduced variable. Validity is already applied, so FILLVAL, VALIDMIN and
    VALIDMAX are dropped: a sum may rightly exceed VALIDMAX."""
    plotted = modes.index(PLOT) if PLOT in modes else None
    attrs = {k: v for k, v in info.all_attributes.items()
             if k not in ("FILLVAL", "VALIDMIN", "VALIDMAX", "DISPLAY_TYPE")
             and not re.fullmatch(r"(DEPEND|LABL_PTR)_[1-9]", k)}
    depend_1 = labl_ptr_1 = ""
    if plotted is not None:
        depend_1 = axis_attribute(info, "DEPEND", plotted)
        labl_ptr_1 = axis_attribute(info, "LABL_PTR", plotted)
        attrs.update({k: [v] for k, v in (("DEPEND_1", depend_1), ("LABL_PTR_1", labl_ptr_1)) if v})
    display_type = "spectrogram" if plotted is not None else "time_series"
    attrs["DISPLAY_TYPE"] = [display_type]
    shape = (info.shape[0],) + ((info.shape[plotted + 1],) if plotted is not None else ())
    return replace(info, shape=shape, depend_1=depend_1, labl_ptr_1=labl_ptr_1,
                   display_type=display_type, fill_value=None, valid_min=None, valid_max=None,
                   cdf_type=pycdfpp.DataType.CDF_DOUBLE, all_attributes=attrs)
