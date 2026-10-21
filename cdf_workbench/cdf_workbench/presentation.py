"""How a variable and its quality are summarised: the tree row and the inspector's quality line."""
from __future__ import annotations
from os.path import commonprefix
from typing import Optional

import pycdfpp

from .quality import QualityReport
from .tree_model import VariableInfo

_DISPLAY_TYPES = {"time_series": "TS", "spectrogram": "SP", "stack_plot": "SK", "no_plot": "no plot"}
_TEXT = {pycdfpp.DataType.CDF_CHAR, pycdfpp.DataType.CDF_UCHAR}
_ERROR_BELOW = 50.0


def row_label(info: VariableInfo) -> str:
    """e.g. "2D · TS". A text variable's string length is not a dimension."""
    ndim = len(info.shape) - (1 if info.cdf_type in _TEXT else 0)
    display = _DISPLAY_TYPES.get(info.display_type.lower().strip(), "")
    return " · ".join(part for part in (f"{ndim}D", display) if part)


def _pct(value: float) -> str:
    return f"{round(value, 1):g}%"


def _is_complete(valid_pct: float) -> bool:
    return round(valid_pct) >= 100


def quality_badge(valid_pct: float) -> Optional[tuple[str, str]]:
    """(text, level) for the tree, or None when nothing is missing: a 100% badge on every row is noise."""
    if _is_complete(valid_pct):
        return None
    return f"{valid_pct:.0f}%", "warning" if valid_pct > _ERROR_BELOW else "error"


def quality_summary(report: QualityReport) -> tuple[str, str]:
    """One line for the inspector, and its level: "ok", "warning" or "error"."""
    valid = report.valid_percentage
    level = ("error" if valid <= _ERROR_BELOW
             else "ok" if _is_complete(valid) and report.epoch_gaps == 0 else "warning")
    text = (f"{_pct(valid)} valid · {_pct(report.fill_percentage)} fill · "
            f"{_pct(report.out_of_range_percentage)} out of range · {report.epoch_gaps} gaps")
    return ("✓ " + text if level == "ok" else text), level


def common_prefix(names: list[str]) -> str:
    """The prefix every name shares, up to its last underscore: drawn dimmed so the rest stands out."""
    if len(names) < 2:
        return ""
    prefix = commonprefix(names)
    return prefix[:prefix.rfind("_") + 1]
