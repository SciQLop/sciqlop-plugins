"""Thin wrapper around ObsPy's FDSN clients.

`routing` is a string:
  - "iris-federator" or "eida-routing" → `RoutingClient`
  - any other value (e.g. "IRIS", "RESIF", "GEOFON") → `Client`
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Optional, Tuple

from obspy import Inventory, Stream, UTCDateTime
from obspy.clients.fdsn import Client, RoutingClient
from obspy.clients.fdsn.header import FDSNNoDataException

_KNOWN_ROUTERS = {"iris-federator", "eida-routing"}


def _client_for(routing: str, timeout: float | None = None):
    if routing.lower() in _KNOWN_ROUTERS:
        return RoutingClient(routing.lower(), timeout=timeout) if timeout else RoutingClient(routing.lower())
    return Client(routing, timeout=timeout) if timeout else Client(routing)


def _to_utc(dt: datetime) -> UTCDateTime:
    return UTCDateTime(dt.timestamp())


def fetch_stream(
    nslc: Tuple[str, str, str, str],
    start_time: datetime,
    end_time: datetime,
    routing: str = "iris-federator",
    timeout: float | None = None,
    *,
    allow_empty: bool = False,
) -> Stream:
    """Fetch waveforms for one NSLC tuple.

    With `allow_empty=False` (default) an empty result raises — keeps the
    imperative/UI path loud. With `allow_empty=True` a no-data response yields
    an empty `Stream` instead, which the cache layer treats as a missing
    fragment so a gap in one sub-window doesn't fail the whole request.
    """
    from obspy.clients.fdsn.header import FDSNNoDataException

    net, sta, loc, chan = nslc
    client = _client_for(routing, timeout=timeout)
    try:
        stream = client.get_waveforms(
            network=net, station=sta, location=loc, channel=chan,
            starttime=_to_utc(start_time), endtime=_to_utc(end_time),
        )
    except FDSNNoDataException:
        if allow_empty:
            return Stream()
        raise
    if len(stream) == 0 and not allow_empty:
        raise RuntimeError(
            f"no data returned for {net}.{sta}.{loc}.{chan} "
            f"between {start_time.isoformat()} and {end_time.isoformat()} (routing={routing})"
        )
    return stream


def search_stations(
    network: str, station: str, location: str, channel: str,
    start_time: datetime, end_time: datetime,
    routing: str = "iris-federator",
    timeout: float | None = None,
    *,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    min_radius_deg: Optional[float] = None,
    max_radius_deg: Optional[float] = None,
):
    """Query the FDSN station service at channel level."""
    client = _client_for(routing, timeout=timeout)
    kwargs = dict(
        network=network, station=station, location=location, channel=channel,
        starttime=_to_utc(start_time), endtime=_to_utc(end_time),
        level="channel",
    )
    if latitude is not None and longitude is not None:
        kwargs["latitude"] = latitude
        kwargs["longitude"] = longitude
    if min_radius_deg is not None:
        kwargs["minradius"] = min_radius_deg
    if max_radius_deg is not None:
        kwargs["maxradius"] = max_radius_deg
    return client.get_stations(**kwargs)


PROBE = timedelta(seconds=60)


def _probe_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """simplify: three short slices (start, middle, end) stand in for a long window, so a
    channel with data only between them is hidden. Upgrade path: query fdsnws-availability
    per data centre where one exists (EarthScope retired theirs, the federator routes none)."""
    if end - start <= 3 * PROBE:
        return [(start, end)]
    middle = start + (end - start) / 2
    return [(start, start + PROBE), (middle, middle + PROBE), (end - PROBE, end)]


def _channel_codes(inv: Inventory) -> list[tuple[str, str, str, str]]:
    return [(n.code, s.code, c.location_code, c.code) for n in inv for s in n for c in s]


def _keep_channels(inv: Inventory, codes: set) -> Inventory:
    kept = copy.deepcopy(inv)
    for net in kept:
        for sta in net:
            sta.channels = [c for c in sta if (net.code, sta.code, c.location_code, c.code) in codes]
        net.stations = [sta for sta in net if sta.channels]
    kept.networks = [net for net in kept if net.stations]
    return kept


def drop_channels_without_data(inv: Inventory, start: datetime, end: datetime, routing: str,
                               timeout: float | None = None) -> tuple[Inventory, int]:
    """(channels that return samples for [start, end], how many were dropped).

    The station service filters on metadata epochs only: a channel can be "installed"
    for the window while its data centre serves no samples (restricted or never
    archived — e.g. most CB channels through the federator). One routed bulk
    dataselect request is the only check every data centre answers."""
    codes = _channel_codes(inv)
    if not codes:
        return inv, 0
    bulk = [(*code, _to_utc(a), _to_utc(b)) for code in codes for a, b in _probe_windows(start, end)]
    try:
        stream = _client_for(routing, timeout=timeout).get_waveforms_bulk(bulk)
    except FDSNNoDataException:
        stream = Stream()
    with_data = {(tr.stats.network, tr.stats.station, tr.stats.location, tr.stats.channel)
                 for tr in stream}
    return _keep_channels(inv, with_data), len(set(codes) - with_data)


def search_events(
    start_time: datetime, end_time: datetime,
    *,
    min_magnitude: Optional[float] = None,
    min_lat: Optional[float] = None, max_lat: Optional[float] = None,
    min_lon: Optional[float] = None, max_lon: Optional[float] = None,
    latitude: Optional[float] = None, longitude: Optional[float] = None,
    min_radius_deg: Optional[float] = None, max_radius_deg: Optional[float] = None,
    provider: str = "USGS",
    timeout: float | None = None,
):
    """Query an FDSN event service. `provider` is an FDSN-event center."""
    client = Client(provider, timeout=timeout) if timeout else Client(provider)
    kwargs = dict(starttime=_to_utc(start_time), endtime=_to_utc(end_time))
    if min_magnitude is not None:
        kwargs["minmagnitude"] = min_magnitude
    if min_lat is not None: kwargs["minlatitude"] = min_lat
    if max_lat is not None: kwargs["maxlatitude"] = max_lat
    if min_lon is not None: kwargs["minlongitude"] = min_lon
    if max_lon is not None: kwargs["maxlongitude"] = max_lon
    if latitude is not None: kwargs["latitude"] = latitude
    if longitude is not None: kwargs["longitude"] = longitude
    if min_radius_deg is not None: kwargs["minradius"] = min_radius_deg
    if max_radius_deg is not None: kwargs["maxradius"] = max_radius_deg
    return client.get_events(**kwargs)
