"""Tests for the LOFAR virtual-product plumbing.

Pure pieces only: the network/zip path, the FITS parse, and the SciQLop
registration handshake. Anything that needs a real LOFAR FITS file is
covered by manual integration testing inside SciQLop.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest


@pytest.fixture
def sample_index_entries():
    return [
        {
            "url": "https://lpp.example/data/json_files/A_B000_SAP000.json",
            "filename": "A_B000_SAP000.json",
            "source": "L12345_B000_SAP000",
            "time_range": ["2024-05-14T16:30:00Z", "2024-05-14T17:30:00Z"],
        },
        {
            "url": "https://lpp.example/data/json_files/B_B000_SAP001.json",
            "filename": "B_B000_SAP001.json",
            "source": "L12345_B000_SAP001",
            "time_range": ["2024-05-14T17:30:00Z", "2024-05-14T18:30:00Z"],
        },
        {
            "url": "https://lpp.example/data/json_files/C_B001_SAP000.json",
            "filename": "C_B001_SAP000.json",
            "source": "L12345_B001_SAP000",
            "time_range": ["2024-05-14T16:30:00Z", "2024-05-14T17:30:00Z"],
        },
        # Malformed: missing time_range — must be skipped, not crash.
        {
            "url": "https://lpp.example/data/json_files/D.json",
            "filename": "D.json",
            "source": "L12345_B000_SAP000",
        },
    ]


@pytest.fixture
def written_index(tmp_path, sample_index_entries):
    p = tmp_path / "lofar_index.json"
    p.write_text(json.dumps(sample_index_entries))
    return p


# ---------------------------------------------------------------------------
# parse_index
# ---------------------------------------------------------------------------


def test_parse_index_drops_malformed_entries(sample_index_entries):
    from sciqlop_radio.lofar import parse_index
    out = parse_index(json.dumps(sample_index_entries))
    assert len(out) == 3
    assert {e.source for e in out} == {
        "L12345_B000_SAP000", "L12345_B000_SAP001", "L12345_B001_SAP000",
    }


def test_parse_index_treats_naive_timestamps_as_utc(sample_index_entries):
    from sciqlop_radio.lofar import parse_index
    sample_index_entries[0]["time_range"] = ["2024-05-14T16:30:00", "2024-05-14T17:30:00"]
    out = parse_index(json.dumps(sample_index_entries))
    assert out[0].t0.tzinfo is timezone.utc
    assert out[0].t0 == datetime(2024, 5, 14, 16, 30, tzinfo=timezone.utc)


def test_parse_index_rejects_non_list():
    from sciqlop_radio.lofar import parse_index
    with pytest.raises(ValueError):
        parse_index(json.dumps({"not": "a list"}))


# ---------------------------------------------------------------------------
# Range filter + URL construction
# ---------------------------------------------------------------------------


def test_entries_in_range_filters_by_beam_and_sap(monkeypatch, tmp_path, written_index, sample_index_entries):
    from sciqlop_radio import lofar
    monkeypatch.setattr(lofar, "_download_index", lambda cache_dir: written_index)
    lofar._load_index_cached.cache_clear()
    lofar._entries_for.cache_clear()

    t0 = datetime(2024, 5, 14, 16, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 5, 14, 17, 0, tzinfo=timezone.utc)
    hits = lofar._entries_in_range(tmp_path, t0, t1, "B000", "SAP000")
    assert [h.filename for h in hits] == ["A_B000_SAP000.json"]


def test_entries_in_range_intersects_time(monkeypatch, tmp_path, written_index):
    from sciqlop_radio import lofar
    monkeypatch.setattr(lofar, "_download_index", lambda cache_dir: written_index)
    lofar._load_index_cached.cache_clear()
    lofar._entries_for.cache_clear()

    # Window touching both back-to-back B000 files
    t0 = datetime(2024, 5, 14, 17, 0, tzinfo=timezone.utc)
    t1 = datetime(2024, 5, 14, 18, 0, tzinfo=timezone.utc)
    hits = lofar._entries_in_range(tmp_path, t0, t1, "B000", "SAP000")
    assert [h.filename for h in hits] == ["A_B000_SAP000.json"]

    hits = lofar._entries_in_range(tmp_path, t0, t1, "B000", "SAP001")
    assert [h.filename for h in hits] == ["B_B000_SAP001.json"]


def test_entries_in_range_empty_when_no_intersection(monkeypatch, tmp_path, written_index):
    from sciqlop_radio import lofar
    monkeypatch.setattr(lofar, "_download_index", lambda cache_dir: written_index)
    lofar._load_index_cached.cache_clear()
    lofar._entries_for.cache_clear()

    t0 = datetime(2030, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2030, 1, 2, tzinfo=timezone.utc)
    assert lofar._entries_in_range(tmp_path, t0, t1, "B000", "SAP000") == []


def test_fits_url_swaps_json_for_dynamic_spectra(sample_index_entries):
    from sciqlop_radio.lofar import _fits_url_for_entry, parse_index
    entries = parse_index(json.dumps(sample_index_entries))
    url = _fits_url_for_entry(entries[0])
    assert url == "https://lpp.example/data/dynamic_spectra/A_B000_SAP000.fits"


def test_fits_url_passes_through_when_index_already_points_at_data():
    from sciqlop_radio.lofar import _Entry, _fits_url_for_entry
    entry = _Entry(
        url="https://lpp.example/dynamic_spectra/X.fits",
        t0=datetime(2024, 1, 1, tzinfo=timezone.utc),
        t1=datetime(2024, 1, 2, tzinfo=timezone.utc),
        source="L_B000_SAP000",
        filename="X.fits",
    )
    assert _fits_url_for_entry(entry) == "https://lpp.example/dynamic_spectra/X.fits"


# ---------------------------------------------------------------------------
# Index download (zip extraction)
# ---------------------------------------------------------------------------


def test_download_index_extracts_json_atomically(monkeypatch, tmp_path, sample_index_entries):
    from sciqlop_radio import lofar

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("index.json", json.dumps(sample_index_entries))

    class _Resp:
        content = buf.getvalue()
        def raise_for_status(self):
            pass

    calls = {"n": 0}

    def fake_get(url, timeout=None):
        calls["n"] += 1
        assert url == lofar.LOFAR_INDEX_URL
        return _Resp()

    monkeypatch.setattr("requests.get", fake_get)
    out = lofar._download_index(tmp_path)
    assert out.exists()
    assert json.loads(out.read_text()) == sample_index_entries

    # Second call must hit the on-disk cache — no second network call.
    out2 = lofar._download_index(tmp_path)
    assert out2 == out
    assert calls["n"] == 1


def test_download_index_raises_when_zip_has_no_json(monkeypatch, tmp_path):
    from sciqlop_radio import lofar

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("README.txt", "no json here")

    class _Resp:
        content = buf.getvalue()
        def raise_for_status(self):
            pass

    monkeypatch.setattr("requests.get", lambda url, timeout=None: _Resp())
    with pytest.raises(RuntimeError, match="no .json file"):
        lofar._download_index(tmp_path)


# ---------------------------------------------------------------------------
# lofar_time conversion
# ---------------------------------------------------------------------------


def test_lofar_time_modern_epoch_days_since_1970():
    from sciqlop_radio.lofar import _lofar_time
    days = 19858  # arbitrary modern day-count
    expected_day = np.datetime64("1970-01-01") + np.timedelta64(days, "D")
    t = _lofar_time(np.array([float(days), days + 1.0 / 86400.0]))
    assert t.dtype == np.dtype("datetime64[ns]")
    assert t[0] == expected_day
    # Second sample is ~1 second later. Float64 can't represent
    # (19858 + 1/86400) exactly, so we tolerate sub-microsecond drift.
    delta_ns = (t[1] - t[0]).astype("timedelta64[ns]").astype("int64")
    assert abs(delta_ns - 1_000_000_000) < 1_000


def test_lofar_time_julian_like_epoch_days_since_0000():
    from sciqlop_radio.lofar import _lofar_time
    # Pick a value clearly > 1e5 so the heuristic picks the 0000-12-31 epoch.
    # That epoch + 730120 days ≈ 2000-01-01.
    base = np.datetime64("0000-12-31")
    days = 730120
    t = _lofar_time(np.array([float(days)]))
    assert t[0] == base + np.timedelta64(days, "D")


# ---------------------------------------------------------------------------
# Registration handshake
# ---------------------------------------------------------------------------


def test_register_lofar_product_returns_none_when_sciqlop_missing(monkeypatch, tmp_path):
    import sys
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.virtual_products", None)
    from sciqlop_radio.lofar import register_lofar_product
    assert register_lofar_product(cache_dir=tmp_path) is None


def test_register_lofar_product_passes_metadata_and_path(monkeypatch, tmp_path):
    import sys
    from types import SimpleNamespace
    fake_vp_module = SimpleNamespace(
        VirtualProductType=SimpleNamespace(Spectrogram="SPEC"),
    )
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.virtual_products", fake_vp_module)

    from sciqlop_radio.lofar import (
        LOFAR_META, LOFAR_VP_PATH, register_lofar_product,
    )
    captured = {}

    def vp_factory(path, cb, vptype, *, metadata, labels=None):
        captured["path"] = path
        captured["vptype"] = vptype
        captured["metadata"] = metadata
        captured["cb"] = cb
        return "VP-OBJECT"

    reg = register_lofar_product(cache_dir=tmp_path, vp_factory=vp_factory)
    assert reg is not None
    assert reg.vp == "VP-OBJECT"
    assert captured["path"] == LOFAR_VP_PATH
    assert captured["vptype"] == "SPEC"
    assert captured["metadata"] is LOFAR_META
    assert callable(captured["cb"])


def test_callback_signature_resolves_under_eval_str(tmp_path):
    """Regression: SciQLop's EasyProvider calls `inspect.signature(callback,
    eval_str=True)`, which re-evaluates the stringified `Annotated[int, Knob(...)]`
    annotations in the callback's module globals. If `Knob` isn't bound at
    module level, this raises `NameError: name 'Knob' is not defined` at
    VP-registration time (seen in production)."""
    import inspect
    from sciqlop_radio.lofar import _build_callback
    cb = _build_callback(tmp_path)
    sig = inspect.signature(cb, eval_str=True)
    assert {"start", "stop", "beam", "sap"} <= set(sig.parameters)


def test_lofar_meta_carries_plot_hints_essentials():
    from sciqlop_radio.lofar import LOFAR_META
    assert LOFAR_META["DISPLAY_TYPE"] == "spectrogram"
    assert LOFAR_META["SCALETYP"] == "log"
    assert "description" in LOFAR_META
    assert LOFAR_META["provider"] == "LOFAR"


# ---------------------------------------------------------------------------
# Callback wiring
# ---------------------------------------------------------------------------


def test_callback_returns_none_when_index_empty(monkeypatch, tmp_path, written_index):
    from sciqlop_radio import lofar
    monkeypatch.setattr(lofar, "_download_index", lambda cache_dir: written_index)
    lofar._load_index_cached.cache_clear()
    lofar._entries_for.cache_clear()

    cb = lofar._build_callback(tmp_path)
    # Window that no index entry covers.
    t0 = datetime(2030, 1, 1, tzinfo=timezone.utc).timestamp()
    t1 = datetime(2030, 1, 2, tzinfo=timezone.utc).timestamp()
    assert cb(t0, t1) is None


def test_callback_returns_none_when_read_returns_none(monkeypatch, tmp_path, written_index):
    """Every FITS-read returns None (parse failure / wrong shape) → callback
    short-circuits to None, doesn't try to merge an empty list."""
    from sciqlop_radio import lofar
    monkeypatch.setattr(lofar, "_download_index", lambda cache_dir: written_index)
    monkeypatch.setattr(lofar, "_read_lofar", lambda url: None)
    lofar._load_index_cached.cache_clear()
    lofar._entries_for.cache_clear()

    cb = lofar._build_callback(tmp_path)
    t0 = datetime(2024, 5, 14, 16, 0, tzinfo=timezone.utc).timestamp()
    t1 = datetime(2024, 5, 14, 17, 0, tzinfo=timezone.utc).timestamp()
    assert cb(t0, t1) is None
