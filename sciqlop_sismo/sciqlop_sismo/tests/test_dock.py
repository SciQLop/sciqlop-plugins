"""Tests for sciqlop_sismo.dock (Qt-headless via pytest-qt)."""
from datetime import datetime, timedelta, timezone
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


@pytest.fixture(autouse=True)
def _no_availability_probe():
    """The "Only with data" check is on by default and would hit the network:
    pass inventories through untouched unless a test patches it itself."""
    passthrough = lambda inv, *a, **k: (inv, 0)  # noqa: E731
    with patch("sciqlop_sismo.dock_stations.drop_channels_without_data", side_effect=passthrough), \
         patch("sciqlop_sismo.dock_events.drop_channels_without_data", side_effect=passthrough):
        yield


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
    # Plot either via the VirtualProduct object or by path — the dock uses
    # whichever is available.
    assert panel.plot.called or panel.plot_product.called
    if panel.plot_product.called:
        args, _ = panel.plot_product.call_args
        assert args[0] == "sismo/G/SSB/00.HHZ/waveform"


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
    assert panel.plot.called or panel.plot_product.called
    if panel.plot_product.called:
        args, _ = panel.plot_product.call_args
        assert args[0] == "sismo/G/SSB/00.HHZ/spectrogram"


def test_plot_waveform_shows_the_searched_window(qtbot, dock, fake_inventory, mock_provider):
    """A fresh panel defaults to "now", where an archive has no data yet (IU.ADK lagged ~8 h
    behind real time): the panel must show the window the user searched, which is where they
    expect data. A window longer than the panel's zoom limit widens the limit instead of
    being silently clipped by SciQLopPlots."""
    from sciqlop_sismo.dock_stations import _to_qdatetime
    tab = dock.stations_tab
    start = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)
    stop = datetime(2026, 10, 2, 10, 1, tzinfo=timezone.utc)
    tab.start_picker.setDateTime(_to_qdatetime(start))
    tab.end_picker.setDateTime(_to_qdatetime(stop))
    _search_and_select_first_channel(qtbot, tab, fake_inventory)
    panel = _SciQLopLikePanel()
    panel.zoom_limit_seconds = 3600.0

    with patch("sciqlop_sismo.dock_stations._create_plot_panel", return_value=panel), \
         patch("sciqlop_sismo.dock_stations._time_range", side_effect=lambda a, b: (a, b)):
        qtbot.mouseClick(tab.plot_waveform_button, _Qt_LeftButton())

    assert panel.time_range == (start.timestamp(), stop.timestamp())
    assert panel.zoom_limit_seconds == stop.timestamp() - start.timestamp()


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


class _SciQLopLikePanel:
    """Behaves like SciQLop's PlotPanel where it matters: plot() only takes a path, a
    user_api VirtualProduct, a callable or data, and raises for the raw EasyProvider
    objects the provider registers (a bare MagicMock accepted them and hid the bug)."""

    def __init__(self, failing_paths=()):
        self.plotted, self.time_range, self._failing = [], None, set(failing_paths)

    def plot(self, product, *args, **kwargs):
        if not isinstance(product, (str, list)):
            raise ValueError("plot() could not interpret its arguments")
        self.plotted.append(product)

    def plot_product(self, path, *args, **kwargs):
        if path in self._failing:
            raise RuntimeError("no such product")
        self.plotted.append(path)
        return MagicMock(), MagicMock()


def _search_and_select_first_channel(qtbot, tab, fake_inventory):
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=fake_inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    chan = model.index(0, 0, model.index(0, 0, model.index(0, 0)))
    sel = tab.results_tree.selectionModel()
    sel.select(chan, sel.SelectionFlag.ClearAndSelect | sel.SelectionFlag.Rows)


def test_plot_waveform_plots_registered_channels_by_path(qtbot, dock, fake_inventory, mock_provider):
    """The provider keeps raw EasyProvider objects (since the out-of-process products):
    passing them to panel.plot() raised, every plot failed, and the panel stayed empty."""
    mock_provider._virtual_products = {"sismo/G/SSB/00.HHZ/waveform": object()}
    tab = dock.stations_tab
    _search_and_select_first_channel(qtbot, tab, fake_inventory)
    panel = _SciQLopLikePanel()

    with patch("sciqlop_sismo.dock_stations._create_plot_panel", return_value=panel):
        qtbot.mouseClick(tab.plot_waveform_button, _Qt_LeftButton())

    assert panel.plotted == ["sismo/G/SSB/00.HHZ/waveform"]


