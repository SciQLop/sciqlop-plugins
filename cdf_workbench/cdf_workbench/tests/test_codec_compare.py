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


def test_a_failing_identity_check_is_reported_not_raised(doc, monkeypatch):
    import cdf_workbench.codec_compare as codec_compare
    monkeypatch.setattr(codec_compare, "_same_values", lambda d, r: (_ for _ in ()).throw(KeyError("B")))
    result = try_codec(doc, C.gzip_compression)
    assert result.error and not result.identical


def test_one_failing_codec_does_not_stop_the_others(doc, monkeypatch):
    import cdf_workbench.codec_dialog as codec_dialog
    real = codec_dialog.try_codec
    monkeypatch.setattr(codec_dialog, "try_codec",
                        lambda d, c: (_ for _ in ()).throw(RuntimeError("boom")) if c == C.rle_compression else real(d, c))
    results = []
    signals = codec_dialog._CodecSignals()
    signals.result.connect(results.append)

    codec_dialog._CodecTask(doc, signals).run()

    assert len(results) == len(CODECS)
    assert next(r for r in results if r.codec == C.rle_compression).error == "boom"
