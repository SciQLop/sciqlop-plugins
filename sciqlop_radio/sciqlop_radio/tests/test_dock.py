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

    def search(self, source, t_start, t_end):
        self.search_calls.append((source.key, t_start, t_end))

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


def test_fetch_button_calls_fetch_service_search(dock):
    w, svc = dock
    w.start_picker.setDateTime(_qdt(2024, 5, 1))
    w.end_picker.setDateTime(_qdt(2024, 5, 2))
    w.source_combo.setCurrentIndex(0)
    w.fetch_button.click()
    assert svc.search_calls, "fetch button did not trigger search"
    key, t0, t1 = svc.search_calls[-1]
    assert isinstance(key, str)
    assert t0 < t1


def test_search_results_populate_list(dock, qtbot):
    w, svc = dock
    row = MagicMock()
    row.url = "https://archive/example_0.cdf"
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit([row])
    assert w.results_list.count() == 1
    assert "example_0.cdf" in w.results_list.item(0).text()


def test_search_failure_shows_status(dock, qtbot):
    w, svc = dock
    with qtbot.waitSignal(w._status_changed, timeout=1000):
        svc.searchFailed.emit("nope")
    assert "nope" in w.status_label.text()


def test_plot_selected_calls_translator_for_each_path(dock, qtbot, tmp_path, monkeypatch):
    w, svc = dock
    p = tmp_path / "example_0.cdf"
    p.write_bytes(b"\x00")

    fake_spec = MagicMock()
    monkeypatch.setattr(
        "sciqlop_radio.dock.open_spectrogram", lambda path: fake_spec
    )
    rendered = []
    monkeypatch.setattr(
        "sciqlop_radio.dock.spectrogram_to_plot",
        lambda spec, parent=None: rendered.append((spec, parent)) or _make_stub_plot(),
    )

    svc.fetchCompleted.emit([p], [])
    qtbot.wait(50)

    assert len(rendered) >= 1
    assert w.tabs.count() >= 1


def _qdt(y, m, d):
    from PySide6.QtCore import QDateTime
    return QDateTime(y, m, d, 0, 0, 0)


def _make_stub_plot():
    from PySide6.QtWidgets import QLabel
    return QLabel("stub plot")
