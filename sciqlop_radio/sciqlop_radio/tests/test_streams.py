"""Tests for stream-identity derivation (pure, no Fido)."""
from __future__ import annotations

from sciqlop_radio.sources import SOURCES
from sciqlop_radio.streams import StreamIdentity, rule_for, stream_identity_for_row


class FakeRow(dict):
    """Dict-backed stand-in for a Fido QueryResponseRow (column access)."""


def _src(key):
    return next(s for s in SOURCES if s.key == key)


def test_ecallisto_identity_includes_station_and_focus_code():
    row = FakeRow({"Observatory": "BIR", "ID": "01",
                   "url": "http://a/BIR_20110607_120000_01.fit.gz"})
    ident = stream_identity_for_row(row, _src("ecallisto"))
    assert ident.station == "BIR"
    assert ident.channel == "01"
    assert ident.instrument == "eCALLISTO"
    assert ident.vp_path == "radio/ecallisto/BIR/01"


def test_ecallisto_focus_codes_get_distinct_paths():
    src = _src("ecallisto")
    r1 = FakeRow({"Observatory": "BIR", "ID": "01"})
    r2 = FakeRow({"Observatory": "BIR", "ID": "02"})
    assert (stream_identity_for_row(r1, src).vp_path
            != stream_identity_for_row(r2, src).vp_path)


def test_rstn_identity_is_per_station_no_channel():
    row = FakeRow({"Observatory": "learmonth", "ID": "x"})
    ident = stream_identity_for_row(row, _src("rstn"))
    assert ident.station == "learmonth"
    assert ident.channel == ""
    assert ident.vp_path == "radio/rstn/learmonth"


def test_ilofar_identity_splits_by_polarisation():
    # ILOFAR mode 357 BST ships one file per polarisation (X and Y linear,
    # see ILOFARMode357Client) for every timestamp. Folding both into one
    # stream concatenates two different channels' data into a single time
    # series, producing a spectrogram with an X-pol/Y-pol seam at every file
    # boundary. Each polarisation must get its own stream identity.
    row_x = FakeRow({"Observatory": "IE613", "Polarisation": "X"})
    row_y = FakeRow({"Observatory": "IE613", "Polarisation": "Y"})
    ident_x = stream_identity_for_row(row_x, _src("ilofar"))
    ident_y = stream_identity_for_row(row_y, _src("ilofar"))
    assert ident_x.station == ""
    assert ident_x.channel == "X"
    assert ident_y.channel == "Y"
    assert ident_x.vp_path != ident_y.vp_path
    assert ident_x.vp_path == "radio/ilofar/X"
    assert ident_y.vp_path == "radio/ilofar/Y"


def test_station_with_space_is_sanitized():
    row = FakeRow({"Observatory": "Sagamore Hill"})
    ident = stream_identity_for_row(row, _src("rstn"))
    assert ident.vp_path == "radio/rstn/Sagamore_Hill"


def test_missing_columns_default_to_empty():
    row = FakeRow({})  # real rows can lack a column
    ident = stream_identity_for_row(row, _src("ecallisto"))
    assert ident.station == "" and ident.channel == ""
    assert ident.vp_path == "radio/ecallisto"


def test_ecallisto_attrs_include_server_side_observatory():
    from sciqlop_radio.streams import StreamIdentity, stream_fido_attrs
    ident = StreamIdentity(source_key="ecallisto", instrument="eCALLISTO",
                           station="BIR", channel="01")
    names = [type(a).__name__ for a in stream_fido_attrs(ident)]
    assert "Instrument" in names
    assert "Observatory" in names  # radiospectra's, server-side station filter


def test_rstn_attrs_have_no_observatory():
    from sciqlop_radio.streams import StreamIdentity, stream_fido_attrs
    ident = StreamIdentity(source_key="rstn", instrument="RSTN",
                           station="learmonth")
    names = [type(a).__name__ for a in stream_fido_attrs(ident)]
    assert "Instrument" in names
    assert "Observatory" not in names  # RSTN filtered client-side only
