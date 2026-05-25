"""Tests for sciqlop_radio.hints — Speasy-index metadata extraction,
RichEasy* plot-hints overrides, and the make_rich_vp factory."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _fake_index(attrs: dict, *, provider="amda", uid="some_uid"):
    """Build a fake Speasy ParameterIndex: attrs land in __dict__, plus
    spz_uid() / spz_provider() methods returning the supplied strings."""
    ns = SimpleNamespace(**attrs)
    ns.spz_uid = lambda: uid
    ns.spz_provider = lambda: provider
    return ns


def test_extract_keeps_primitive_attributes():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({
        "UNITS": "dB",
        "LABLAXIS": "PSD",
        "SCALETYP": "log",
        "FILLVAL": -1e31,
        "DEPEND_0": "Epoch",
        "DEPEND_1": "frequency",
        "VAR_NOTES": "Calibrated L3 power spectral density",
    })
    meta = extract_speasy_index_meta(idx)
    assert meta["UNITS"] == "dB"
    assert meta["LABLAXIS"] == "PSD"
    assert meta["SCALETYP"] == "log"
    assert meta["FILLVAL"] == -1e31
    assert meta["DEPEND_0"] == "Epoch"
    assert meta["DEPEND_1"] == "frequency"
    assert meta["VAR_NOTES"].startswith("Calibrated")


def test_extract_keeps_lists_of_primitives():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({
        "LABL_PTR_1": ["x", "y", "z"],
        "VALIDMIN": [-100.0, -100.0, -100.0],
    })
    meta = extract_speasy_index_meta(idx)
    assert meta["LABL_PTR_1"] == ["x", "y", "z"]
    assert meta["VALIDMIN"] == [-100.0, -100.0, -100.0]


def test_extract_drops_dicts_callables_and_underscored():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({
        "UNITS": "dB",
        "nested_dict": {"a": 1},          # filtered (dict)
        "method_attr": lambda: None,      # filtered (callable)
        "_private": "hidden",             # filtered (underscore)
    })
    meta = extract_speasy_index_meta(idx)
    assert "UNITS" in meta
    assert "nested_dict" not in meta
    assert "method_attr" not in meta
    assert "_private" not in meta


def test_extract_adds_canonical_speasy_keys():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({"UNITS": "dB"}, provider="cda", uid="WI_L2/PSD")
    meta = extract_speasy_index_meta(idx)
    assert meta["uid"] == "WI_L2/PSD"
    assert meta["provider"] == "cda"
    assert meta["speasy_id"] == "cda/WI_L2/PSD"
    assert meta["stable_id"] == "cda/WI_L2/PSD"


def test_extract_uses_explicit_components_when_supplied():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({"UNITS": "nT"})
    meta = extract_speasy_index_meta(idx, components=["Bx", "By", "Bz"])
    assert meta["components"] == ["Bx", "By", "Bz"]


def test_extract_components_fallback_from_LABL_PTR_1_list():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({"LABL_PTR_1": ["a", "b", "c"]})
    meta = extract_speasy_index_meta(idx)
    assert meta["components"] == ["a", "b", "c"]


def test_extract_components_fallback_to_uid_when_unknown():
    from sciqlop_radio.hints import extract_speasy_index_meta
    idx = _fake_index({"UNITS": "K"}, uid="my_param")
    meta = extract_speasy_index_meta(idx)
    assert meta["components"] == ["my_param"]


def test_extract_propagates_missing_spz_uid_as_attributeerror():
    """Per spec, the extractor lets it raise; _register_entries catches."""
    from sciqlop_radio.hints import extract_speasy_index_meta
    # No spz_uid attribute at all
    idx = SimpleNamespace(UNITS="dB", spz_provider=lambda: "amda")
    with pytest.raises(AttributeError):
        extract_speasy_index_meta(idx)
