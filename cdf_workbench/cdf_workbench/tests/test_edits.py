"""Attribute edits: typed text parsing and pure Document -> Document functions."""
import numpy as np
import pycdfpp
import pytest

from cdf_workbench.document import Attribute, GlobalAttribute, from_cdf, to_cdf
from cdf_workbench.edits import (
    format_value, parse_value, remove_global_attribute, remove_variable_attribute,
    set_global_attribute, set_variable_attribute,
)

T = pycdfpp.DataType


@pytest.fixture
def doc():
    cdf = pycdfpp.CDF()
    cdf.add_attribute("Project", ["ISTP", "second"])
    cdf.add_attribute("Mission", ["MMS"])
    cdf.add_variable("B", values=np.ones(3))
    cdf["B"].add_attribute("UNITS", "nT")
    cdf["B"].add_attribute("FILLVAL", [-1e31], T.CDF_DOUBLE)
    cdf["B"].add_attribute("CATDESC", "field")
    return from_cdf(pycdfpp.load(bytes(pycdfpp.save(cdf))))


def _saved(doc):
    return pycdfpp.load(bytes(pycdfpp.save(to_cdf(doc))))


@pytest.mark.parametrize("text, data_type, expected", [
    ("nT", T.CDF_CHAR, "nT"),
    ("1, 2, 3", T.CDF_INT4, [1, 2, 3]),
    ("-1e31", T.CDF_DOUBLE, [-1e31]),
    (" 0.5 ,1.5 ", T.CDF_FLOAT, [0.5, 1.5]),
])
def test_parse_value(text, data_type, expected):
    assert parse_value(text, data_type) == expected


def test_parse_time_values():
    value = parse_value("2020-01-01T12:00:00.5", T.CDF_TIME_TT2000)
    assert value == [np.datetime64("2020-01-01T12:00:00.5", "ns")]


@pytest.mark.parametrize("text, data_type", [("1.5", T.CDF_INT4), ("abc", T.CDF_DOUBLE), ("300", T.CDF_INT1),
                                             ("", T.CDF_INT2), ("yesterday", T.CDF_EPOCH)])
def test_parse_rejects_bad_text_with_a_message(text, data_type):
    with pytest.raises(ValueError):
        parse_value(text, data_type)


@pytest.mark.parametrize("value, data_type", [("nT", T.CDF_CHAR), ([1, 2, 3], T.CDF_INT4), ([-1e31], T.CDF_DOUBLE)])
def test_format_then_parse_gives_the_value_back(value, data_type):
    assert parse_value(format_value(value), data_type) == value


def test_format_then_parse_a_read_time_attribute(doc):
    cdf = pycdfpp.CDF()
    cdf.add_variable("v", values=np.ones(1))
    cdf["v"].add_attribute("T", [np.datetime64("2020-01-01T12:00:00.5", "ns")], T.CDF_TIME_TT2000)
    value = from_cdf(cdf)["v"].attributes["T"].value
    assert parse_value(format_value(value), T.CDF_TIME_TT2000) == [np.datetime64("2020-01-01T12:00:00.5", "ns")]


def test_set_variable_attribute_changes_value_and_type(doc):
    edited = set_variable_attribute(doc, "B", "FILLVAL", "FILLVAL", Attribute([-999], T.CDF_INT4))

    out = _saved(edited)["B"].attributes["FILLVAL"]
    assert out.value == [-999] and out.type() == T.CDF_INT4
    assert doc["B"].attributes["FILLVAL"].type == T.CDF_DOUBLE


def test_rename_keeps_the_position(doc):
    edited = set_variable_attribute(doc, "B", "UNITS", "UNIT", Attribute("nT", T.CDF_CHAR))
    assert list(edited["B"].attributes) == ["UNIT", "FILLVAL", "CATDESC"]


def test_add_and_remove_variable_attributes(doc):
    added = set_variable_attribute(doc, "B", None, "LABLAXIS", Attribute("B", T.CDF_CHAR))
    removed = remove_variable_attribute(added, "B", "CATDESC")
    assert list(_saved(removed)["B"].attributes) == ["UNITS", "FILLVAL", "LABLAXIS"]


def test_cannot_rename_onto_an_existing_attribute(doc):
    with pytest.raises(ValueError, match="CATDESC"):
        set_variable_attribute(doc, "B", "UNITS", "CATDESC", Attribute("x", T.CDF_CHAR))


def test_global_attribute_edits(doc):
    entries = GlobalAttribute((Attribute("ISTP", T.CDF_CHAR), Attribute("third", T.CDF_CHAR)))
    edited = remove_global_attribute(set_global_attribute(doc, "Project", "Project", entries), "Mission")

    out = _saved(edited)
    assert list(out.attributes) == ["Project"]
    assert list(out.attributes["Project"]) == ["ISTP", "third"]


def test_attribute_form_for_a_variable_is_one_value():
    from cdf_workbench.edits import read_attribute_form
    assert read_attribute_form(" UNITS ", T.CDF_INT4, "1, 2", multi_entry=False) == ("UNITS", T.CDF_INT4, [[1, 2]])


def test_attribute_form_for_a_global_is_one_entry_per_line():
    from cdf_workbench.edits import read_attribute_form
    assert read_attribute_form("Project", T.CDF_CHAR, "ISTP\nSPDF\n", multi_entry=True) == (
        "Project", T.CDF_CHAR, ["ISTP", "SPDF"])


def test_attribute_form_needs_a_name():
    from cdf_workbench.edits import read_attribute_form
    with pytest.raises(ValueError, match="name"):
        read_attribute_form("  ", T.CDF_CHAR, "x", multi_entry=False)


def test_format_a_scalar():
    assert format_value(3) == "3"
