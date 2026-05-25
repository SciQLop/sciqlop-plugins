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


def test_resolve_index_returns_index_when_found():
    from sciqlop_radio.catalog import _resolve_index
    sentinel = object()
    sp = _fake_speasy({"amda": {"wnd_swaves_rad1": sentinel}})
    assert _resolve_index("amda/wnd_swaves_rad1", sp) is sentinel


def test_resolve_index_returns_none_when_uid_missing_or_provider_absent():
    from sciqlop_radio.catalog import _resolve_index
    sp = _fake_speasy({"amda": {"other": object()}})
    assert _resolve_index("amda/wnd_swaves_rad1", sp) is None
    assert _resolve_index("cda/anything", sp) is None


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


def _fake_vp_types():
    return SimpleNamespace(
        Spectrogram="SPEC", Vector="VEC", Scalar="SCA", MultiComponent="MC"
    )


def test_register_entries_registers_resolvable_skips_unresolvable():
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {"ok": object()}})
    entries = [
        CuratedRadioProduct(path="Wind/WAVES/RAD1", speasy_id="amda/ok"),
        CuratedRadioProduct(path="Gone/Product", speasy_id="amda/missing"),
    ]
    created = []

    def create_vp(path, cb, vptype, **kw):
        created.append((path, vptype, kw))
        return f"VP[{path}]"

    reg = _register_entries(entries, create_vp, _fake_vp_types(), sp)
    assert [c[0] for c in created] == ["radio/Wind/WAVES/RAD1"]
    assert created[0][1] == "SPEC"
    assert reg.vps == {"radio/Wind/WAVES/RAD1": "VP[radio/Wind/WAVES/RAD1]"}


def test_register_entries_passes_labels_for_non_spectrogram():
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {"v": object()}})
    entries = [
        CuratedRadioProduct(
            path="X/Vec", speasy_id="amda/v", type="vector", labels=["a", "b", "c"]
        )
    ]
    created = []

    def create_vp(path, cb, vptype, **kw):
        created.append((path, vptype, kw))
        return path

    _register_entries(entries, create_vp, _fake_vp_types(), sp)
    assert created[0][1] == "VEC"
    assert created[0][2] == {"labels": ["a", "b", "c"]}


def test_register_entries_continues_when_create_vp_raises():
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {"a": object(), "b": object()}})
    entries = [
        CuratedRadioProduct(path="One", speasy_id="amda/a"),
        CuratedRadioProduct(path="Two", speasy_id="amda/b"),
    ]

    def create_vp(path, cb, vptype, **kw):
        if path == "radio/One":
            raise RuntimeError("boom")
        return path

    reg = _register_entries(entries, create_vp, _fake_vp_types(), sp)
    assert list(reg.vps) == ["radio/Two"]


def test_register_catalog_products_returns_none_when_sciqlop_missing(tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.virtual_products", None)
    f = tmp_path / "cat.yaml"
    f.write_text("- path: A/B\n  speasy_id: amda/x\n")
    from sciqlop_radio.catalog import register_catalog_products
    assert register_catalog_products(f) is None


def test_register_catalog_products_empty_catalog_returns_empty_registration(tmp_path):
    from sciqlop_radio.catalog import register_catalog_products, CatalogRegistration
    reg = register_catalog_products(tmp_path / "missing.yaml")
    assert isinstance(reg, CatalogRegistration)
    assert reg.vps == {}


def test_shipped_catalog_loads_and_validates():
    """The bundled radio_catalog.yaml must parse and every entry must pass
    schema validation strictly (load_catalog skips invalid entries — so we
    re-validate the raw file strictly here to catch typos before release).

    Also enforces the curation rule: no entry may duplicate the continuous
    VP paths registered by `continuous.py`."""
    from pathlib import Path
    import yaml
    import sciqlop_radio
    from sciqlop_radio.catalog import CuratedRadioProduct

    f = Path(sciqlop_radio.__file__).parent / "radio_catalog.yaml"
    raw = yaml.safe_load(f.read_text()) or []
    assert isinstance(raw, list)
    validated = [CuratedRadioProduct(**i) for i in raw]   # raises on any invalid entry

    from sciqlop_radio.continuous import CONTINUOUS_SOURCES
    cont = {s.vp_path for s in CONTINUOUS_SOURCES}
    paths = {f"radio/{e.path}" for e in validated}
    assert paths.isdisjoint(cont), f"catalog duplicates continuous VPs: {paths & cont}"