def test_a_failed_plot_is_reported_not_covered_by_a_success_message(qtbot, dock, fake_inventory, mock_provider):
    tab = dock.stations_tab
    _search_and_select_first_channel(qtbot, tab, fake_inventory)
    panel = _SciQLopLikePanel(failing_paths={"sismo/G/SSB/00.HHZ/waveform"})
    messages = []
    tab._status_sink = messages.append

    with patch("sciqlop_sismo.dock_stations._create_plot_panel", return_value=panel):
        qtbot.mouseClick(tab.plot_waveform_button, _Qt_LeftButton())

    assert "failed" in messages[-1].lower() and "sismo/G/SSB/00.HHZ/waveform" in messages[-1]


def _two_station_inventory():
    """FAR first in the inventory, so ordering by distance to an event at
    (45, 5) must flip it."""
    def station(code, lat):
        chan = Channel(code="HHZ", location_code="00", latitude=lat, longitude=5.0,
                       elevation=0.0, depth=0.0, sample_rate=100.0,
                       start_date=datetime(2010, 1, 1, tzinfo=timezone.utc),
                       end_date=datetime(2099, 1, 1, tzinfo=timezone.utc))
        return Station(code=code, latitude=lat, longitude=5.0, elevation=0.0, channels=[chan])

    net = Network(code="G", stations=[station("FAR", 60.0), station("NEAR", 45.1)])
    return Inventory(networks=[net], source="test")


def _search_and_select_all_channels(qtbot, tab, inventory):
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=inventory):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    net = model.index(0, 0)
    sel = tab.results_tree.selectionModel()
    sel.clearSelection()
    for s in range(model.rowCount(net)):
        chan = model.index(0, 0, model.index(s, 0, net))
        sel.select(chan, sel.SelectionFlag.Select | sel.SelectionFlag.Rows)


def _plot_waterfall(qtbot, tab):
    panel = MagicMock()
    panel.zoom_limit_seconds = 0
    with patch("sciqlop_sismo.dock_stations._create_plot_panel", return_value=panel), \
         patch("sciqlop_sismo.dock_stations._time_range", side_effect=lambda a, b: (a, b)):
        qtbot.mouseClick(tab.plot_waterfall_button, _Qt_LeftButton())
    return panel


def _y_labels(panel):
    args, _ = panel.plots[-1].set_axis_tick_labels.call_args
    assert args[0] == "y"
    return [args[1][i] for i in sorted(args[1])]


def test_plot_waterfall_draws_one_trace_per_selected_channel(qtbot, dock):
    tab = dock.stations_tab
    _search_and_select_all_channels(qtbot, tab, _two_station_inventory())
    panel = _plot_waterfall(qtbot, tab)
    panel.waterfall.assert_called_once()
    x, y, z = panel.waterfall.call_args.args
    assert len(y) == 2 and z.shape == (2, len(x))
    assert panel.waterfall.call_args.kwargs["normalize"] is True
    assert _y_labels(panel) == ["G.FAR.00.HHZ", "G.NEAR.00.HHZ"]


def test_plot_waterfall_sorts_by_distance_to_the_selected_event(qtbot, dock, fake_catalog):
    with patch("sciqlop_sismo.dock_events.search_events", return_value=fake_catalog):
        with qtbot.waitSignal(dock.events_tab.search_finished, timeout=5000):
            qtbot.mouseClick(dock.events_tab.search_button, _Qt_LeftButton())
    dock.events_tab.events_table.selectRow(0)
    tab = dock.stations_tab
    _search_and_select_all_channels(qtbot, tab, _two_station_inventory())
    panel = _plot_waterfall(qtbot, tab)
    labels = _y_labels(panel)
    assert labels[0].startswith("G.NEAR.00.HHZ (") and labels[1].startswith("G.FAR.00.HHZ (")
    offsets = panel.waterfall.call_args.kwargs["offsets"]
    assert offsets[0] == pytest.approx(0.1, abs=0.01) and offsets[1] == pytest.approx(15.0, abs=0.01)


