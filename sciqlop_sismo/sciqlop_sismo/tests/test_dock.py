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
