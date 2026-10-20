"""X1: re-encode the document with every codec, compare sizes, keep the chosen one."""
import numpy as np
import pycdfpp
import pytest

from cdf_workbench.codec_compare import CODECS, try_codec, with_compression
from cdf_workbench.document import DocumentSession, from_cdf

C = pycdfpp.CompressionType


@pytest.fixture
def doc():
    cdf = pycdfpp.CDF()
    cdf.add_variable("B", values=np.tile(np.arange(100, dtype=np.float64), 50))
    cdf.add_variable("label", values=np.array([b"x", b"y"]), is_nrv=True)
    return from_cdf(pycdfpp.load(bytes(pycdfpp.save(cdf))))


def test_every_pycdfpp_codec_is_tried():
    assert set(CODECS) == set(C.__members__.values())


def test_gzip_is_smaller_and_identical(doc):
    plain, gzip = try_codec(doc, C.no_compression), try_codec(doc, C.gzip_compression)
    assert plain.identical and gzip.identical and not gzip.error
    assert gzip.size < plain.size
    assert gzip.write_s >= 0 and gzip.read_s >= 0


def test_a_codec_pycdfpp_cannot_write_is_reported_not_raised(doc):
    result = try_codec(doc, C.huff_compression)
    assert result.size is None and "Unsupported" in result.error


def test_experimental_codecs_are_flagged(doc):
    assert try_codec(doc, C.zstd_compression).experimental
    assert not try_codec(doc, C.gzip_compression).experimental


def test_with_compression_sets_every_variable(doc):
    assert {v.compression for _, v in with_compression(doc, C.gzip_compression).items()} == {C.gzip_compression}


def test_dialog_fills_the_table_and_applies_the_chosen_codec(qtbot, doc):
    from cdf_workbench.codec_dialog import CodecDialog
    session = DocumentSession(doc)
    dialog = CodecDialog(session, original_size=None)
    qtbot.addWidget(dialog)

    qtbot.waitUntil(lambda: dialog.finished_count() == len(CODECS), timeout=30000)
    dialog.select(C.gzip_compression)
    dialog.use_selected()

    assert {v.compression for _, v in session.document.items()} == {C.gzip_compression}
    session.undo()
    assert {v.compression for _, v in session.document.items()} == {C.no_compression}
