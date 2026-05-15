"""Probe that _open_and_convert actually caches.

Two calls on the same path must trigger only one radiospectra parse.
"""
from __future__ import annotations

import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest


@pytest.fixture
def fake_radiospectra_module(monkeypatch):
    fake = types.SimpleNamespace()
    class Spectrogram: ...
    class SpectrogramSequence: ...
    fake.Spectrogram = Spectrogram
    fake.SpectrogramSequence = SpectrogramSequence
    import sys
    monkeypatch.setitem(sys.modules, "radiospectra", fake)
    monkeypatch.setitem(sys.modules, "radiospectra.spectrogram", types.SimpleNamespace(
        Spectrogram=Spectrogram, SpectrogramSequence=SpectrogramSequence,
    ))
    return fake


def _make_spec(SpecCls):
    spec = SpecCls()
    t0 = datetime(2024, 5, 1, tzinfo=timezone.utc)
    spec.times = types.SimpleNamespace(
        unix=np.arange(4, dtype=np.float64) + t0.timestamp(),
        to_datetime=lambda: np.array([
            datetime(2024, 5, 1, 0, 0, i, tzinfo=timezone.utc) for i in range(4)
        ]),
    )
    freq_vals = np.array([1.0, 2.0, 4.0], dtype=np.float64)
    spec.frequencies = types.SimpleNamespace(
        to_value=lambda unit, _fv=freq_vals: _fv,
        unit="MHz",
    )
    spec.data = np.arange(4 * 3, dtype=np.float32).reshape((3, 4))
    spec.meta = {"instrument": "TEST"}
    return spec


def test_cache_hit_skips_radiospectra_parse(tmp_path, fake_radiospectra_module):
    """Two calls on the same file must call radiospectra.open_spectrogram
    only ONCE — the second call must come from Speasy's cache."""
    from sciqlop_radio import dock

    f = tmp_path / "probe.cdf"
    f.write_bytes(b"\x00" * 64)  # any non-empty payload — we mock the parser

    parse_count = {"n": 0}

    def fake_open(_path):
        parse_count["n"] += 1
        return _make_spec(fake_radiospectra_module.Spectrogram)

    with patch("sciqlop_radio.dock.open_spectrogram", fake_open):
        dock._cached_open_and_convert = None  # reset module-level cached factory
        v1 = dock._open_and_convert(f)
        v2 = dock._open_and_convert(f)

    assert v1 is not None and v2 is not None
    assert parse_count["n"] == 1, (
        f"Expected cache hit on second call; got {parse_count['n']} parses"
    )


def test_cache_miss_when_mtime_changes(tmp_path, fake_radiospectra_module):
    """Touching the file changes mtime → cache key changes → re-parse."""
    from sciqlop_radio import dock
    import os
    import time

    f = tmp_path / "probe.cdf"
    f.write_bytes(b"\x00" * 64)

    parse_count = {"n": 0}

    def fake_open(_path):
        parse_count["n"] += 1
        return _make_spec(fake_radiospectra_module.Spectrogram)

    with patch("sciqlop_radio.dock.open_spectrogram", fake_open):
        dock._cached_open_and_convert = None
        dock._open_and_convert(f)
        # Bump mtime by 2s (some filesystems have 1s resolution).
        t = time.time() + 2
        os.utime(f, (t, t))
        dock._open_and_convert(f)

    assert parse_count["n"] == 2, "Touched file must miss the cache and re-parse"