def test_plot_waterfall_follows_the_panel_time_range(qtbot, dock, mock_provider):
    tab = dock.stations_tab
    _search_and_select_all_channels(qtbot, tab, _two_station_inventory())
    panel = _plot_waterfall(qtbot, tab)
    panel._impl.time_range_changed.connect.assert_called_once()
    mock_provider.get_data.return_value = None
    on_range_changed = panel._impl.time_range_changed.connect.call_args.args[0]
    on_range_changed(MagicMock(start=lambda: 0.0, stop=lambda: 10.0))
    qtbot.waitUntil(lambda: mock_provider.get_data.call_count == 2, timeout=3000)
    uids = sorted(c.args[0] for c in mock_provider.get_data.call_args_list)
    assert uids == ["G/FAR/00.HHZ/waveform", "G/NEAR/00.HHZ/waveform"]


def test_plot_waterfall_is_disabled_without_waterfall_support(qtbot, mock_provider):
    with patch("sciqlop_sismo.dock_stations._waterfall_supported", return_value=False):
        from sciqlop_sismo.dock import SismoBrowserDock
        w = SismoBrowserDock(provider=mock_provider)
        qtbot.addWidget(w)
    assert not w.stations_tab.plot_waterfall_button.isEnabled()
    assert "0.13" in w.stations_tab.plot_waterfall_button.toolTip()


def test_events_tab_waterfall_sorts_stations_near_the_event(qtbot, dock, fake_catalog, mock_provider):
    """Stations found around an event plot as a record section: nearest first, over the
    event's own search window (origin - 5 min .. + 25 min), not the Stations-tab pickers."""
    tab = dock.events_tab
    with patch("sciqlop_sismo.dock_events.search_events", return_value=fake_catalog):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    tab.events_table.selectRow(0)
    with patch("sciqlop_sismo.dock_events.search_stations", return_value=_two_station_inventory()):
        with qtbot.waitSignal(tab.stations_finished, timeout=5000):
            qtbot.mouseClick(tab.find_stations_button, _Qt_LeftButton())
    tab.stations_table.selectAll()
    panel = MagicMock()
    panel.zoom_limit_seconds = 0
    with patch("sciqlop_sismo.dock_stations._create_plot_panel", return_value=panel), \
         patch("sciqlop_sismo.dock_stations._time_range", side_effect=lambda a, b: (a, b)):
        qtbot.mouseClick(tab.plot_waterfall_button, _Qt_LeftButton())
    assert [label.split(" ")[0] for label in _y_labels(panel)] == ["G.NEAR.00.HHZ", "G.FAR.00.HHZ"]
    assert panel.waterfall.call_args.kwargs["offsets"][1] == pytest.approx(15.0, abs=0.01)
    origin = datetime(2024, 4, 2, 14, 0, tzinfo=timezone.utc)
    assert panel.time_range == ((origin - timedelta(minutes=5)).timestamp(),
                                (origin + timedelta(minutes=25)).timestamp())
    assert mock_provider.add_channel.call_count == 2


def test_events_tab_waterfall_needs_a_station_selection(qtbot, dock):
    qtbot.mouseClick(dock.events_tab.plot_waterfall_button, _Qt_LeftButton())
    assert "No station rows selected" in dock.status_label.text()


def _catalog(*events):
    """events: (lat, lon, mag) tuples."""
    built = []
    for i, (lat, lon, mag) in enumerate(events):
        origin = MagicMock(latitude=lat, longitude=lon, depth=10000.0)
        origin.time.datetime = datetime(2024, 4, 2, 14, i, tzinfo=timezone.utc)
        event = MagicMock()
        event.preferred_origin = MagicMock(return_value=origin)
        event.preferred_magnitude = MagicMock(return_value=MagicMock(mag=mag))
        built.append(event)
    cat = MagicMock()
    cat.__iter__ = MagicMock(side_effect=lambda: iter(built))
    cat.__len__ = MagicMock(return_value=len(built))
    return cat


