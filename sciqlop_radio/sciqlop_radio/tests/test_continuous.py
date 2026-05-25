"""Tests for the continuous-product plumbing.

We only test the pure pieces: the concat helper and the source registry.
Anything that touches Fido is integration-tested manually (the live test
marker on test_fetch covers the search path; the continuous callback
just chains pieces we test elsewhere).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest


@pytest.fixture
def speasy_variable_factory():
    from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
    from speasy.products.variable import SpeasyVariable

    def _make(t0_iso: str, n_time: int, n_freq: int, freq=None):
        t0 = np.datetime64(t0_iso, "ns")
        step_ns = 1_000_000_000  # 1s
        times = (t0.astype("int64") + np.arange(n_time) * step_ns).astype("datetime64[ns]")
        if freq is None:
            freq = np.array([10.0 * (i + 1) for i in range(n_freq)], dtype=np.float64)
        time_axis = VariableTimeAxis(values=times)
        freq_axis = VariableAxis(name="frequency", values=freq, meta={"UNITS": "Hz"})
        data = np.arange(n_time * n_freq, dtype=np.float64).reshape((n_time, n_freq))
        values = DataContainer(values=data, meta={"UNITS": "dB"}, name="TEST")
        return SpeasyVariable(axes=[time_axis, freq_axis], values=values, columns=["TEST"])

    return _make


def test_continuous_sources_registry_covers_known_channels():
    """PSP/RFS used to live here but is now served via the curated catalog
    (cda L3 PSD flux/SFU); only ground-based / mission-specific receivers
    without a calibrated Speasy equivalent remain as continuous VPs."""
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES
    paths = {s.vp_path for s in CONTINUOUS_SOURCES}
    assert paths == {"radio/eovsa", "radio/ilofar"}


def test_concat_returns_single_variable_unchanged(speasy_variable_factory):
    from sciqlop_radio.continuous import _concat_spectrograms
    v = speasy_variable_factory("2024-01-01T00:00:00", 5, 3)
    out = _concat_spectrograms([v])
    assert out is v


def test_concat_concatenates_along_time(speasy_variable_factory):
    from sciqlop_radio.continuous import _concat_spectrograms
    v1 = speasy_variable_factory("2024-01-01T00:00:00", 5, 3)
    v2 = speasy_variable_factory("2024-01-01T00:01:00", 4, 3)
    out = _concat_spectrograms([v2, v1])  # out-of-order input — must sort
    assert out.values.shape == (9, 3)
    t = out.time.astype("datetime64[ns]").astype("int64")
    assert np.all(np.diff(t) > 0), "concat must be time-monotonic"


def test_concat_drops_mismatched_frequency_grid(speasy_variable_factory):
    from sciqlop_radio.continuous import _concat_spectrograms
    v1 = speasy_variable_factory("2024-01-01T00:00:00", 5, 3)
    v_bad = speasy_variable_factory("2024-01-01T00:01:00", 4, 5)  # 5 freqs vs 3
    out = _concat_spectrograms([v1, v_bad])
    assert out.values.shape == (5, 3), "mismatched grid should be dropped"


def test_concat_returns_none_for_empty_input():
    from sciqlop_radio.continuous import _concat_spectrograms
    assert _concat_spectrograms([]) is None


def test_register_continuous_products_returns_none_when_sciqlop_missing(monkeypatch, tmp_path):
    """Headless tests don't have SciQLop.user_api; registration should
    short-circuit, not crash."""
    import sys
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.virtual_products", None)
    from sciqlop_radio.continuous import register_continuous_products
    out = register_continuous_products(
        cache_dir=tmp_path,
        open_and_convert=lambda p: None,
    )
    assert out is None
