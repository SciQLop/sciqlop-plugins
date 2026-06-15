"""Dock tests with an injected fake RadioFetchService.

We never hit the real Fido here — the dock's contract with fetch.py is
expressed entirely through signal subscriptions, which we exercise with
a stand-in QObject that emits the same signals.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6.QtCore import QObject, Signal


class FakeRow(dict):
    """Dict-backed stand-in for a Fido QueryResponseRow (column access)."""


def _erow(url, observatory="", start=""):
    return FakeRow({"url": url, "Observatory": observatory, "Start Time": start})


def _crow(url, observatory, idcode, start=""):
    return FakeRow({"url": url, "Observatory": observatory, "ID": idcode,
                    "Start Time": start})


class FakeFetchService(QObject):
    searchCompleted = Signal(list)
    searchFailed = Signal(str)
    fetchProgress = Signal(int, int)
    fetchCompleted = Signal(list, list)
    fetchFailed = Signal(str)

    def __init__(self):
        super().__init__()
        self.search_calls: list = []
        self.fetch_calls: list = []
        self._cache_dir = Path("/tmp/sciqlop_radio_test_cache")

    def search(self, query):
        self.search_calls.append(query)

    def fetch(self, rows):
        self.fetch_calls.append(list(rows))

    def wait_for_finished(self, timeout_s=5.0):
        return True


@pytest.fixture
def dock(qtbot):
    from sciqlop_radio.dock import RadioSpectraDock
    svc = FakeFetchService()
    w = RadioSpectraDock(main_window=None, fetch_service=svc)
    qtbot.addWidget(w)
    return w, svc


def test_source_dropdown_populated_from_registry(dock):
    w, _ = dock
    from sciqlop_radio.sources import SOURCES
    assert w.source_combo.count() == len(SOURCES)


def test_fetch_button_builds_query_from_source(dock):
    w, svc = dock
    w.start_picker.setDateTime(_qdt(2021, 9, 1))
    w.end_picker.setDateTime(_qdt(2021, 9, 2))
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).fido_instrument:
            w.source_combo.setCurrentIndex(i)
            break
    w.fetch_button.click()
    assert svc.search_calls, "fetch button did not trigger search"
    q = svc.search_calls[-1]
    assert q.instrument
    assert q.t_start < q.t_end


def test_selecting_eovsa_disables_fetch_and_shows_message(dock):
    w, svc = dock
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).key == "eovsa":
            w.source_combo.setCurrentIndex(i)
            break
    w.fetch_button.click()
    assert not svc.search_calls, "EOVSA must not trigger a Fido search"
    assert "registration" in w.status_label.text().lower()


def test_search_results_populate_table(dock, qtbot):
    w, svc = dock
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit([_erow("https://archive/example_0.cdf", "BIR", "2021-09-07 08:00")])
    assert w.results_table.rowCount() == 1
    assert "example_0.cdf" in w._table_filename(0)
    assert w._table_station(0) == "BIR"


def test_search_drops_non_spectrogram_results(dock, qtbot):
    w, svc = dock
    rows = [
        _erow("https://archive/swaves_tds_tdsmax_20240612.txt"),
        _erow("https://archive/psp_rfs_20240612.cdf"),
        _erow("https://archive/callisto_20240612.fit.gz"),
        _erow("https://archive/something_else.bin"),
    ]
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit(rows)
    assert w.results_table.rowCount() == 2
    names = [w._table_filename(i) for i in range(w.results_table.rowCount())]
    assert not any(n.endswith(".txt") or n.endswith(".bin") for n in names)
    assert "2 non-spectrogram" in w.status_label.text()


def test_empty_results_shows_coverage_hint(dock, qtbot):
    w, svc = dock
    # pick the ILOFAR source so _current_source has an example_range
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).key == "ilofar":
            w.source_combo.setCurrentIndex(i)
            break
    w.start_picker.setDateTime(_qdt(2017, 9, 6))
    w.end_picker.setDateTime(_qdt(2017, 9, 7))
    w.fetch_button.click()        # sets _current_source = ILOFAR
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit([])   # zero rows, no error
    assert w.results_table.rowCount() == 0
    assert "2021-09-07" in w.status_label.text()


def test_search_failure_shows_status(dock, qtbot):
    w, svc = dock
    with qtbot.waitSignal(w._status_changed, timeout=1000):
        svc.searchFailed.emit("nope")
    assert "nope" in w.status_label.text()


def test_plot_selected_registers_virtual_product_and_plots_on_panel(dock, qtbot, tmp_path, monkeypatch):
    """When a fetch completes, each path → SpeasyVariable → VirtualProduct → panel.plot(vp)."""
    w, svc = dock
    p = tmp_path / "example_0.cdf"
    p.write_bytes(b"\x00")

    fake_var = MagicMock(name="speasy_variable")
    monkeypatch.setattr("sciqlop_radio.dock.open_spectrogram", lambda path: MagicMock())
    monkeypatch.setattr(
        "sciqlop_radio.dock.spectrogram_to_speasy_variable", lambda spec: fake_var
    )

    panel = MagicMock(name="panel")
    fake_vp = MagicMock(name="virtual_product")
    create_panel_calls = []
    vp_calls = []

    import sys
    import types as _types
    fake_user_api_plot = _types.ModuleType("SciQLop.user_api.plot")
    fake_user_api_plot.create_plot_panel = lambda: (create_panel_calls.append(1) or panel)
    fake_user_api_vp = _types.ModuleType("SciQLop.user_api.virtual_products")
    fake_user_api_vp.create_virtual_product = lambda *a, **kw: (vp_calls.append((a, kw)) or fake_vp)

    class _VPT:
        Spectrogram = "Spectrogram"

    fake_user_api_vp.VirtualProductType = _VPT
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.plot", fake_user_api_plot)
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.virtual_products", fake_user_api_vp)

    svc.fetchCompleted.emit([p], [])
    qtbot.wait(50)

    assert len(vp_calls) == 1
    args, kwargs = vp_calls[0]
    assert args[0].startswith("radio/")
    assert args[0].endswith("/example_0")
    assert args[2] == _VPT.Spectrogram
    panel.plot.assert_called_once_with(fake_vp)


def test_station_filter_hides_other_stations(dock, qtbot):
    w, svc = dock
    rows = [
        _erow("https://a/BIR_1.fit.gz", "BIR"),
        _erow("https://a/ALMATY_1.fit.gz", "ALMATY"),
        _erow("https://a/BIR_2.fit.gz", "BIR"),
    ]
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit(rows)
    idx = w.station_filter.findText("ALMATY")
    assert idx >= 0
    w.station_filter.setCurrentIndex(idx)
    visible = [i for i in range(w.results_table.rowCount())
               if not w.results_table.isRowHidden(i)]
    assert len(visible) == 1
    assert w._table_station(visible[0]) == "ALMATY"


def test_text_filter_matches_filename(dock, qtbot):
    w, svc = dock
    rows = [_erow("https://a/BIR_1.fit.gz", "BIR"),
            _erow("https://a/ALMATY_1.fit.gz", "ALMATY")]
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit(rows)
    w.text_filter.setText("almaty")
    visible = [i for i in range(w.results_table.rowCount())
               if not w.results_table.isRowHidden(i)]
    assert len(visible) == 1
    assert "ALMATY" in w._table_filename(visible[0])


def _qdt(y, m, d):
    from PySide6.QtCore import QDateTime
    return QDateTime(y, m, d, 0, 0, 0)


def test_advanced_structured_query(dock):
    w, svc = dock
    w.advanced_group.setChecked(True)
    w.adv_instrument.setCurrentText("ILOFAR")
    w.adv_wl_min.setText("20")
    w.adv_wl_max.setText("100")
    w.start_picker.setDateTime(_qdt(2021, 9, 1))
    w.end_picker.setDateTime(_qdt(2021, 9, 10))
    w.fetch_button.click()
    q = svc.search_calls[-1]
    assert q.instrument == "ILOFAR"
    assert q.wavelength_min_mhz == 20.0
    assert q.wavelength_max_mhz == 100.0
    assert q.expect_spectrogram is True


def test_advanced_raw_query_sets_raw_and_keeps_all_rows(dock):
    w, svc = dock
    w.advanced_group.setChecked(True)
    w.adv_raw.setText("a.Time('2021-09-01','2021-09-10'), a.Instrument('ILOFAR')")
    w.fetch_button.click()
    q = svc.search_calls[-1]
    assert q.raw_attrs_text.startswith("a.Time(")
    assert q.expect_spectrogram is False


def test_advanced_instrument_resolves_to_source_for_labeling_and_hint(dock, qtbot):
    """An advanced structured query whose instrument matches a curated source
    must reuse that source — so fetched files are labeled with its key and the
    empty-results hint shows its example_range (the ILOFAR fix in advanced mode)."""
    w, svc = dock
    w.advanced_group.setChecked(True)
    w.adv_instrument.setCurrentText("ILOFAR")
    w.start_picker.setDateTime(_qdt(2017, 9, 6))
    w.end_picker.setDateTime(_qdt(2017, 9, 7))
    w.fetch_button.click()
    assert w._current_source is not None and w._current_source.key == "ilofar"
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit([])
    assert "2021-09-07" in w.status_label.text()


def test_advanced_unknown_instrument_has_no_source(dock):
    w, svc = dock
    w.advanced_group.setChecked(True)
    w.adv_instrument.setCurrentText("SOMETHING_EXOTIC")
    w.fetch_button.click()
    assert w._current_source is None


def test_curated_source_fetched_files_use_streaming_vp(dock, qtbot, tmp_path, monkeypatch):
    """A fetched eCALLISTO file registers a live stream keyed by station+focus,
    at radio/ecallisto/<station>/<focus> — not a per-file static snapshot."""
    import types as _t
    w, svc = dock
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).key == "ecallisto":
            w.source_combo.setCurrentIndex(i)
            break
    w.fetch_button.click()  # sets _current_source = eCALLISTO

    fn = "AUSTRALIA-ASSA_20110607_120000_01.fit.gz"
    p = tmp_path / fn
    p.write_bytes(b"\x00")
    w._pending_rows = [_crow(f"http://a/{fn}", "AUSTRALIA-ASSA", "01")]
    monkeypatch.setattr("sciqlop_radio.dock._open_and_convert",
                        lambda path: _t.SimpleNamespace(name=path.name))
    monkeypatch.setattr("sciqlop_radio.dock.frequency_signature", lambda v: ("ecal",))
    panel, vp_calls = _install_fake_user_api(monkeypatch)

    svc.fetchCompleted.emit([p], [])
    qtbot.wait(50)

    assert len(vp_calls) == 1
    assert vp_calls[0][0] == "radio/ecallisto/AUSTRALIA-ASSA/01"
    assert panel.plot.call_count == 1


def test_local_file_uses_static_vp(dock, qtbot, tmp_path, monkeypatch):
    """Local files (no active source) produce a static VP with a file-stem path."""
    import types as _t
    w, svc = dock

    p = tmp_path / "my_local_spec.cdf"
    p.write_bytes(b"\x00")
    monkeypatch.setattr("sciqlop_radio.dock._open_and_convert",
                        lambda path: _t.SimpleNamespace(name=path.name))
    monkeypatch.setattr("sciqlop_radio.dock.frequency_signature", lambda v: ("local",))
    monkeypatch.setattr("sciqlop_radio.dock.concat_variables_along_time", lambda vs: vs[0])

    panel, vp_calls = _install_fake_user_api(monkeypatch)

    svc.fetchCompleted.emit([p], [])
    qtbot.wait(50)

    assert len(vp_calls) == 1, "local files use static create_virtual_product"


def test_ilofar_dat_filename_is_supported():
    """ILOFAR mode-357 BST files are .dat; they must not be filtered out as
    'non-spectrogram' (radiospectra parses them via Spectrogram(path))."""
    from sciqlop_radio.dock import _is_supported_filename
    assert _is_supported_filename("20210901_080729_bst_00X.dat")
    assert _is_supported_filename("20210901_080729_bst_00Y.dat")


def _install_fake_user_api(monkeypatch):
    """Fake SciQLop.user_api.{plot,virtual_products}; return (panel, vp_calls)."""
    import sys, types as _t
    panel = MagicMock(name="panel")
    vp_calls = []
    fp = _t.ModuleType("SciQLop.user_api.plot")
    fp.create_plot_panel = lambda: panel
    fv = _t.ModuleType("SciQLop.user_api.virtual_products")
    fv.create_virtual_product = lambda *a, **k: (vp_calls.append(a) or MagicMock())

    class _VPT:
        Spectrogram = "Spectrogram"

    fv.VirtualProductType = _VPT
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.plot", fp)
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.virtual_products", fv)
    return panel, vp_calls


def test_same_frequency_files_merge_into_one_plot(dock, qtbot, tmp_path, monkeypatch):
    import types as _t
    w, svc = dock
    p1 = tmp_path / "a.cdf"; p1.write_bytes(b"\x00")
    p2 = tmp_path / "b.cdf"; p2.write_bytes(b"\x00")
    monkeypatch.setattr("sciqlop_radio.dock._open_and_convert",
                        lambda path: _t.SimpleNamespace(name=path.name))
    monkeypatch.setattr("sciqlop_radio.dock.frequency_signature", lambda v: ("same",))
    concat_calls = []
    monkeypatch.setattr("sciqlop_radio.dock.concat_variables_along_time",
                        lambda vs: (concat_calls.append(list(vs)) or _t.SimpleNamespace(name="merged")))
    panel, vp_calls = _install_fake_user_api(monkeypatch)

    svc.fetchCompleted.emit([p1, p2], [])
    qtbot.wait(50)

    assert len(vp_calls) == 1, "same-frequency files must merge into one plot"
    assert len(concat_calls) == 1 and len(concat_calls[0]) == 2
    panel.plot.assert_called_once()


def test_different_frequency_files_plot_separately(dock, qtbot, tmp_path, monkeypatch):
    import types as _t
    w, svc = dock
    p1 = tmp_path / "a.cdf"; p1.write_bytes(b"\x00")
    p2 = tmp_path / "b.cdf"; p2.write_bytes(b"\x00")
    monkeypatch.setattr("sciqlop_radio.dock._open_and_convert",
                        lambda path: _t.SimpleNamespace(name=path.name))
    monkeypatch.setattr("sciqlop_radio.dock.frequency_signature", lambda v: (v.name,))  # distinct
    concat_calls = []
    monkeypatch.setattr("sciqlop_radio.dock.concat_variables_along_time",
                        lambda vs: (concat_calls.append(vs) or _t.SimpleNamespace(name="merged")))
    panel, vp_calls = _install_fake_user_api(monkeypatch)

    svc.fetchCompleted.emit([p1, p2], [])
    qtbot.wait(50)

    assert len(vp_calls) == 2, "different-frequency files must plot separately"
    assert concat_calls == [], "no merge across different frequency grids"
    assert panel.plot.call_count == 2


def test_selected_rows_excludes_rows_hidden_by_filter(dock, qtbot):
    """Hiding a row via the filter must not leave it 'selected' for plotting.
    Select-all then filter: only the still-visible rows count as selected."""
    w, svc = dock
    rows = [
        _erow("https://a/BIR_1.fit.gz", "BIR"),
        _erow("https://a/ALMATY_1.fit.gz", "ALMATY"),
        _erow("https://a/BIR_2.fit.gz", "BIR"),
    ]
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit(rows)
    w.results_table.selectAll()                       # all 3 selected
    idx = w.station_filter.findText("ALMATY")
    w.station_filter.setCurrentIndex(idx)             # hides the 2 BIR rows
    sel = w._selected_rows()
    assert len(sel) == 1, "hidden (filtered-out) rows must not be returned as selected"
    assert sel[0]["url"].endswith("ALMATY_1.fit.gz")


def test_selected_rows_correct_objects_after_sort(dock, qtbot):
    """After sorting, _selected_rows must return the row objects at the
    selected visual positions (UserRole travels with the sorted item)."""
    w, svc = dock
    rows = [
        _erow("https://a/c.fit.gz", "C", "2021-09-03 00:00"),
        _erow("https://a/a.fit.gz", "A", "2021-09-01 00:00"),
        _erow("https://a/b.fit.gz", "B", "2021-09-02 00:00"),
    ]
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit(rows)
    w.results_table.sortItems(0)                      # sort by Start Time asc
    w.results_table.selectRow(0)                      # earliest -> a.fit.gz
    sel = w._selected_rows()
    assert len(sel) == 1
    assert sel[0]["url"].endswith("a.fit.gz")


def test_ecallisto_focus_codes_stream_separately(dock, qtbot, tmp_path, monkeypatch):
    """Two focus codes (_01/_02) at the same station/time -> two distinct streams."""
    import types as _t
    w, svc = dock
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).key == "ecallisto":
            w.source_combo.setCurrentIndex(i)
            break
    w.fetch_button.click()

    f1 = "BIR_20110607_120000_01.fit.gz"
    f2 = "BIR_20110607_120000_02.fit.gz"
    p1 = tmp_path / f1; p1.write_bytes(b"\x00")
    p2 = tmp_path / f2; p2.write_bytes(b"\x00")
    w._pending_rows = [_crow(f"http://a/{f1}", "BIR", "01"),
                       _crow(f"http://a/{f2}", "BIR", "02")]
    monkeypatch.setattr("sciqlop_radio.dock._open_and_convert",
                        lambda path: _t.SimpleNamespace(name=path.name))
    monkeypatch.setattr("sciqlop_radio.dock.frequency_signature", lambda v: (v.name,))
    panel, vp_calls = _install_fake_user_api(monkeypatch)

    svc.fetchCompleted.emit([p1, p2], [])
    qtbot.wait(50)

    paths = sorted(c[0] for c in vp_calls)
    assert paths == ["radio/ecallisto/BIR/01", "radio/ecallisto/BIR/02"]
    assert panel.plot.call_count == 2


def test_ecallisto_same_station_focus_merge_into_one_stream(dock, qtbot, tmp_path, monkeypatch):
    """Same station + focus at different times -> one stream node, one plot."""
    import types as _t
    w, svc = dock
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).key == "ecallisto":
            w.source_combo.setCurrentIndex(i)
            break
    w.fetch_button.click()

    f1 = "BIR_20110607_120000_01.fit.gz"
    f2 = "BIR_20110607_121500_01.fit.gz"
    p1 = tmp_path / f1; p1.write_bytes(b"\x00")
    p2 = tmp_path / f2; p2.write_bytes(b"\x00")
    w._pending_rows = [_crow(f"http://a/{f1}", "BIR", "01"),
                       _crow(f"http://a/{f2}", "BIR", "01")]
    monkeypatch.setattr("sciqlop_radio.dock._open_and_convert",
                        lambda path: _t.SimpleNamespace(name=path.name))
    monkeypatch.setattr("sciqlop_radio.dock.frequency_signature", lambda v: ("ecal",))
    panel, vp_calls = _install_fake_user_api(monkeypatch)

    svc.fetchCompleted.emit([p1, p2], [])
    qtbot.wait(50)

    assert [c[0] for c in vp_calls] == ["radio/ecallisto/BIR/01"]
    assert panel.plot.call_count == 1
