"""Read local miniSEED / SAC files into channel descriptors.

Channel descriptors are pure data (`ChannelInfo`); injecting them into
the Speasy provider's inventory is the provider's job (Task 7).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import obspy


@dataclass(frozen=True)
class ChannelInfo:
    network: str
    station: str
    location: str
    channel: str
    sampling_rate_hz: float
    start_date: datetime
    stop_date: datetime
    routing: str
    path: Path | None = None


def _to_aware_utc(utc_dt: obspy.UTCDateTime) -> datetime:
    return datetime.fromtimestamp(utc_dt.timestamp, tz=timezone.utc)


def _sha1_of_path(p: Path) -> str:
    return hashlib.sha1(str(p.resolve()).encode("utf-8")).hexdigest()


def import_file(path: Path) -> List[ChannelInfo]:
    """Read a miniSEED / SAC file and return one ChannelInfo per channel."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    stream = obspy.read(str(p))
    if len(stream) == 0:
        raise ValueError(f"no traces in {p}")
    routing = f"local:{_sha1_of_path(p)}"
    out: List[ChannelInfo] = []
    seen: set[tuple[str, str, str, str]] = set()
    for tr in stream:
        st = tr.stats
        key = (st.network, st.station, st.location, st.channel)
        if key in seen:
            continue
        seen.add(key)
        out.append(ChannelInfo(
            network=st.network,
            station=st.station,
            location=st.location,
            channel=st.channel,
            sampling_rate_hz=float(st.sampling_rate),
            start_date=_to_aware_utc(st.starttime),
            stop_date=_to_aware_utc(st.endtime),
            routing=routing,
            path=p,
        ))
    return out
