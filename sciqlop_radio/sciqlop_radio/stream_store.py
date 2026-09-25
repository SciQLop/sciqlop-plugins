"""Persist dock-registered live streams so they survive a SciQLop restart.

The dock registers a stream (`streams.StreamIdentity`) lazily, the first
time a fetched search result is plotted (see `dock.py:_finalize_group`).
Without this module that registration lives only in memory: after a
restart the product-tree node is gone, so a saved panel template that
references it can't be reloaded (`load()` re-registers `CONTINUOUS_SOURCES`
but has never heard of, say, `radio/e-CALLISTO/BIR/59`).

`save_stream` records one entry every time the dock registers a stream;
`register_continuous_products` (continuous.py) calls `load_saved_streams`
at plugin load to re-register every remembered one. Entries self-clean on
load: schema-invalid, from a source the plugin no longer knows (renamed or
removed from `sources.py`), or unused for about a year are dropped and the
file is rewritten without them.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .sources import SOURCES
from .streams import StreamIdentity

log = logging.getLogger(__name__)

_MAX_AGE_S = 365 * 86400  # drop entries unused for about a year


class SavedStream(BaseModel):
    """Just enough to rebuild a `StreamIdentity` and its frequency filter."""

    source_key: str
    instrument: str = ""
    station: str = ""
    channel: str = ""
    path_name: str = ""
    freq_signature: list | None = None
    last_used: float = 0.0

    def to_identity(self) -> StreamIdentity:
        return StreamIdentity(
            source_key=self.source_key, instrument=self.instrument,
            station=self.station, channel=self.channel, path_name=self.path_name,
        )

    @property
    def freq_signature_tuple(self) -> tuple | None:
        """`ContinuousSource.freq_signature` is compared with `==` against
        `frequency_signature()`'s tuple output — JSON round-trips it as a
        list, which would never compare equal, so callers must go through
        this instead of the raw field."""
        return tuple(self.freq_signature) if self.freq_signature is not None else None


def _known_source_keys() -> set[str]:
    return {s.key for s in SOURCES}


def _read_raw(path: Path) -> list[dict]:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _write(path: Path, entries: list[SavedStream]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps([e.model_dump() for e in entries], indent=2))
    tmp.replace(path)


def _is_worth_keeping(entry: SavedStream, now: float) -> bool:
    if entry.source_key not in _known_source_keys():
        log.info("stream_store: dropping entry for unknown source %r", entry.source_key)
        return False
    if now - entry.last_used > _MAX_AGE_S:
        log.info("stream_store: dropping stale entry %r (unused > 1y)",
                 entry.to_identity().vp_path)
        return False
    return True


def load_saved_streams(path: Path, *, now: float | None = None) -> list[SavedStream]:
    """Streams worth restoring. Rewrites the file when any entry is dropped,
    so a renamed/removed source or a stale entry cleans up on the next load
    rather than lingering forever."""
    now = time.time() if now is None else now
    raw = _read_raw(path)
    kept: list[SavedStream] = []
    for item in raw:
        try:
            entry = SavedStream.model_validate(item)
        except ValidationError as exc:
            log.warning("stream_store: dropping invalid entry: %s", exc)
            continue
        if _is_worth_keeping(entry, now):
            kept.append(entry)
    if len(kept) != len(raw):
        _write(path, kept)
    return kept


def save_stream(path: Path, identity: StreamIdentity, freq_signature,
                *, now: float | None = None) -> None:
    """Upsert one entry keyed by `identity.vp_path`, refreshing `last_used`."""
    now = time.time() if now is None else now
    by_path = {e.to_identity().vp_path: e for e in load_saved_streams(path, now=now)}
    by_path[identity.vp_path] = SavedStream(
        source_key=identity.source_key, instrument=identity.instrument,
        station=identity.station, channel=identity.channel,
        path_name=identity.path_name,
        freq_signature=list(freq_signature) if freq_signature is not None else None,
        last_used=now,
    )
    _write(path, list(by_path.values()))


def forget_all(path: Path) -> None:
    """Drop every remembered stream. Takes effect on the next restart —
    SciQLop has no live product-removal API yet (see SciQLop backlog.md,
    'Virtual products' — `remove_virtual_product()`)."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
