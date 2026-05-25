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


# ---------------------------------------------------------------------------
# RichEasySpectrogram overrides
# ---------------------------------------------------------------------------

import sys
from unittest.mock import MagicMock

_SCIQLOP_REAL = not isinstance(
    sys.modules.get("SciQLop.core.plot_hints"), MagicMock
)


def _fake_node_with_meta(meta):
    """Mimic the bits of ProductsModelNode the hooks actually call."""
    return SimpleNamespace(metadata=lambda: meta)


def test_plot_hints_translates_node_metadata_to_z_axis():
    if not _SCIQLOP_REAL:
        pytest.skip("requires real SciQLop install - PlotHints is a MagicMock under headless conftest")
    from sciqlop_radio.hints import RichEasySpectrogram
    from SciQLop.core.plot_hints import PlotHints

    spec = RichEasySpectrogram.__new__(RichEasySpectrogram)
    node = _fake_node_with_meta({
        "DISPLAY_TYPE": "spectrogram",
        "UNITS": "dB/Hz",
        "LABLAXIS": "PSD",
        "SCALETYP": "log",
    })
    hints = spec.plot_hints(node)
    assert isinstance(hints, PlotHints)
    assert hints.display_type == "spectrogram"
    assert hints.z.unit == "dB/Hz"
    assert hints.z.label == "PSD"
    assert hints.z.scale == "log"


def test_plot_hints_returns_empty_on_metadata_exception():
    if not _SCIQLOP_REAL:
        pytest.skip("requires real SciQLop install")
    from sciqlop_radio.hints import RichEasySpectrogram
    from SciQLop.core.plot_hints import PlotHints

    spec = RichEasySpectrogram.__new__(RichEasySpectrogram)

    def broken_metadata():
        raise RuntimeError("node gone")

    node = SimpleNamespace(metadata=broken_metadata)
    hints = spec.plot_hints(node)
    assert isinstance(hints, PlotHints)
    # Empty PlotHints - no axis info populated
    assert hints.z.label is None and hints.z.unit is None


def _fake_speasy_variable(z_meta, freq_meta, freq=None):
    """Mimic the bits of SpeasyVariable variable_as_istp_meta touches."""
    from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
    from speasy.products.variable import SpeasyVariable
    import numpy as np

    if freq is None:
        freq = np.array([10.0, 20.0, 30.0], dtype=np.float64)
    times = np.array(["2024-01-01T00:00:00", "2024-01-01T00:00:01"],
                     dtype="datetime64[ns]")
    time_axis = VariableTimeAxis(values=times)
    freq_axis = VariableAxis(name=freq_meta.get("LABLAXIS", ""),
                             values=freq, meta=freq_meta)
    data = np.zeros((2, 3), dtype=np.float64)
    values = DataContainer(values=data, meta=z_meta,
                           name=z_meta.get("LABLAXIS", "test"))
    return SpeasyVariable(axes=[time_axis, freq_axis], values=values,
                          columns=["test"])


def test_plot_hints_from_variable_populates_y2_from_freq_axis():
    if not _SCIQLOP_REAL:
        pytest.skip("requires real SciQLop install")
    from sciqlop_radio.hints import RichEasySpectrogram
    from SciQLop.core.enums import GraphType
    from SciQLop.core.plot_hints import PlotHints

    spec = RichEasySpectrogram.__new__(RichEasySpectrogram)
    # graph_type returns ColorMap -> variable_as_istp_meta sets DISPLAY_TYPE
    spec.graph_type = lambda node: GraphType.ColorMap
    node = _fake_node_with_meta({})
    var = _fake_speasy_variable(
        z_meta={"UNITS": "dB", "LABLAXIS": "PSD", "SCALETYP": "log"},
        freq_meta={"UNITS": "Hz", "LABLAXIS": "Frequency", "SCALETYP": "log"},
    )
    hints = spec.plot_hints_from_variable(node, var)
    assert isinstance(hints, PlotHints)
    assert hints.y2.unit == "Hz"
    assert hints.y2.label == "Frequency"
    assert hints.y2.scale == "log"


def test_plot_hints_from_variable_returns_empty_on_exception():
    if not _SCIQLOP_REAL:
        pytest.skip("requires real SciQLop install")
    from sciqlop_radio.hints import RichEasySpectrogram
    from SciQLop.core.plot_hints import PlotHints

    spec = RichEasySpectrogram.__new__(RichEasySpectrogram)
    spec.graph_type = lambda node: None
    node = _fake_node_with_meta({})
    # not a SpeasyVariable -> variable_as_istp_meta raises
    hints = spec.plot_hints_from_variable(node, "not a variable")
    assert isinstance(hints, PlotHints)