def _search_events(qtbot, tab, catalog):
    with patch("sciqlop_sismo.dock_events.search_events", return_value=catalog):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())


def _column(table, col):
    return [table.item(r, col).text() for r in range(table.rowCount())]


def test_events_sort_by_magnitude_numerically_and_keep_the_right_event(qtbot, dock):
    from PySide6.QtCore import Qt
    tab = dock.events_tab
    _search_events(qtbot, tab, _catalog((10.0, 1.0, 10.0), (20.0, 2.0, 9.5), (30.0, 3.0, 4.2)))
    assert tab.events_table.isSortingEnabled()
    tab.events_table.sortItems(4, Qt.SortOrder.AscendingOrder)
    assert _column(tab.events_table, 4) == ["4.2", "9.5", "10.0"]
    tab.events_table.selectRow(0)
    assert tab.selected_origin() == (30.0, 3.0)


def test_events_refill_while_sorted_keeps_rows_whole(qtbot, dock):
    from PySide6.QtCore import Qt
    tab = dock.events_tab
    _search_events(qtbot, tab, _catalog((10.0, 1.0, 5.0), (20.0, 2.0, 6.0)))
    tab.events_table.sortItems(4, Qt.SortOrder.DescendingOrder)
    _search_events(qtbot, tab, _catalog((1.0, 1.0, 7.0), (2.0, 2.0, 3.0), (3.0, 3.0, 5.0)))
    rows = [(_column(tab.events_table, 1)[r], _column(tab.events_table, 4)[r]) for r in range(3)]
    assert sorted(rows) == [("1.000", "7.0"), ("2.000", "3.0"), ("3.000", "5.0")]


def _rate_inventory(*rates):
    chans = [Channel(code=f"HH{i}", location_code="00", latitude=45.0, longitude=5.0,
                     elevation=0.0, depth=0.0, sample_rate=rate,
                     start_date=datetime(2010, 1, 1, tzinfo=timezone.utc),
                     end_date=datetime(2099, 1, 1, tzinfo=timezone.utc))
             for i, rate in enumerate(rates)]
    sta = Station(code="SSB", latitude=45.0, longitude=5.0, elevation=0.0, channels=chans)
    return Inventory(networks=[Network(code="G", stations=[sta])], source="test")


def test_stations_near_event_sort_by_sample_rate_numerically(qtbot, dock, fake_catalog):
    from PySide6.QtCore import Qt
    tab = dock.events_tab
    _search_events(qtbot, tab, fake_catalog)
    tab.events_table.selectRow(0)
    with patch("sciqlop_sismo.dock_events.search_stations", return_value=_rate_inventory(100.0, 20.0, 1.0)):
        with qtbot.waitSignal(tab.stations_finished, timeout=5000):
            qtbot.mouseClick(tab.find_stations_button, _Qt_LeftButton())
    assert tab.stations_table.isSortingEnabled()
    tab.stations_table.sortItems(3, Qt.SortOrder.AscendingOrder)
    assert _column(tab.stations_table, 3) == ["1.00 Hz", "20.00 Hz", "100.00 Hz"]
    tab.stations_table.selectRow(0)
    assert [r["sample_rate"] for r in tab._selected_station_rows()] == [1.0]


def test_stations_tree_sorts_channels_by_sample_rate_numerically(qtbot, dock):
    from PySide6.QtCore import Qt
    tab = dock.stations_tab
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=_rate_inventory(100.0, 20.0, 1.0)):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    assert tab.results_tree.isSortingEnabled()
    tab.results_tree.sortByColumn(1, Qt.SortOrder.AscendingOrder)
    model = tab.results_tree.model()
    sta = model.index(0, 0, model.index(0, 0))
    rates = [model.data(model.index(r, 1, sta)) for r in range(model.rowCount(sta))]
    assert rates == ["1.00 Hz", "20.00 Hz", "100.00 Hz"]
    payload = model.data(model.index(0, 0, sta), Qt.ItemDataRole.UserRole)
    assert payload["sample_rate"] == 1.0


