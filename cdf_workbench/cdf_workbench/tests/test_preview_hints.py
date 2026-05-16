"""DEPEND_1 SCALETYP must reach hints.y2.scale through the CDF attribute conversion.

Reproducer: pycdfpp's VariableAttribute is non-iterable and ``str(v)`` returns
the dump format (``'SCALETYP: "log"\\n'``) — not the value. The old idiom
``list(v) if hasattr(v, "__iter__") ...`` dropped the value silently and the
spectrogram Y axis ended up linear regardless of DEPEND_1.SCALETYP.
"""
import numpy as np
import pycdfpp
import pytest

pytest.importorskip("SciQLop.core.istp_hints")

from SciQLop.core.istp_hints import istp_metadata_to_hints

from cdf_workbench.file_view import _cdf_attrs_to_dict


def _spectrogram_cdf():
    cdf = pycdfpp.CDF()
    energies = np.array([1.0, 10.0, 100.0, 1000.0], dtype=np.float32)
    cdf.add_variable("Energy", values=energies, is_nrv=True)
    cdf["Energy"].add_attribute("SCALETYP", "log")
    cdf["Energy"].add_attribute("UNITS", "eV")
    cdf["Energy"].add_attribute("LABLAXIS", "Energy")

    flux = np.ones((3, 4), dtype=np.float32)
    cdf.add_variable("Flux", values=flux, is_nrv=False)
    cdf["Flux"].add_attribute("DISPLAY_TYPE", "spectrogram")
    cdf["Flux"].add_attribute("DEPEND_1", "Energy")
    cdf["Flux"].add_attribute("SCALETYP", "log")
    cdf["Flux"].add_attribute("UNITS", "counts/s")
    return cdf


def test_cdf_attrs_dict_unwraps_string_attribute():
    cdf = _spectrogram_cdf()
    meta = _cdf_attrs_to_dict(cdf["Energy"])
    assert meta["SCALETYP"] == ["log"]
    assert meta["UNITS"] == ["eV"]
    assert meta["LABLAXIS"] == ["Energy"]


def test_depend_1_scaletyp_reaches_y2_scale():
    cdf = _spectrogram_cdf()
    meta = {
        "DISPLAY_TYPE": ["spectrogram"],
        "SCALETYP": ["log"],
        "UNITS": ["counts/s"],
        "_depend_1": _cdf_attrs_to_dict(cdf["Energy"]),
    }
    hints = istp_metadata_to_hints(meta)
    assert hints.display_type == "spectrogram"
    assert hints.z.scale == "log"
    assert hints.y2.scale == "log"
    assert hints.y2.unit == "eV"
    assert hints.y2.label == "Energy"
