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



from types import SimpleNamespace


def _fake_speasy(parameters_by_provider, get_data_return="VAR"):
    """SimpleNamespace mimicking the bits of `speasy` the catalog touches:
    `.inventories.flat_inventories.<provider>.parameters` (a dict) and
    `.get_data(id, t0, t1)`."""
    providers = {
        prov: SimpleNamespace(parameters=params)
        for prov, params in parameters_by_provider.items()
    }
    flat = SimpleNamespace(**providers)
    calls = []

    def get_data(pid, t0, t1):
        calls.append((pid, t0, t1))
        return get_data_return

    sp = SimpleNamespace(
        inventories=SimpleNamespace(flat_inventories=flat),
        get_data=get_data,
    )
    sp.calls = calls
    return sp


def test_resolves_true_when_uid_in_inventory():
    from sciqlop_radio.catalog import _resolves
    sp = _fake_speasy({"amda": {"wnd_swaves_rad1": object()}})
    assert _resolves("amda/wnd_swaves_rad1", sp) is True


def test_resolves_false_when_uid_missing_or_provider_absent():
    from sciqlop_radio.catalog import _resolves
    sp = _fake_speasy({"amda": {"other": object()}})
    assert _resolves("amda/wnd_swaves_rad1", sp) is False
    assert _resolves("cda/anything", sp) is False


def test_callback_fetches_via_speasy_get_data():
    from sciqlop_radio.catalog import CuratedRadioProduct, _build_callback
    sp = _fake_speasy({}, get_data_return="SPECVAR")
    e = CuratedRadioProduct(path="A/B", speasy_id="amda/x")
    cb = _build_callback(e, sp)
    out = cb(1_700_000_000.0, 1_700_000_900.0)
    assert out == "SPECVAR"
    assert sp.calls and sp.calls[0][0] == "amda/x"


def test_callback_swallows_get_data_error_returns_none():
    from sciqlop_radio.catalog import CuratedRadioProduct, _build_callback

    def boom(pid, t0, t1):
        raise RuntimeError("upstream down")

    sp = SimpleNamespace(get_data=boom)
    e = CuratedRadioProduct(path="A/B", speasy_id="amda/x")
    cb = _build_callback(e, sp)
    assert cb(1_700_000_000.0, 1_700_000_900.0) is None
