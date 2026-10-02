"""Tests for sciqlop_sismo.fdsn_client (no real network)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from obspy import Inventory, Stream, Trace, UTCDateTime
from obspy.core.inventory import Inventory, Network

from sciqlop_sismo.fdsn_client import (
    fetch_stream,
    search_events,
    search_stations,
)


def _utc(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


@pytest.fixture
def fake_stream():
    tr = Trace(
        data=np.zeros(100, dtype=np.float32),
        header={
            "network": "IU", "station": "ANMO", "location": "00",
            "channel": "BHZ", "sampling_rate": 40.0,
            "starttime": UTCDateTime("2026-01-01T00:00:00"),
        },
    )
    return Stream([tr])


def test_fetch_stream_uses_routing_client_by_default(fake_stream):
    with patch("sciqlop_sismo.fdsn_client.RoutingClient") as RC:
        client = MagicMock()
        client.get_waveforms.return_value = fake_stream
        RC.return_value = client
        out = fetch_stream(
            ("IU", "ANMO", "00", "BHZ"),
            _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1),
            routing="iris-federator",
        )
    RC.assert_called_once_with("iris-federator")
    client.get_waveforms.assert_called_once()
    args, kwargs = client.get_waveforms.call_args
    assert kwargs["network"] == "IU"
    assert kwargs["station"] == "ANMO"
    assert kwargs["location"] == "00"
    assert kwargs["channel"] == "BHZ"
    assert isinstance(kwargs["starttime"], UTCDateTime)
    assert isinstance(kwargs["endtime"], UTCDateTime)
    assert out is fake_stream


def test_fetch_stream_uses_single_center_when_routing_is_a_center_code(fake_stream):
    with patch("sciqlop_sismo.fdsn_client.Client") as Cl, \
         patch("sciqlop_sismo.fdsn_client.RoutingClient") as RC:
        client = MagicMock()
        client.get_waveforms.return_value = fake_stream
        Cl.return_value = client
        fetch_stream(
            ("IU", "ANMO", "00", "BHZ"),
            _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1),
            routing="IRIS",
        )
    Cl.assert_called_once_with("IRIS")
    RC.assert_not_called()


def test_fetch_stream_raises_on_empty_result():
    with patch("sciqlop_sismo.fdsn_client.RoutingClient") as RC:
        client = MagicMock()
        client.get_waveforms.return_value = Stream([])
        RC.return_value = client
        with pytest.raises(RuntimeError, match="no data"):
            fetch_stream(
                ("IU", "ANMO", "00", "BHZ"),
                _utc(2026, 1, 1), _utc(2026, 1, 1, 0, 1),
                routing="iris-federator",
            )


def test_search_stations_forwards_filters_and_returns_inventory():
    inv = Inventory(networks=[Network(code="IU")], source="test")
    with patch("sciqlop_sismo.fdsn_client.RoutingClient") as RC:
        client = MagicMock()
        client.get_stations.return_value = inv
        RC.return_value = client
        out = search_stations(
            network="IU", station="ANMO", location="00", channel="BHZ",
            start_time=_utc(2026, 1, 1), end_time=_utc(2026, 1, 2),
            routing="iris-federator",
        )
    assert out is inv
    args, kwargs = client.get_stations.call_args
    assert kwargs["level"] == "channel"
    assert kwargs["network"] == "IU"


def test_search_stations_passes_geographic_filters_when_given():
    with patch("sciqlop_sismo.fdsn_client.RoutingClient") as RC:
        client = MagicMock()
        client.get_stations.return_value = Inventory(networks=[], source="t")
        RC.return_value = client
        search_stations(
            network="*", station="*", location="*", channel="HHZ",
            start_time=_utc(2026, 1, 1), end_time=_utc(2026, 1, 2),
            routing="iris-federator",
            latitude=45.0, longitude=5.0,
            min_radius_deg=0.0, max_radius_deg=30.0,
        )
    kwargs = client.get_stations.call_args.kwargs
    assert kwargs["latitude"] == 45.0
    assert kwargs["longitude"] == 5.0
    assert kwargs["minradius"] == 0.0
    assert kwargs["maxradius"] == 30.0


def test_search_events_returns_catalog():
    sentinel_catalog = MagicMock()
    with patch("sciqlop_sismo.fdsn_client.Client") as Cl:
        client = MagicMock()
        client.get_events.return_value = sentinel_catalog
        Cl.return_value = client
        out = search_events(
            start_time=_utc(2026, 1, 1), end_time=_utc(2026, 1, 2),
            min_magnitude=5.0, provider="USGS",
        )
    Cl.assert_called_once_with("USGS")
    args, kwargs = client.get_events.call_args
    assert kwargs["minmagnitude"] == 5.0
    assert out is sentinel_catalog


def _inventory(*codes):
    """codes: (net, sta, loc, chan) tuples."""
    from obspy.core.inventory import Channel, Station
    nets = {}
    for net, sta, loc, chan in codes:
        stations = nets.setdefault(net, {})
        stations.setdefault(sta, []).append(Channel(
            code=chan, location_code=loc, latitude=0.0, longitude=0.0, elevation=0.0, depth=0.0))
    return Inventory(networks=[
        Network(code=net, stations=[Station(code=sta, latitude=0.0, longitude=0.0, elevation=0.0,
                                            channels=chans) for sta, chans in stations.items()])
        for net, stations in nets.items()], source="test")


def _trace(net, sta, loc, chan):
    return Trace(data=np.zeros(10), header={"network": net, "station": sta, "location": loc,
                                             "channel": chan, "sampling_rate": 1.0})


def _codes(inv):
    return sorted((n.code, s.code, c.location_code, c.code) for n in inv for s in n for c in s)


def test_channels_without_archived_data_are_dropped():
    """The station service filters on metadata epochs only: a channel can be
    "installed" for the window while its data centre has no samples for it."""
    from sciqlop_sismo.fdsn_client import drop_channels_without_data

    inv = _inventory(("IU", "ANMO", "00", "BHZ"), ("CB", "LZH", "00", "BHZ"), ("CB", "GTA", "00", "BHZ"))
    client = MagicMock()
    client.get_waveforms_bulk.return_value = Stream([_trace("IU", "ANMO", "00", "BHZ")])
    with patch("sciqlop_sismo.fdsn_client._client_for", return_value=client):
        kept, dropped = drop_channels_without_data(
            inv, _utc(2025, 3, 28, 6, 15), _utc(2025, 3, 28, 6, 45), routing="iris-federator")
    assert _codes(kept) == [("IU", "ANMO", "00", "BHZ")]
    assert dropped == 2
    assert [n.code for n in kept] == ["IU"], "a network left without channels must go too"
    assert len(_codes(inv)) == 3, "the caller's inventory is not modified"


def test_a_long_window_is_probed_with_short_slices_not_downloaded():
    from sciqlop_sismo.fdsn_client import drop_channels_without_data

    client = MagicMock()
    client.get_waveforms_bulk.return_value = Stream()
    start, end = _utc(2025, 3, 28), _utc(2025, 3, 29)
    with patch("sciqlop_sismo.fdsn_client._client_for", return_value=client):
        drop_channels_without_data(_inventory(("IU", "ANMO", "00", "BHZ")), start, end, routing="IRIS")
    bulk = client.get_waveforms_bulk.call_args.args[0]
    assert len(bulk) == 3
    assert all(line[5] - line[4] <= 60 for line in bulk)
    assert bulk[0][4] == UTCDateTime(start.timestamp()) and bulk[-1][5] == UTCDateTime(end.timestamp())


def test_no_data_anywhere_drops_everything():
    from obspy.clients.fdsn.header import FDSNNoDataException
    from sciqlop_sismo.fdsn_client import drop_channels_without_data

    client = MagicMock()
    client.get_waveforms_bulk.side_effect = FDSNNoDataException("no data")
    with patch("sciqlop_sismo.fdsn_client._client_for", return_value=client):
        kept, dropped = drop_channels_without_data(
            _inventory(("CB", "LZH", "00", "BHZ")), _utc(2025, 3, 28), _utc(2025, 3, 28, 0, 30),
            routing="iris-federator")
    assert _codes(kept) == [] and dropped == 1


def test_an_empty_search_needs_no_probe():
    from sciqlop_sismo.fdsn_client import drop_channels_without_data

    with patch("sciqlop_sismo.fdsn_client._client_for") as cf:
        kept, dropped = drop_channels_without_data(
            Inventory(networks=[], source="t"), _utc(2025, 3, 28), _utc(2025, 3, 28, 1), routing="IRIS")
    cf.assert_not_called()
    assert dropped == 0
