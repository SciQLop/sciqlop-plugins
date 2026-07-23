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
    without a calibrated Speasy equivalent remain as continuous VPs. ILOFAR
    ships two files per timestamp (X/Y linear polarisation) so it needs two
    registry entries, not one whole-instrument entry."""
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES
    paths = {s.vp_path for s in CONTINUOUS_SOURCES}
    assert paths == {"radio/eovsa", "radio/ilofar/X", "radio/ilofar/Y"}


def test_ilofar_continuous_sources_filter_by_polarisation():
    """Each ILOFAR registry entry must scope to exactly one polarisation —
    otherwise both channels get merged into the same product (the bug this
    guards against: an X-pol image and a Y-pol image spliced together)."""
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES
    ilofar_sources = {s.vp_path: s for s in CONTINUOUS_SOURCES
                      if s.vp_path.startswith("radio/ilofar")}
    assert {s.channel_value for s in ilofar_sources.values()} == {"X", "Y"}
    assert all(s.channel_column == "Polarisation" for s in ilofar_sources.values())


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

    def vp_factory(path, cb, vptype, *, metadata, labels=None, out_of_process=False):
        captured.append((path, vptype, metadata, out_of_process))
        return path

    out = register_continuous_products(
        cache_dir=tmp_path,
        open_and_convert=lambda p: None,
        vp_factory=vp_factory,
    )
    assert out is not None
    assert len(captured) == len(CONTINUOUS_SOURCES)
    for (path, vptype, metadata, out_of_process), src in zip(captured, CONTINUOUS_SOURCES):
        assert path == src.vp_path
        assert vptype == "SPEC"
        assert metadata is src.static_meta
        assert out_of_process is True


def test_register_continuous_products_out_of_process_can_be_overridden(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    fake_vp_module = SimpleNamespace(
        VirtualProductType=SimpleNamespace(Spectrogram="SPEC"),
    )
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.virtual_products", fake_vp_module)

    from sciqlop_radio.continuous import register_continuous_products
    captured = []

    def vp_factory(path, cb, vptype, *, metadata, labels=None, out_of_process=False):
        captured.append(out_of_process)
        return path

    register_continuous_products(
        cache_dir=tmp_path,
        open_and_convert=lambda p: None,
        vp_factory=vp_factory,
        out_of_process=False,
    )
    assert captured and all(v is False for v in captured)


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


def test_ilofar_callback_never_fetches_both_polarisations(
        monkeypatch, tmp_path, speasy_variable_factory):
    """Real I-LOFAR mode 357 BST search results carry an X file and a Y file
    for the same timestamp. The X-polarisation VP's callback must fetch only
    the X row — fetching both and letting `_concat_spectrograms` merge them
    (same frequency grid, so nothing else catches it) is exactly the bug
    that spliced two channels into one spectrogram."""
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES
    from sciqlop_radio import continuous as C
    rows = [
        {"Observatory": "IE613", "Polarisation": "X",
         "url": "http://a/20250722_140037_bst_00X.dat"},
        {"Observatory": "IE613", "Polarisation": "Y",
         "url": "http://a/20250722_140037_bst_00Y.dat"},
    ]
    captured = {}
    monkeypatch.setattr(C, "_fido_search", lambda t0, t1, src: [dict(r) for r in rows])
    monkeypatch.setattr(C, "_fetch_paths",
                        lambda rws, cd: (captured.__setitem__("rows", list(rws)) or []))
    x_source = next(s for s in CONTINUOUS_SOURCES if s.vp_path == "radio/ilofar/X")
    cb = C._build_callback(x_source, tmp_path, lambda p: None)
    cb(0.0, 100.0)
    assert len(captured["rows"]) == 1
    assert captured["rows"][0]["Polarisation"] == "X"


def test_ilofar_stale_day_cache_without_polarisation_self_heals(
        monkeypatch, tmp_path):
    """Regression: the disk-backed day cache (`_fido_search_day_cached`) is
    keyed only by (search_signature, day) — it has no schema-compatibility
    check. Before the X/Y polarisation split, ILOFAR's ContinuousSource had
    no `channel_column`, so `_row_to_dict` cached rows *without* a
    "Polarisation" key under `sciqlop_radio/search/ILOFAR/<day>`. After the
    split, that exact stale cache entry (confirmed on a real machine's disk
    cache) still matches the new sources' cache key and their files are
    already on disk from prior use, so the old cache-hit path returned it
    unchanged — `_filter_rows_for_stream` then filtered out every row
    (`Polarisation` field missing) and every I-LOFAR VP went permanently
    empty. The day cache must detect a schema-incompatible hit and
    re-search instead of trusting stale field-incomplete rows."""
    from speasy.core.cache import add_item
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES, _search_cache_key
    from sciqlop_radio import continuous as C
    from datetime import datetime, timezone

    x_source = next(s for s in CONTINUOUS_SOURCES if s.vp_path == "radio/ilofar/X")
    day = datetime(2025, 7, 22, tzinfo=timezone.utc)
    stale_row = {
        "url": "https://data.lofar.ie/2025/07/22/bst/kbt/rcu357_1beam_datastream_fast/"
               "20250722_140037_bst_00X.dat",
        "Observatory": "",
        "Start Time": "2025-07-22 14:00:37.000",
    }
    add_item(_search_cache_key(x_source, day), [stale_row], 3600)
    (tmp_path / "20250722_140037_bst_00X.dat").write_bytes(b"\x00")

    fresh_row = dict(stale_row, Polarisation="X")
    monkeypatch.setattr(C, "_fido_search", lambda t0, t1, src: [dict(fresh_row)])

    rows = C._search_rows_for_window(
        datetime(2025, 7, 22, 14, 0, tzinfo=timezone.utc),
        datetime(2025, 7, 22, 15, 0, tzinfo=timezone.utc),
        x_source, tmp_path,
    )
    rows = C._filter_rows_for_stream(rows, x_source)
    assert len(rows) == 1, "stale pre-split cache entry must not poison the filter"
    assert rows[0]["Polarisation"] == "X"


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


def test_stream_callback_emits_tracing_zones_and_points_counter(
        monkeypatch, tmp_path, speasy_variable_factory):
    from sciqlop_radio import continuous as C
    from contextlib import contextmanager
    zone_calls = []
    counter_calls = []

    @contextmanager
    def fake_zone(name, cat="", **kwargs):
        zone_calls.append(name)
        yield

    monkeypatch.setattr(C, "zone", fake_zone)
    monkeypatch.setattr(C, "counter",
                        lambda name, value, cat="": counter_calls.append((name, value, cat)))
    v = speasy_variable_factory("2024-01-01T00:00:00", 2, 3)
    rows = [{"Observatory": "BIR", "ID": "01", "url": "http://a/x.fit.gz"}]
    monkeypatch.setattr(C, "_fido_search", lambda *a: [dict(r) for r in rows])
    monkeypatch.setattr(C, "_fetch_paths", lambda rws, cd: [tmp_path / "x.fit.gz"])

    out = C._build_callback(_ecallisto_source(), tmp_path, lambda p: v)(0.0, 100.0)

    assert out is not None
    for expected in ("sciqlop_radio.continuous.callback",
                     "sciqlop_radio.continuous.search",
                     "sciqlop_radio.continuous.fetch",
                     "sciqlop_radio.continuous.parse"):
        assert expected in zone_calls
    points_calls = [c for c in counter_calls if c[0] == "sciqlop_radio.continuous.points"]
    assert points_calls and points_calls[0][1] == out.values.size


def test_stream_callback_returns_none_on_empty_window(monkeypatch, tmp_path):
    from sciqlop_radio import continuous as C
    monkeypatch.setattr(C, "_fido_search", lambda *a: [])
    out = C._build_callback(_ecallisto_source(), tmp_path, lambda p: None)(0.0, 100.0)
    assert out is None


def _ecallisto_stream_cb(channel, tmp_path):
    from sciqlop_radio.continuous import make_stream_source, _build_callback
    from sciqlop_radio.dock import _open_and_convert
    from sciqlop_radio.streams import StreamIdentity
    ident = StreamIdentity(source_key="ecallisto", instrument="eCALLISTO",
                           station="BIR", channel=channel)
    src = make_stream_source(ident, freq_signature=None)
    return _build_callback(src, tmp_path, _open_and_convert)


@pytest.mark.live
def test_live_ecallisto_stream_returns_data(tmp_path):
    """Real Fido: a per-station+focus eCALLISTO stream over a known window returns
    a non-empty spectrogram. Confirms server-side net.Observatory + the callback
    chain end-to-end. BIR runs focus code 59 here. Network-gated; run with `-m live`."""
    from datetime import datetime, timezone
    t0 = datetime(2011, 6, 7, 6, 0, tzinfo=timezone.utc).timestamp()
    t1 = datetime(2011, 6, 7, 7, 0, tzinfo=timezone.utc).timestamp()
    out = _ecallisto_stream_cb("59", tmp_path)(t0, t1)
    assert out is not None
    assert out.values.shape[0] > 0
    assert out.values.shape[1] > 0


@pytest.mark.live
def test_live_ecallisto_focus_code_filter_excludes_other_receivers(tmp_path):
    """The focus-code guarantee against real data: BIR runs two receivers (59 and
    10) in this window. A stream for a focus code that doesn't exist (01) must
    return None even though the BIR search yields rows — proving the client-side
    focus filter never folds a different receiver into the stream."""
    from datetime import datetime, timezone
    t0 = datetime(2011, 6, 7, 6, 0, tzinfo=timezone.utc).timestamp()
    t1 = datetime(2011, 6, 7, 7, 0, tzinfo=timezone.utc).timestamp()
    assert _ecallisto_stream_cb("01", tmp_path)(t0, t1) is None