def _find_stations_near_event(qtbot, dock, fake_catalog, inventory):
    tab = dock.events_tab
    _search_events(qtbot, tab, fake_catalog)
    tab.events_table.selectRow(0)
    with patch("sciqlop_sismo.dock_events.search_stations", return_value=inventory):
        with qtbot.waitSignal(tab.stations_finished, timeout=5000):
            qtbot.mouseClick(tab.find_stations_button, _Qt_LeftButton())
    return tab


def _keep_only(station):
    def drop(inv, start, end, routing, timeout=None):
        kept = inv.select(station=station)
        return kept, sum(len(s) for n in inv for s in n) - sum(len(s) for n in kept for s in n)
    return drop


def test_find_stations_hides_channels_without_data_by_default(qtbot, dock, fake_catalog):
    assert dock.events_tab.only_with_data_check.isChecked()
    with patch("sciqlop_sismo.dock_events.drop_channels_without_data", side_effect=_keep_only("NEAR")) as d:
        tab = _find_stations_near_event(qtbot, dock, fake_catalog, _two_station_inventory())
    assert _column(tab.stations_table, 1) == ["NEAR"]
    assert "1 without data hidden" in dock.status_label.text()
    _, start, end = d.call_args.args[:3]
    assert end - start == timedelta(minutes=30)


def test_find_stations_can_show_every_channel(qtbot, dock, fake_catalog):
    dock.events_tab.only_with_data_check.setChecked(False)
    with patch("sciqlop_sismo.dock_events.drop_channels_without_data") as d:
        tab = _find_stations_near_event(qtbot, dock, fake_catalog, _two_station_inventory())
    d.assert_not_called()
    assert sorted(_column(tab.stations_table, 1)) == ["FAR", "NEAR"]


def test_a_failed_availability_check_keeps_the_list_and_says_so(qtbot, dock, fake_catalog):
    with patch("sciqlop_sismo.dock_events.drop_channels_without_data", side_effect=TimeoutError("slow")):
        tab = _find_stations_near_event(qtbot, dock, fake_catalog, _two_station_inventory())
    assert sorted(_column(tab.stations_table, 1)) == ["FAR", "NEAR"]
    assert "couldn't check data availability" in dock.status_label.text()


def test_stations_search_hides_channels_without_data_by_default(qtbot, dock):
    tab = dock.stations_tab
    assert tab.only_with_data_check.isChecked()
    with patch("sciqlop_sismo.dock_stations.search_stations", return_value=_two_station_inventory()), \
         patch("sciqlop_sismo.dock_stations.drop_channels_without_data", side_effect=_keep_only("FAR")):
        with qtbot.waitSignal(tab.search_finished, timeout=5000):
            qtbot.mouseClick(tab.search_button, _Qt_LeftButton())
    model = tab.results_tree.model()
    net = model.index(0, 0)
    assert [model.data(model.index(r, 0, net)) for r in range(model.rowCount(net))] == ["FAR"]
    assert "1 without data hidden" in dock.status_label.text()


def test_waterfall_legend_names_each_trace(qtbot, dock):
    tab = dock.stations_tab
    _search_and_select_all_channels(qtbot, tab, _two_station_inventory())
    panel = _plot_waterfall(qtbot, tab)
    graph = panel.waterfall.return_value
    graph._impl.set_labels.assert_called_once_with(["G.FAR.00.HHZ", "G.NEAR.00.HHZ"])


def test_waterfall_y_axis_spans_every_trace(qtbot, dock, fake_catalog):
    with patch("sciqlop_sismo.dock_events.search_events", return_value=fake_catalog):
        with qtbot.waitSignal(dock.events_tab.search_finished, timeout=5000):
            qtbot.mouseClick(dock.events_tab.search_button, _Qt_LeftButton())
    dock.events_tab.events_table.selectRow(0)
    tab = dock.stations_tab
    _search_and_select_all_channels(qtbot, tab, _two_station_inventory())
    panel = _plot_waterfall(qtbot, tab)
    axis, lo, hi = panel.plots[-1].set_axis_range.call_args.args
    offsets = panel.waterfall.call_args.kwargs["offsets"]
    assert axis == "y" and lo < min(offsets) and hi > max(offsets)
