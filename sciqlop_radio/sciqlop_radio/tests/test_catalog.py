"""Tests for the curated Speasy radio-product catalog."""
from __future__ import annotations

import pytest


def test_valid_entry_defaults():
    from sciqlop_radio.catalog import CuratedRadioProduct
    e = CuratedRadioProduct(path="Wind/WAVES/RAD1", speasy_id="amda/wnd_swaves_rad1")
    assert e.path == "Wind/WAVES/RAD1"
    assert e.type == "spectrogram"
    assert e.label == "Wind/WAVES/RAD1"   # defaults to path
    assert e.labels is None


def test_path_is_stripped_of_slashes():
    from sciqlop_radio.catalog import CuratedRadioProduct
    e = CuratedRadioProduct(path="/Wind/WAVES/RAD1/", speasy_id="amda/x")
    assert e.path == "Wind/WAVES/RAD1"


def test_blank_path_rejected():
    from sciqlop_radio.catalog import CuratedRadioProduct
    with pytest.raises(ValueError):
        CuratedRadioProduct(path="  /  ", speasy_id="amda/x")


@pytest.mark.parametrize("bad", ["noslash", "amda/", "/uid", "  "])
def test_bad_speasy_id_rejected(bad):
    from sciqlop_radio.catalog import CuratedRadioProduct
    with pytest.raises(ValueError):
        CuratedRadioProduct(path="A/B", speasy_id=bad)


def test_speasy_id_inner_whitespace_is_canonicalized():
    from sciqlop_radio.catalog import CuratedRadioProduct
    e = CuratedRadioProduct(path="A/B", speasy_id="  amda /  wnd_swaves_rad1  ")
    assert e.speasy_id == "amda/wnd_swaves_rad1"


def test_labels_required_for_non_spectrogram():
    from sciqlop_radio.catalog import CuratedRadioProduct
    with pytest.raises(ValueError):
        CuratedRadioProduct(path="A/B", speasy_id="amda/x", type="vector")
    ok = CuratedRadioProduct(
        path="A/B", speasy_id="amda/x", type="vector", labels=["x", "y", "z"]
    )
    assert ok.labels == ["x", "y", "z"]


def test_load_catalog_parses_valid_yaml(tmp_path):
    from sciqlop_radio.catalog import load_catalog
    f = tmp_path / "cat.yaml"
    f.write_text(
        "- path: Wind/WAVES/RAD1\n"
        "  speasy_id: amda/wnd_swaves_rad1\n"
        "- path: STEREO-A/SWAVES/HFR\n"
        "  speasy_id: cda/STA_L3_WAV_HFR/avg_intens_ahead\n"
    )
    entries = load_catalog(f)
    assert [e.path for e in entries] == ["Wind/WAVES/RAD1", "STEREO-A/SWAVES/HFR"]


def test_load_catalog_skips_malformed_entry_keeps_rest(tmp_path):
    from sciqlop_radio.catalog import load_catalog
    f = tmp_path / "cat.yaml"
    f.write_text(
        "- path: Good/One\n"
        "  speasy_id: amda/ok\n"
        "- path: Bad/One\n"
        "  speasy_id: missing_slash\n"
    )
    entries = load_catalog(f)
    assert [e.path for e in entries] == ["Good/One"]


def test_load_catalog_missing_file_returns_empty(tmp_path):
    from sciqlop_radio.catalog import load_catalog
    assert load_catalog(tmp_path / "nope.yaml") == []


def test_load_catalog_non_list_returns_empty(tmp_path):
    from sciqlop_radio.catalog import load_catalog
    f = tmp_path / "cat.yaml"
    f.write_text("key: value\n")
    assert load_catalog(f) == []
