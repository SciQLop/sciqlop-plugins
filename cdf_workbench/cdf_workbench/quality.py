from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class QualityReport:
    fill_percentage: float
    out_of_range_percentage: float
    epoch_gaps: int
    total_points: int

    @property
    def valid_percentage(self) -> float:
        bad = self.fill_percentage + self.out_of_range_percentage
        return max(0.0, 100.0 - bad)


def fill_mask(values: np.ndarray, fill_value) -> np.ndarray:
    """Where values equal FILLVAL, compared in the data's own type: a float32 file stores
    -1e31 as -9.9999998e30. A FILLVAL that type can't hold (NaN for integers, 1e300 for
    float32) matches nothing. A NaN FILLVAL matches NaN values."""
    if fill_value is None:
        return np.zeros(values.shape, dtype=bool)
    fill = np.float64(fill_value)
    if np.isnan(fill):
        return np.isnan(values) if values.dtype.kind == "f" else np.zeros(values.shape, dtype=bool)
    with np.errstate(over="ignore", invalid="ignore"):
        typed = fill.astype(values.dtype)
    if values.dtype.kind == "f":
        holds = bool(np.isfinite(typed)) == bool(np.isfinite(fill))
    else:
        holds = bool(np.isfinite(fill)) and float(typed) == float(fill)
    return values == typed if holds else np.zeros(values.shape, dtype=bool)


def analyze_quality(
    values: np.ndarray,
    epochs: np.ndarray | None = None,
    fill_value: float | None = None,
    valid_min: float | None = None,
    valid_max: float | None = None,
) -> QualityReport:
    total = values.size
    if total == 0:
        return QualityReport(0.0, 0.0, 0, 0)

    flat = values.ravel()

    is_fill = fill_mask(flat, fill_value)
    fill_count = int(np.sum(is_fill))

    oor_count = 0
    if valid_min is not None or valid_max is not None:
        non_fill = flat[~is_fill]
        if valid_min is not None:
            oor_count += int(np.sum(non_fill < valid_min))
        if valid_max is not None:
            oor_count += int(np.sum(non_fill > valid_max))

    gap_count = _count_epoch_gaps(epochs) if epochs is not None else 0

    return QualityReport(
        fill_percentage=100.0 * fill_count / total,
        out_of_range_percentage=100.0 * oor_count / total,
        epoch_gaps=gap_count,
        total_points=total,
    )


def _count_epoch_gaps(epochs: np.ndarray) -> int:
    if len(epochs) < 3:
        return 0
    diffs = np.diff(epochs.astype("int64"))
    median_diff = np.median(diffs)
    if median_diff == 0:
        return 0
    # A gap is any interval > 3x the median cadence
    return int(np.sum(diffs > 3 * median_diff))
