"""Refuse to read a variable whose values can't fit in free memory, with a clear message."""
import numpy as np
import pycdfpp

from cdf_workbench.document import from_cdf
from cdf_workbench.memory import decoded_nbytes, format_bytes, memory_problem


def _doc():
    cdf = pycdfpp.CDF()
    cdf.add_variable("dist", values=np.ones((3, 2, 3, 4), dtype=np.float32))
    cdf.add_variable("t", values=np.array(["2020-01-01"], dtype="datetime64[ns]"),
                     data_type=pycdfpp.DataType.CDF_EPOCH16)
    cdf.add_variable("label", values=np.array([b"abc", b"def"]), is_nrv=True)
    return from_cdf(cdf)


def test_decoded_size_comes_from_shape_and_type_without_reading_values():
    doc = _doc()
    assert decoded_nbytes(doc["dist"]) == 3 * 2 * 3 * 4 * 4
    assert decoded_nbytes(doc["t"]) == 16
    assert decoded_nbytes(doc["label"]) == 6


def test_no_problem_when_it_fits():
    assert memory_problem("dist", _doc()["dist"], available=10**9) is None


def test_problem_says_how_much_is_needed_and_available():
    message = memory_problem("dist", _doc()["dist"], available=100)
    assert "dist" in message and format_bytes(100) in message
    assert "needs" in message


def test_format_bytes_is_readable():
    assert format_bytes(512) == "512 B"
    assert format_bytes(3 * 2**30) == "3.0 GiB"
