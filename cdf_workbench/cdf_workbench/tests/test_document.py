import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pycdfpp
import pytest

from cdf_workbench.document import Attribute, DocumentSession, from_cdf, to_cdf

CDFPP_RESOURCES = Path(os.environ.get(
    "CDFPP_TEST_RESOURCES", Path.home() / "Documents/prog/CDFpp/tests/resources"))


@pytest.fixture
def rich_cdf():
    cdf = pycdfpp.CDF()
    cdf.add_attribute("Project", ["ISTP>Test", "second entry"])
    cdf.add_attribute("Mixed", [np.arange(2, dtype=np.int32), [1.5, 2.5]],
                      [pycdfpp.DataType.CDF_INT4, pycdfpp.DataType.CDF_DOUBLE])
    epochs = np.arange(np.datetime64("2020-01-01"), np.datetime64("2020-01-01T00:00:05"),
                       np.timedelta64(1, "s")).astype("datetime64[ns]")
    cdf.add_variable("Epoch", values=epochs, data_type=pycdfpp.DataType.CDF_TIME_TT2000)
    cdf.add_variable("Epoch_ms", values=epochs, data_type=pycdfpp.DataType.CDF_EPOCH)
    cdf.add_variable("B", values=np.random.rand(5, 3).astype(np.float32),
                     compression=pycdfpp.CompressionType.gzip_compression)
    cdf.add_variable("label_B", values=np.array([b"Bx", b"By", b"Bz"]), is_nrv=True)
    cdf["B"].add_attribute("DEPEND_0", "Epoch")
    cdf["B"].add_attribute("LABL_PTR_1", "label_B")
    cdf["B"].add_attribute("FILLVAL", [np.float32(-1e31)], pycdfpp.DataType.CDF_REAL4)
    cdf["B"].add_attribute("VALIDMIN", [np.float32(-1e3)] * 3, pycdfpp.DataType.CDF_REAL4)
    return pycdfpp.load(bytes(pycdfpp.save(cdf)))


def _fingerprint(cdf: pycdfpp.CDF) -> dict:
    def attr_entries(a):
        return [(a.type(i), repr(a[i])) for i in range(len(a))]

    return {
        "globals": {n: attr_entries(a) for n, a in cdf.attributes.items()},
        "variables": {
            n: (v.type, tuple(v.shape), v.is_nrv, v.compression, v.values.tobytes(),
                {an: (a.type(), repr(a.value)) for an, a in v.attributes.items()})
            for n, v in cdf.items()
        },
    }


def _round_trip(cdf: pycdfpp.CDF) -> pycdfpp.CDF:
    return pycdfpp.load(bytes(pycdfpp.save(to_cdf(from_cdf(cdf)))))


def test_round_trip_keeps_types_shapes_values_and_attributes(rich_cdf):
    assert _fingerprint(_round_trip(rich_cdf)) == _fingerprint(rich_cdf)


@pytest.mark.parametrize("path", sorted(CDFPP_RESOURCES.glob("*.cdf")) if CDFPP_RESOURCES.is_dir() else [],
                         ids=lambda p: p.name)
def test_round_trip_cdfpp_resources(path):
    if path.name == "not_a_cdf.cdf":
        pytest.skip("not a CDF")
    cdf = pycdfpp.load(str(path))
    assert _fingerprint(_round_trip(cdf)) == _fingerprint(cdf)


def test_loading_a_document_does_not_read_values(tmp_path, rich_cdf):
    path = tmp_path / "f.cdf"
    pycdfpp.save(rich_cdf, str(path))
    cdf = pycdfpp.load(str(path))
    from_cdf(cdf)
    assert not any(v.values_loaded for _, v in cdf.items())


def test_document_reads_like_a_mapping(rich_cdf):
    doc = from_cdf(rich_cdf)
    assert "B" in doc and "nope" not in doc
    assert list(doc.keys()) == list(rich_cdf.keys())
    assert doc["B"].shape == (5, 3)
    assert doc["B"].attributes["DEPEND_0"].value == "Epoch"
    assert [e.value for e in doc.attributes["Project"].entries] == ["ISTP>Test", "second entry"]
    np.testing.assert_array_equal(doc["B"].values, rich_cdf["B"].values)


def test_rename_and_drop_attribute_reach_the_saved_file(rich_cdf):
    doc = from_cdf(rich_cdf)
    b = doc["B"]
    attrs = {k: a for k, a in b.attributes.items() if k != "VALIDMIN"}
    attrs["UNITS"] = Attribute("nT", pycdfpp.DataType.CDF_CHAR)
    edited = replace(doc, variables={
        **{k: v for k, v in doc.variables.items() if k != "B"},
        "B_gse": replace(b, attributes=attrs),
    })

    out = pycdfpp.load(bytes(pycdfpp.save(to_cdf(edited))))

    assert "B" not in out and "B_gse" in out
    assert "VALIDMIN" not in out["B_gse"].attributes
    assert out["B_gse"].attributes["UNITS"].value == "nT"
    np.testing.assert_array_equal(out["B_gse"].values, rich_cdf["B"].values)
    assert from_cdf(rich_cdf)["B"].attributes.keys() >= {"VALIDMIN"}


def test_session_tracks_modified_state(qtbot, rich_cdf):
    session = DocumentSession(from_cdf(rich_cdf))
    assert not session.is_modified

    with qtbot.waitSignal(session.changed):
        session.apply(lambda d: replace(d, attributes={}))
    assert session.is_modified
    assert session.document.attributes == {}

    session.mark_saved()
    assert not session.is_modified


def test_mapping_key_is_the_saved_name(rich_cdf):
    doc = from_cdf(rich_cdf)
    renamed = replace(doc, variables={("Bfield" if k == "B" else k): v for k, v in doc.variables.items()})

    out = pycdfpp.load(bytes(pycdfpp.save(to_cdf(renamed))))

    assert "Bfield" in out and "B" not in out


def test_edited_value_of_a_read_attribute_is_saved(rich_cdf):
    doc = from_cdf(rich_cdf)
    b = doc["B"]
    fill = replace(b.attributes["FILLVAL"], value=[np.float32(-999.0)])
    project = replace(doc.attributes["Project"],
                      entries=doc.attributes["Project"].entries[:1])
    edited = replace(doc, attributes={**doc.attributes, "Project": project},
                     variables={**doc.variables, "B": replace(b, attributes={**b.attributes, "FILLVAL": fill})})

    out = pycdfpp.load(bytes(pycdfpp.save(to_cdf(edited))))

    assert out["B"].attributes["FILLVAL"].value == [-999.0]
    assert list(out.attributes["Project"]) == ["ISTP>Test"]


def test_session_rejects_an_edit_that_returns_the_same_document(rich_cdf):
    session = DocumentSession(from_cdf(rich_cdf))

    def in_place(doc):
        doc.attributes.clear()
        return doc

    with pytest.raises(ValueError):
        session.apply(in_place)
