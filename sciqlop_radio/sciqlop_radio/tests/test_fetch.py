"""RadioFetchService unit tests — Fido is fully mocked."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _query(**kw):
    from sciqlop_radio.query import RadioQuery
    base = dict(t_start=datetime(2021, 9, 1, tzinfo=timezone.utc),
                t_end=datetime(2021, 9, 2, tzinfo=timezone.utc))
    base.update(kw)
    return RadioQuery(**base)


def test_search_emits_search_completed(qapp, tmp_path):
    from sciqlop_radio.fetch import RadioFetchService
    from sciqlop_radio.query import RadioQuery

    svc = RadioFetchService(cache_dir=tmp_path)
    received = []

    svc.searchCompleted.connect(lambda rows: received.append(rows))
    svc.searchFailed.connect(lambda msg: received.append(("FAIL", msg)))

    fake_rows = [MagicMock(name=f"row{i}", url=f"https://archive/example_{i}.cdf") for i in range(3)]

    with patch("sciqlop_radio.fetch._do_search", return_value=fake_rows):
        svc.search(
            RadioQuery(t_start=datetime(2024, 5, 1, tzinfo=timezone.utc),
                       t_end=datetime(2024, 5, 2, tzinfo=timezone.utc),
                       instrument="ILOFAR")
        )
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()

    assert received, "no signal received"
    assert isinstance(received[0], list)
    assert len(received[0]) == 3


def test_search_failure_emits_search_failed(qapp, tmp_path):
    from sciqlop_radio.fetch import RadioFetchService
    from sciqlop_radio.query import RadioQuery

    svc = RadioFetchService(cache_dir=tmp_path)
    received = []
    svc.searchCompleted.connect(lambda rows: received.append(("OK", rows)))
    svc.searchFailed.connect(lambda msg: received.append(("FAIL", msg)))

    with patch("sciqlop_radio.fetch._do_search", side_effect=RuntimeError("boom")):
        svc.search(
            RadioQuery(t_start=datetime(2024, 5, 1, tzinfo=timezone.utc),
                       t_end=datetime(2024, 5, 2, tzinfo=timezone.utc),
                       instrument="ILOFAR")
        )
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()

    assert received and received[0][0] == "FAIL"
    assert "boom" in received[0][1]


def test_format_time_for_fido_strips_timezone():
    """astropy.time.Time's isot parser rejects '+00:00' suffix; the helper
    must hand it a naive-UTC ISO string."""
    from sciqlop_radio.fetch import _format_time_for_fido

    aware = datetime(2024, 5, 1, 12, 30, 45, tzinfo=timezone.utc)
    assert _format_time_for_fido(aware) == "2024-05-01T12:30:45"

    naive = datetime(2024, 5, 1, 12, 30, 45)
    assert _format_time_for_fido(naive) == "2024-05-01T12:30:45"


def test_format_time_for_fido_converts_non_utc_offset():
    """Aware datetimes in another timezone get converted to UTC before format."""
    from datetime import timezone as tz, timedelta
    from sciqlop_radio.fetch import _format_time_for_fido

    paris = datetime(2024, 5, 1, 14, 30, 0, tzinfo=tz(timedelta(hours=2)))
    assert _format_time_for_fido(paris) == "2024-05-01T12:30:00"


def test_format_time_for_fido_output_parses_with_astropy():
    """Regression guard for the actual bug: astropy.time.Time must accept the output."""
    pytest.importorskip("astropy")
    from astropy.time import Time

    from sciqlop_radio.fetch import _format_time_for_fido

    aware = datetime(2024, 5, 1, tzinfo=timezone.utc)
    Time(_format_time_for_fido(aware))  # must not raise


def test_do_search_surfaces_response_errors(monkeypatch):
    """When Fido attaches client-side errors AND returns no rows, _do_search
    must raise so the dock shows a real message instead of 'Found 0 file(s)'."""
    from types import SimpleNamespace
    import sys, types

    from sciqlop_radio import fetch as fetch_mod

    class FakeResponse:
        errors = [TypeError("Scraper.__init__() missing 1 required positional argument: 'format'")]
        def __iter__(self):
            return iter([])

    fake_Fido = SimpleNamespace(search=lambda *args, **kwargs: FakeResponse())
    fake_attrs = SimpleNamespace(
        Time=lambda *a, **k: object(),
        Instrument=lambda *a, **k: object(),
    )
    fake_sunpy_net = types.ModuleType("sunpy.net")
    fake_sunpy_net.Fido = fake_Fido
    fake_sunpy_net.attrs = fake_attrs
    monkeypatch.setitem(sys.modules, "sunpy.net", fake_sunpy_net)
    monkeypatch.setitem(sys.modules, "radiospectra.net", types.ModuleType("radiospectra.net"))

    with pytest.raises(RuntimeError, match="Fido client errors"):
        fetch_mod._do_search(_query(instrument="ILOFAR"))


def test_build_attrs_includes_instrument_and_wavelength(monkeypatch):
    from types import SimpleNamespace
    import sys, types
    fake_attrs = SimpleNamespace(
        Time=lambda *a, **k: ("Time", a),
        Instrument=lambda *a, **k: ("Instrument", a),
        Wavelength=lambda lo, hi: ("Wavelength", lo, hi),
    )
    monkeypatch.setitem(sys.modules, "radiospectra.net", types.ModuleType("radiospectra.net"))
    fake_net = types.ModuleType("sunpy.net")
    fake_net.attrs = fake_attrs
    monkeypatch.setitem(sys.modules, "sunpy.net", fake_net)

    from sciqlop_radio import fetch as fetch_mod
    attrs = fetch_mod._build_attrs(_query(instrument="ILOFAR",
                                         wavelength_min_mhz=20.0,
                                         wavelength_max_mhz=100.0))
    kinds = [x[0] for x in attrs]
    assert kinds == ["Time", "Instrument", "Wavelength"]


def test_eval_raw_attrs_valid(monkeypatch):
    from types import SimpleNamespace
    import sys, types
    fake_attrs = SimpleNamespace(
        Time=lambda *a, **k: ("Time", a),
        Instrument=lambda *a, **k: ("Instrument", a),
        Wavelength=lambda *a, **k: ("Wavelength", a),
    )
    monkeypatch.setitem(sys.modules, "radiospectra.net", types.ModuleType("radiospectra.net"))
    fake_net = types.ModuleType("sunpy.net")
    fake_net.attrs = fake_attrs
    monkeypatch.setitem(sys.modules, "sunpy.net", fake_net)

    from sciqlop_radio import fetch as fetch_mod
    attrs = fetch_mod._eval_raw_attrs("a.Time('2021-09-01','2021-09-02'), a.Instrument('ILOFAR')")
    assert [x[0] for x in attrs] == ["Time", "Instrument"]


def test_eval_raw_attrs_invalid_raises(monkeypatch):
    import sys, types
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, "radiospectra.net", types.ModuleType("radiospectra.net"))
    fake_net = types.ModuleType("sunpy.net")
    fake_net.attrs = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "sunpy.net", fake_net)

    from sciqlop_radio import fetch as fetch_mod
    with pytest.raises(RuntimeError, match="Invalid raw Fido query"):
        fetch_mod._eval_raw_attrs("import os; os.system('boom')")


def test_row_url_reads_column_then_attribute():
    from sciqlop_radio.fetch import _row_url

    class DictRow(dict):
        pass

    assert _row_url(DictRow({"url": "https://x/a.fit.gz"})) == "https://x/a.fit.gz"

    class AttrRow:
        url = "https://y/b.cdf"
    assert _row_url(AttrRow()) == "https://y/b.cdf"


def test_fetch_uses_cache_hit(qapp, tmp_path):
    from sciqlop_radio.fetch import RadioFetchService

    cached = tmp_path / "example_0.cdf"
    cached.write_bytes(b"\x00" * 16)

    svc = RadioFetchService(cache_dir=tmp_path)

    received = []
    svc.fetchCompleted.connect(lambda ok, failed: received.append((list(ok), list(failed))))

    class DictRow(dict):
        pass
    row = DictRow({"url": "https://archive/example_0.cdf"})

    with patch("sciqlop_radio.fetch._do_fetch") as fido_fetch:
        svc.fetch([row])
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()
        fido_fetch.assert_not_called()

    assert received
    ok, failed = received[0]
    assert cached in ok
    assert not failed


def test_row_field_stringifies_non_str_column():
    """Real Fido columns are often non-str (astropy Time, numpy scalars).
    They must be stringified, not dropped."""
    from sciqlop_radio.fetch import _row_field

    class DictRow(dict):
        pass

    assert _row_field(DictRow({"Start Time": 12345}), "Start Time") == "12345"

    class Stamp:
        def __str__(self):
            return "2011-06-07 06:15:00.000"
    assert _row_field(DictRow({"Start Time": Stamp()}), "Start Time") == "2011-06-07 06:15:00.000"


def test_repeat_search_hits_in_memory_cache(qapp, tmp_path):
    """A second identical search within the TTL must re-emit cached rows
    without calling _do_search again."""
    from sciqlop_radio.fetch import RadioFetchService

    svc = RadioFetchService(cache_dir=tmp_path)
    received = []
    svc.searchCompleted.connect(lambda rows: received.append(rows))

    fake_rows = [object(), object()]
    query = _query(instrument="ILOFAR")

    with patch("sciqlop_radio.fetch._do_search", return_value=fake_rows) as do_search:
        svc.search(query)
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()
        svc.search(query)              # identical → cache hit
        svc.wait_for_finished(timeout_s=5.0)
        qapp.processEvents()

    assert do_search.call_count == 1, "second identical search should hit the cache"
    assert len(received) == 2 and len(received[1]) == 2
