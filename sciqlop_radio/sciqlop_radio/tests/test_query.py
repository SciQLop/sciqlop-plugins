from __future__ import annotations

from datetime import datetime, timezone

from sciqlop_radio.query import RadioQuery
from sciqlop_radio.sources import SOURCES


def _t(d):
    return datetime(2021, 9, d, tzinfo=timezone.utc)


def test_from_source_copies_instrument_and_times():
    src = next(s for s in SOURCES if s.fido_instrument)
    q = RadioQuery.from_source(src, _t(1), _t(2))
    assert q.instrument == src.fido_instrument
    assert q.t_start == _t(1)
    assert q.t_end == _t(2)
    assert q.expect_spectrogram is True
    assert q.raw_attrs_text is None


def test_raw_query_defaults_keep_all_rows_off_until_set():
    q = RadioQuery(t_start=_t(1), t_end=_t(2), raw_attrs_text="a.Time('x','y')",
                   expect_spectrogram=False)
    assert q.raw_attrs_text == "a.Time('x','y')"
    assert q.expect_spectrogram is False


def test_optional_wavelength_fields():
    q = RadioQuery(t_start=_t(1), t_end=_t(2), instrument="ILOFAR",
                   wavelength_min_mhz=20.0, wavelength_max_mhz=100.0)
    assert q.wavelength_min_mhz == 20.0
    assert q.wavelength_max_mhz == 100.0
