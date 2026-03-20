import numpy as np
import pytest
from cdf_workbench.quality import analyze_quality, QualityReport


def test_quality_report_perfect_data():
    """No fill values, no out-of-range, no gaps."""
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    epochs = np.arange(
        np.datetime64("2020-01-01"),
        np.datetime64("2020-01-01T00:00:05"),
        np.timedelta64(1, "s"),
    )
    report = analyze_quality(
        values=values,
        epochs=epochs,
        fill_value=-1e31,
        valid_min=0.0,
        valid_max=100.0,
    )
    assert report.fill_percentage == 0.0
    assert report.out_of_range_percentage == 0.0
    assert report.epoch_gaps == 0
    assert report.valid_percentage == 100.0


def test_quality_report_with_fill_values():
    values = np.array([1.0, -1e31, 3.0, -1e31, 5.0])
    report = analyze_quality(
        values=values, fill_value=-1e31,
    )
    assert report.fill_percentage == pytest.approx(40.0)


def test_quality_report_with_out_of_range():
    values = np.array([1.0, 2.0, 150.0, 4.0, -5.0])
    report = analyze_quality(
        values=values,
        fill_value=-1e31,
        valid_min=0.0,
        valid_max=100.0,
    )
    assert report.out_of_range_percentage == pytest.approx(40.0)


def test_quality_report_epoch_gaps():
    # Regular 1-second cadence with a 10-second gap in the middle
    epochs = np.array([0, 1, 2, 3, 13, 14, 15], dtype="datetime64[s]")
    report = analyze_quality(
        values=np.ones(7),
        epochs=epochs,
    )
    assert report.epoch_gaps == 1


def test_quality_report_no_metadata():
    """When no fill/valid range provided, only basic stats."""
    values = np.array([1.0, 2.0, 3.0])
    report = analyze_quality(values=values)
    assert report.fill_percentage == 0.0
    assert report.out_of_range_percentage == 0.0


def test_quality_report_multidimensional():
    """2D array (e.g. vector field) — quality computed over all elements."""
    values = np.array([[1.0, 2.0], [-1e31, 3.0], [4.0, -1e31]])
    report = analyze_quality(values=values, fill_value=-1e31)
    assert report.fill_percentage == pytest.approx(100.0 * 2 / 6)
