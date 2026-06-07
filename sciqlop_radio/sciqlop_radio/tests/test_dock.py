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


def test_search_results_populate_list(dock, qtbot):
    w, svc = dock
    row = MagicMock()
    row.url = "https://archive/example_0.cdf"
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit([row])
    assert w.results_list.count() == 1
    assert "example_0.cdf" in w.results_list.item(0).text()


def test_search_drops_non_spectrogram_results(dock, qtbot):
    w, svc = dock
    rows = []
    for url in (
        "https://archive/swaves_tds_tdsmax_20240612.txt",      # not a spectrogram
        "https://archive/psp_rfs_20240612.cdf",                # spectrogram
        "https://archive/callisto_20240612.fit.gz",            # spectrogram
        "https://archive/something_else.bin",                  # not a spectrogram
    ):
        r = MagicMock()
        r.url = url
        rows.append(r)
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit(rows)
    assert w.results_list.count() == 2
    names = [w.results_list.item(i).text() for i in range(w.results_list.count())]
    assert not any(n.endswith(".txt") or n.endswith(".bin") for n in names)
    assert "2 non-spectrogram" in w.status_label.text()


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


def _qdt(y, m, d):
    from PySide6.QtCore import QDateTime
    return QDateTime(y, m, d, 0, 0, 0)
