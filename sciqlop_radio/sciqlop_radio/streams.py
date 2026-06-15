"""Pure stream-identity logic for live per-channel radio products.

A *stream* is one physical signal chain: an instrument at a station running a
particular receiver/focus code. The dock turns each fetched search-result group
into one stream so dragging it to any time range re-fetches that channel.

No Qt, no SciQLop imports here. The only function that touches sunpy/radiospectra
(`stream_fido_attrs`) imports them lazily at call time.
"""
from __future__ import annotations

from dataclasses import dataclass

from .fetch import _row_field


@dataclass(frozen=True)
class StreamRule:
    """Per-instrument rules for how a stream is identified and searched.

    `per_station`   — this instrument has many stations; key streams by station.
    `server_side`   — also pass `radiospectra.net.Observatory` so the archive
                      filters by station (eCALLISTO has hundreds of stations;
                      RSTN has five, so we just filter client-side for it).
    `channel_column`— Fido column carrying the sub-station channel token
                      (eCALLISTO focus code lives in the `ID` column).
    """

    per_station: bool = False
    server_side: bool = False
    channel_column: str | None = None


# Keyed by RadioSource.key. Anything absent is single-channel (one stream).
STREAM_RULES: dict[str, StreamRule] = {
    "ecallisto": StreamRule(per_station=True, server_side=True, channel_column="ID"),
    "rstn": StreamRule(per_station=True, server_side=False, channel_column=None),
}

_DEFAULT_RULE = StreamRule()


def rule_for(source_key: str) -> StreamRule:
    return STREAM_RULES.get(source_key, _DEFAULT_RULE)


def _sanitize(token: str) -> str:
    return token.strip().replace("/", "_").replace(" ", "_")


@dataclass(frozen=True)
class StreamIdentity:
    source_key: str       # curated RadioSource.key, e.g. "ecallisto"
    instrument: str       # sunpy a.Instrument value, e.g. "eCALLISTO"
    station: str = ""     # Observatory column value ("" = single-station)
    channel: str = ""     # channel token, e.g. focus code ("" = single-channel)

    @property
    def vp_path(self) -> str:
        parts = ["radio", self.source_key]
        if self.station:
            parts.append(_sanitize(self.station))
        if self.channel:
            parts.append(_sanitize(self.channel))
        return "/".join(parts)


def stream_identity_for_row(row, source) -> StreamIdentity:
    """Derive the stream identity of a fetched Fido `row` under its `source`."""
    rule = rule_for(source.key)
    station = _row_field(row, "Observatory") if rule.per_station else ""
    channel = _row_field(row, rule.channel_column) if rule.channel_column else ""
    return StreamIdentity(
        source_key=source.key,
        instrument=source.fido_instrument or "",
        station=station,
        channel=channel,
    )


def stream_fido_attrs(identity: StreamIdentity) -> list:
    """sunpy/radiospectra attrs scoping this stream's search (excluding a.Time).

    Imports sunpy/radiospectra lazily — only fires when the stream callback runs.
    Uses `radiospectra.net.Observatory` (NOT `sunpy.net.attrs.Observatory`, which
    is absent in sunpy 7.1.2) for server-side station filtering where supported.
    """
    from sunpy.net import attrs as a  # type: ignore

    attrs: list = []
    if identity.instrument:
        attrs.append(a.Instrument(identity.instrument))
    rule = rule_for(identity.source_key)
    if rule.server_side and identity.station:
        from radiospectra.net import Observatory  # type: ignore
        attrs.append(Observatory(identity.station))
    return attrs
