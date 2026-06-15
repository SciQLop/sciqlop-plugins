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


# ---------------------------------------------------------------------------
# static_meta + vp_factory injection
# ---------------------------------------------------------------------------


def test_continuous_sources_have_minimal_static_meta():
    """Both continuous sources must carry the minimum needed for plot hints:
    DISPLAY_TYPE=spectrogram, SCALETYP=log, a description, a provider tag."""
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES
    for src in CONTINUOUS_SOURCES:
        meta = src.static_meta
        assert meta.get("DISPLAY_TYPE") == "spectrogram", src.vp_path
        assert meta.get("SCALETYP") == "log", src.vp_path
        assert "description" in meta, src.vp_path
        assert meta.get("provider") == "radiospectra", src.vp_path


def test_register_continuous_products_passes_static_meta_to_factory(tmp_path, monkeypatch):
    """register_continuous_products must forward each source's static_meta
    through the injected vp_factory."""
    import sys
    from types import SimpleNamespace
    fake_vp_module = SimpleNamespace(
        VirtualProductType=SimpleNamespace(Spectrogram="SPEC"),
    )
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.virtual_products", fake_vp_module)

    from sciqlop_radio.continuous import register_continuous_products, CONTINUOUS_SOURCES
    captured = []

    def vp_factory(path, cb, vptype, *, metadata, labels=None):
        captured.append((path, vptype, metadata))
        return path

    out = register_continuous_products(
        cache_dir=tmp_path,
        open_and_convert=lambda p: None,
        vp_factory=vp_factory,
    )
    assert out is not None
    assert len(captured) == len(CONTINUOUS_SOURCES)
    for (path, vptype, metadata), src in zip(captured, CONTINUOUS_SOURCES):
        assert path == src.vp_path
        assert vptype == "SPEC"
        assert metadata is src.static_meta


# ---------------------------------------------------------------------------
# streaming callback: station/channel/frequency filters + no cap
# ---------------------------------------------------------------------------


def _ecallisto_source(**over):
    from sciqlop_radio.continuous import ContinuousSource
    base = dict(vp_path="radio/ecallisto/BIR/01", label="BIR/01",
                attrs_factory=lambda: [], station="BIR",
                channel_column="ID", channel_value="01")
    base.update(over)
    return ContinuousSource(**base)


def test_stream_callback_filters_rows_by_station_and_channel(monkeypatch, tmp_path):
    from sciqlop_radio import continuous as C
    rows = [
        {"Observatory": "BIR", "ID": "01", "url": "http://a/BIR_x_01.fit.gz"},
        {"Observatory": "BIR", "ID": "02", "url": "http://a/BIR_x_02.fit.gz"},
        {"Observatory": "ALMATY", "ID": "01", "url": "http://a/ALMATY_x_01.fit.gz"},
    ]
    captured = {}
    monkeypatch.setattr(C, "_fido_search", lambda t0, t1, src: [dict(r) for r in rows])
    monkeypatch.setattr(C, "_fetch_paths",
                        lambda rws, cd: (captured.__setitem__("rows", list(rws)) or []))
    cb = C._build_callback(_ecallisto_source(), tmp_path, lambda p: None)
    cb(0.0, 100.0)
    assert len(captured["rows"]) == 1
    assert captured["rows"][0]["Observatory"] == "BIR"
    assert captured["rows"][0]["ID"] == "01"


def test_stream_callback_drops_files_off_frequency_signature(
        monkeypatch, tmp_path, speasy_variable_factory):
    from sciqlop_radio import continuous as C
    from sciqlop_radio.plot import frequency_signature
    v_good = speasy_variable_factory("2024-01-01T00:00:00", 3, 4)
    v_bad = speasy_variable_factory("2024-01-01T00:01:00", 3, 5)
    sig = frequency_signature(v_good)
    rows = [{"Observatory": "BIR", "ID": "01", "url": "http://a/g.fit.gz"},
            {"Observatory": "BIR", "ID": "01", "url": "http://a/b.fit.gz"}]
    monkeypatch.setattr(C, "_fido_search", lambda *a: [dict(r) for r in rows])
    monkeypatch.setattr(C, "_fetch_paths",
                        lambda rws, cd: [tmp_path / "g.fit.gz", tmp_path / "b.fit.gz"])
    mapping = {"g.fit.gz": v_good, "b.fit.gz": v_bad}
    src = _ecallisto_source(freq_signature=sig)
    out = C._build_callback(src, tmp_path, lambda p: mapping[p.name])(0.0, 100.0)
    assert out is not None
    assert out.values.shape[1] == 4  # only the matching-grid file survives


def test_stream_callback_has_no_file_cap(monkeypatch, tmp_path, speasy_variable_factory):
    from sciqlop_radio import continuous as C
    v = speasy_variable_factory("2024-01-01T00:00:00", 2, 3)
    rows = [{"Observatory": "BIR", "ID": "01", "url": f"http://a/{i}.fit.gz"}
            for i in range(50)]
    monkeypatch.setattr(C, "_fido_search", lambda *a: [dict(r) for r in rows])
    monkeypatch.setattr(C, "_fetch_paths",
                        lambda rws, cd: [tmp_path / f"{i}.fit.gz" for i in range(len(rws))])
    out = C._build_callback(_ecallisto_source(), tmp_path, lambda p: v)(0.0, 100.0)
    assert out is not None
    assert out.values.shape[0] == 50 * 2  # all 50 files concatenated, not capped


def test_stream_callback_returns_none_on_empty_window(monkeypatch, tmp_path):
    from sciqlop_radio import continuous as C
    monkeypatch.setattr(C, "_fido_search", lambda *a: [])
    out = C._build_callback(_ecallisto_source(), tmp_path, lambda p: None)(0.0, 100.0)
    assert out is None

