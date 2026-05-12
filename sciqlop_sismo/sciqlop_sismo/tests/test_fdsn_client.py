"""Tests for sciqlop_sismo.fdsn_client (no real network)."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from obspy import Inventory, Stream, Trace, UTCDateTime
from obspy.core.inventory import Channel, Network, Station

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
