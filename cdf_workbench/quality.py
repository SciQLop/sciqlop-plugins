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

    fill_count = 0
    if fill_value is not None:
        fill_count = int(np.sum(flat == fill_value))

    oor_count = 0
    if valid_min is not None or valid_max is not None:
        non_fill = flat if fill_value is None else flat[flat != fill_value]
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
