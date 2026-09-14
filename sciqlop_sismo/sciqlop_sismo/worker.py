"""Worker-safe sismo fetch/process callbacks for out-of-process virtual products.

Snapshot policy (explicit): the live callback captures only plain data —
the NSLC tuple, kind, routing, sampling rate, an absolutized local path,
and frozen bandpass/timeout floats. It never captures the SismoProvider,
Qt objects, or SciQLop virtual products, so it survives pickling into
SciQLop's worker process.

The worker never re-reads `inventory.yaml`: channel add/remove
re-registers (or drops) the virtual products in-process, so a worker
invocation always runs against the snapshot frozen at registration time.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from speasy.core.cache import Cacheable
from speasy.products.variable import SpeasyVariable

from .fdsn_client import fetch_stream
from .process import bandpass, detrend
from .stream_to_variable import (
    spectrogram_from_stream,
    stream_to_speasy_variable,
    variable_to_stream,
)

log = logging.getLogger(__name__)

KINDS = ("waveform", "raw", "spectrogram")


def raw_cache_key(dataset_uid: str, routing: str) -> str:
    """Range-cache product key for one channel + routing.

    Speasy's default cache entry name ignores extra kwargs, so the routing
    must be folded into the `product` string itself — otherwise changing a
    channel's routing reuses the previous route's cached fragments. The kind
    stays out of the key so raw/waveform/spectrogram of one channel+routing
    share a single fetch. Shared with `provider.py` (same function object).
    """
    digest = hashlib.sha256(routing.encode("utf-8")).hexdigest()[:8]
    return f"{dataset_uid}#routing={digest}"


_fetch_locks_guard = threading.Lock()
_fetch_locks: dict[str, threading.Lock] = {}


def _fetch_lock_for(dataset_uid: str) -> threading.Lock:
    """One lock per channel so concurrent in-process requests for the same
    dataset never duplicate a live fetch.

    Per-process only: each out-of-process worker has its own lock table, so
    this provides no cross-process exclusion — cross-process dedup comes
    from the shared speasy disk cache underneath `_cached_raw_counts`."""
    with _fetch_locks_guard:
        return _fetch_locks.setdefault(dataset_uid, threading.Lock())


class _RawCountsCache:
    """Method-style holder so speasy's `Cacheable` (which wraps
    `(self, product, start_time, stop_time, ...)`) keeps its range-aware
    fragment behavior. One module-level instance; never pickled — the
    worker process re-imports this module fresh."""

    @Cacheable(prefix="sismo", fragment_hours=lambda product: 1)
    def raw_counts(
        self, product, start_time, stop_time, *, nslc, routing, timeout_s
    ) -> Optional[SpeasyVariable]:
        """Range-aware-cached raw counts for one channel (dataset uid `product`).

        Returns None for a window with no data so a gap doesn't fail the whole
        request — Speasy's fragment cache stores nothing for a None fragment."""
        from obspy.clients.fdsn.header import FDSNNoDataException

        try:
            stream = fetch_stream(
                tuple(nslc),
                start_time,
                stop_time,
                routing=routing,
                timeout=timeout_s,
                allow_empty=True,
            )
        except FDSNNoDataException:
            return None
        if len(stream) == 0:
            return None
        return stream_to_speasy_variable(stream, channel=nslc[3], units="counts")


_RAW_COUNTS = _RawCountsCache()


def _read_local_snapshot(path: Optional[str]):
    """Read a snapshotted local file. None when the path is missing (or
    unreadable) — never raises into the data path."""
    if not path:
        return None
    file_path = Path(path)
    try:
        if not file_path.is_file():
            return None
    except OSError:
        return None
    import obspy

    try:
        return obspy.read(str(file_path))
    except Exception:  # noqa: BLE001
        log.warning("sismo worker: cannot read local file %s", file_path)
        return None


def sismo_worker_callback(
    start: float,
    stop: float,
    *,
    nslc,
    kind: str,
    routing: str,
    sampling_rate_hz: float,
    path: Optional[str],
    bandpass_min_hz: float,
    bandpass_max_hz: float,
    fetch_timeout_s: float,
) -> Optional[SpeasyVariable]:
    """Module-level `(start, stop) → SpeasyVariable | None` worker callback.

    All keyword arguments are plain picklable data frozen at registration.
    Fetches the cached raw stream once per channel, then branches into
    raw/waveform/spectrogram without refetching. Any failure yields None,
    matching the virtual-product callback contract.
    """
    try:
        t0 = datetime.fromtimestamp(float(start), tz=timezone.utc)
        t1 = datetime.fromtimestamp(float(stop), tz=timezone.utc)
        nslc = tuple(nslc)
        channel = nslc[3]
        if routing.startswith("local:"):
            stream = _read_local_snapshot(path)
        else:
            dataset_uid = f"{nslc[0]}/{nslc[1]}/{nslc[2]}.{nslc[3]}"
            cache_key = raw_cache_key(dataset_uid, routing)
            with _fetch_lock_for(cache_key):
                counts = _RAW_COUNTS.raw_counts(
                    cache_key,
                    t0,
                    t1,
                    nslc=nslc,
                    routing=routing,
                    timeout_s=fetch_timeout_s,
                )
            if counts is None:
                return None
            stream = variable_to_stream(counts, nslc, float(sampling_rate_hz))
        if stream is None or len(stream) == 0:
            return None
        if kind == "raw":
            return stream_to_speasy_variable(stream, channel=channel, units="counts")
        processed = bandpass(
            detrend(stream, type="demean"),
            fmin=float(bandpass_min_hz),
            fmax=float(bandpass_max_hz),
        )
        if kind == "waveform":
            return stream_to_speasy_variable(processed, channel=channel, units="m/s")
        if kind == "spectrogram":
            return spectrogram_from_stream(processed, channel=channel)
        raise ValueError(f"unknown kind: {kind!r}")
    except Exception:  # noqa: BLE001
        log.exception("sismo worker callback failed for %s/%s", nslc, kind)
        return None
