"""Tests for sciqlop_sismo.dock (Qt-headless via pytest-qt)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from obspy.core.inventory import Channel, Inventory, Network, Station


@pytest.fixture
def fake_inventory():
    chan = Channel(
        code="HHZ", location_code="00", latitude=45.0, longitude=5.0,
        elevation=600.0, depth=0.0, sample_rate=100.0,
        start_date=datetime(2010, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    sta = Station(
        code="SSB", latitude=45.0, longitude=5.0, elevation=600.0,
        channels=[chan],
    )
    net = Network(code="G", stations=[sta])
    return Inventory(networks=[net], source="test")


@pytest.fixture
def mock_provider():
    return MagicMock()


@pytest.fixture
def dock(qtbot, mock_provider):
    from sciqlop_sismo.dock import SismoBrowserDock
    w = SismoBrowserDock(provider=mock_provider)
    qtbot.addWidget(w)
    return w


def test_dock_has_three_tabs(dock):
    assert dock.tab_widget.count() == 3
    tab_titles = [dock.tab_widget.tabText(i) for i in range(3)]
    assert tab_titles == ["Stations", "Events", "Local files"]


def test_stations_tab_search_calls_fdsn_client(qtbot, dock, fake_inventory):
    tab = dock.stations_tab
    tab.network_edit.setText("G")
    tab.station_edit.setText("SSB")
    tab.channel_edit.setText("HHZ")
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory) as ss:
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    ss.assert_called_once()
    kwargs = ss.call_args.kwargs
    assert kwargs["network"] == "G"
    assert kwargs["station"] == "SSB"
    assert kwargs["channel"] == "HHZ"


def test_search_results_populate_tree(qtbot, dock, fake_inventory):
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    assert model.rowCount() >= 1
    net_index = model.index(0, 0)
    assert model.data(net_index) == "G"


def test_add_to_inventory_calls_provider(qtbot, dock, fake_inventory, mock_provider):
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    net = model.index(0, 0)
    sta = model.index(0, 0, net)
    chan = model.index(0, 0, sta)
    sel = tab.results_tree.selectionModel()
    sel.select(chan, sel.SelectionFlag.ClearAndSelect | sel.SelectionFlag.Rows)
    qtbot.mouseClick(tab.add_button, _Qt_LeftButton())
    mock_provider.add_channel.assert_called_once()
    kwargs = mock_provider.add_channel.call_args.kwargs
    assert kwargs["network"] == "G"
    assert kwargs["station"] == "SSB"
    assert kwargs["location"] == "00"
    assert kwargs["channel"] == "HHZ"


def test_search_error_lands_in_status_bar(qtbot, dock):
    tab = dock.stations_tab
    with patch(
        "sciqlop_sismo.dock_stations.search_stations",
        side_effect=RuntimeError("boom"),
    ):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    assert "boom" in dock.status_label.text()


def _Qt_LeftButton():
    from PySide6.QtCore import Qt
    return Qt.MouseButton.LeftButton


def test_plot_waveform_calls_create_plot_panel(qtbot, dock, fake_inventory, mock_provider):
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    chan = model.index(0, 0, model.index(0, 0, model.index(0, 0)))
    sel = tab.results_tree.selectionModel()
    sel.select(chan, sel.SelectionFlag.ClearAndSelect | sel.SelectionFlag.Rows)
    panel = MagicMock()
    with patch("sciqlop_sismo.dock_stations._create_plot_panel", return_value=panel) as cpp:
        qtbot.mouseClick(tab.plot_waveform_button, _Qt_LeftButton())
    cpp.assert_called_once()
    panel.plot_function.assert_called_once()
    args, kwargs = panel.plot_function.call_args
    assert callable(args[0])


def test_plot_spectrogram_uses_spectrogram_uid(qtbot, dock, fake_inventory, mock_provider):
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    chan = model.index(0, 0, model.index(0, 0, model.index(0, 0)))
    sel = tab.results_tree.selectionModel()
    sel.select(chan, sel.SelectionFlag.ClearAndSelect | sel.SelectionFlag.Rows)
    panel = MagicMock()
    with patch("sciqlop_sismo.dock_stations._create_plot_panel", return_value=panel):
        qtbot.mouseClick(tab.plot_spectrogram_button, _Qt_LeftButton())
    panel.plot_function.assert_called_once()
    args, kwargs = panel.plot_function.call_args
    assert callable(args[0])


def test_plot_buttons_noop_when_create_plot_panel_unavailable(qtbot, dock, fake_inventory, mock_provider):
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    chan = model.index(0, 0, model.index(0, 0, model.index(0, 0)))
    sel = tab.results_tree.selectionModel()
    sel.select(chan, sel.SelectionFlag.ClearAndSelect | sel.SelectionFlag.Rows)
    with patch("sciqlop_sismo.dock_stations._create_plot_panel", side_effect=ImportError):
        qtbot.mouseClick(tab.plot_waveform_button, _Qt_LeftButton())
    assert "SciQLop" in dock.status_label.text() or "unavailable" in dock.status_label.text().lower()


@pytest.fixture
def fake_catalog():
    from unittest.mock import MagicMock
    event = MagicMock()
    origin = MagicMock()
    origin.time = MagicMock()
    origin.time.datetime = datetime(2024, 4, 2, 14, 0, tzinfo=timezone.utc)
    origin.latitude = 45.0
    origin.longitude = 5.0
    origin.depth = 10000.0
    magnitude = MagicMock()
    magnitude.mag = 5.5
    event.preferred_origin = MagicMock(return_value=origin)
    event.preferred_magnitude = MagicMock(return_value=magnitude)
    cat = MagicMock()
    cat.__iter__ = MagicMock(return_value=iter([event]))
    cat.__len__ = MagicMock(return_value=1)
    return cat


def test_events_tab_search_events_populates_table(qtbot, dock, fake_catalog):
    tab = dock.events_tab
    with patch("sciqlop_sismo.dock_events.search_events", return_value=fake_catalog) as se:
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    se.assert_called_once()
    assert tab.events_table.rowCount() == 1
    assert "5.5" in tab.events_table.item(0, 4).text()


def test_find_stations_uses_event_coordinates(qtbot, dock, fake_catalog, fake_inventory):
    tab = dock.events_tab
    with patch("sciqlop_sismo.dock_events.search_events", return_value=fake_catalog):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    tab.events_table.selectRow(0)
    with patch("sciqlop_sismo.dock_events.search_stations", return_value=fake_inventory) as ss:
        with qtbot.waitSignal(tab.stations_finished, timeout=5000):
            qtbot.mouseClick(tab.find_stations_button, _Qt_LeftButton())
    kwargs = ss.call_args.kwargs
    assert kwargs["latitude"] == 45.0
    assert kwargs["longitude"] == 5.0


def test_local_tab_open_file_calls_provider(qtbot, dock, mock_provider, tmp_path):
    import numpy as np
    from obspy import Trace, UTCDateTime
    fp = tmp_path / "x.mseed"
    Trace(
        data=np.zeros(100, dtype=np.float32),
        header={
            "network": "XX", "station": "TEST", "location": "00",
            "channel": "HHZ", "sampling_rate": 100.0,
            "starttime": UTCDateTime("2026-01-01T00:00:00"),
        },
    ).write(str(fp), format="MSEED")
    tab = dock.local_tab
    with patch(
        "sciqlop_sismo.dock_local.QFileDialog.getOpenFileNames",
        return_value=([str(fp)], "Seismic files (*.mseed *.sac)"),
    ):
        qtbot.mouseClick(tab.open_button, _Qt_LeftButton())
    mock_provider.add_channel_from_local.assert_called_once()
    info = mock_provider.add_channel_from_local.call_args.args[0]
    assert info.network == "XX"
