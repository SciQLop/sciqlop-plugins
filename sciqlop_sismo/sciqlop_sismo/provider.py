"""Speasy provider for FDSN seismic waveforms."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml
from speasy.core import AllowedKwargs, AnyDateTimeType
from speasy.core.dataprovider import (
    GET_DATA_ALLOWED_KWARGS,
    DataProvider,
)
from speasy.core.inventory.indexes import (
    DatasetIndex,
    ParameterIndex,
    SpeasyIndex,
)
from speasy.products.variable import SpeasyVariable

from .fdsn_client import fetch_stream
from .local_files import ChannelInfo
from .process import default_pipeline
from .settings import SismoSettings
from .stream_to_variable import (
    spectrogram_from_stream,
    stream_to_speasy_variable,
)

PROVIDER_NAME = "sismo"


def _inventory_dir() -> Path:
    override = os.environ.get("SCIQLOP_SISMO_INVENTORY_DIR")
    if override:
        return Path(override)
    return Path.home() / ".config" / "sciqlop" / "sismo"


def _inventory_path() -> Path:
    return _inventory_dir() / "inventory.yaml"


def _to_iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso_utc(s) -> datetime:
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class SismoProvider(DataProvider):
    """FDSN waveforms exposed as Speasy variables.

    One channel → one DatasetIndex → three ParameterIndex children
    (`waveform`, `raw`, `spectrogram`).
    """

    def __init__(self, settings: Optional[SismoSettings] = None):
        self._settings = settings or SismoSettings()
        # Must be set before DataProvider.__init__ because that calls
        # update_inventory() → build_inventory() immediately.
        self._pending_records: list[dict] = []
        DataProvider.__init__(
            self,
            provider_name=PROVIDER_NAME,
            provider_alt_names=["seismic", "fdsn"],
            inventory_disable_proxy=True,
        )

    # ----- DataProvider hooks ------------------------------------------------

    def build_inventory(self, root: SpeasyIndex) -> SpeasyIndex:
        for record in self._reload_pending_from_yaml():
            self._materialize_record(root, record)
        return root

    @AllowedKwargs(GET_DATA_ALLOWED_KWARGS)
    def get_data(
        self,
        product,
        start_time: AnyDateTimeType,
        stop_time: AnyDateTimeType,
        **kwargs,
    ) -> Optional[SpeasyVariable]:
        param = self._to_parameter_index(product)
        meta = param.__dict__
        kind = meta.get("kind")
        nslc = tuple(meta["nslc"])
        routing = meta.get("routing", "iris-federator")
        t0 = _coerce_datetime(start_time)
        t1 = _coerce_datetime(stop_time)
        stream = self._fetch_stream_for_meta(meta, nslc, t0, t1, routing)
        channel = nslc[3]
        if kind == "raw":
            return stream_to_speasy_variable(stream, channel=channel, units="counts")
        if kind == "waveform":
            processed = default_pipeline(stream, self._settings)
            return stream_to_speasy_variable(processed, channel=channel, units="m/s")
        if kind == "spectrogram":
            processed = default_pipeline(stream, self._settings)
            return spectrogram_from_stream(processed, channel=channel)
        raise ValueError(f"unknown kind: {kind!r}")

    # ----- Public API for the dock ------------------------------------------

    def add_channel(
        self,
        network: str,
        station: str,
        location: str,
        channel: str,
        start_date: datetime,
        stop_date: datetime,
        sampling_rate_hz: float,
        routing: str = "iris-federator",
    ) -> None:
        record = {
            "network": network, "station": station, "location": location,
            "channel": channel,
            "start_date": _to_iso_utc(start_date), "stop_date": _to_iso_utc(stop_date),
            "sampling_rate_hz": float(sampling_rate_hz), "routing": routing,
        }
        self._upsert_record(record)
        self.update_inventory()

    def add_channel_from_local(self, info: ChannelInfo) -> None:
        record = {
            "network": info.network, "station": info.station,
            "location": info.location, "channel": info.channel,
            "start_date": _to_iso_utc(info.start_date),
            "stop_date": _to_iso_utc(info.stop_date),
            "sampling_rate_hz": info.sampling_rate_hz,
            "routing": info.routing,
            "path": str(info.path) if info.path else None,
        }
        self._upsert_record(record)
        self.update_inventory()

    def remove_channel(
        self, network: str, station: str, location: str, channel: str
    ) -> None:
        key = (network, station, location, channel)
        self._pending_records = [
            r for r in self._pending_records
            if (r["network"], r["station"], r["location"], r["channel"]) != key
        ]
        self._persist_records()
        self.update_inventory()

    # ----- Internals --------------------------------------------------------

    def _reload_pending_from_yaml(self) -> list[dict]:
        """Refresh `_pending_records` from disk and return a copy. Side effect: mutates `_pending_records`."""
        path = _inventory_path()
        if path.exists():
            with path.open("r") as f:
                payload = yaml.safe_load(f) or {}
            self._pending_records = list(payload.get("channels", []))
        return list(self._pending_records)

    def _persist_records(self) -> None:
        path = _inventory_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            yaml.safe_dump({"channels": self._pending_records}, f, sort_keys=False)

    def _upsert_record(self, record: dict) -> None:
        key = (record["network"], record["station"], record["location"], record["channel"])
        self._pending_records = [
            r for r in self._pending_records
            if (r["network"], r["station"], r["location"], r["channel"]) != key
        ]
        self._pending_records.append(record)
        self._persist_records()

    def _materialize_record(self, root: SpeasyIndex, record: dict) -> None:
        net = record["network"]
        sta = record["station"]
        loc = record["location"]
        chan = record["channel"]
        dataset_uid = f"sismo/{net}/{sta}/{loc}.{chan}"
        net_node = _get_or_make_child(root, net, provider=PROVIDER_NAME)
        sta_node = _get_or_make_child(net_node, sta, provider=PROVIDER_NAME)
        dataset = DatasetIndex(
            name=f"{loc}.{chan}",
            provider=PROVIDER_NAME,
            uid=dataset_uid,
            meta={
                "nslc": [net, sta, loc, chan],
                "routing": record["routing"],
                "sampling_rate_hz": record["sampling_rate_hz"],
            },
        )
        dataset.start_date = _from_iso_utc(record["start_date"])
        dataset.stop_date = _from_iso_utc(record["stop_date"])
        sta_node.__dict__[dataset.spz_name()] = dataset
        for kind, units_label in (
            ("waveform", "m/s"), ("raw", "counts"), ("spectrogram", "dB"),
        ):
            param = ParameterIndex(
                name=kind, provider=PROVIDER_NAME,
                uid=f"{dataset_uid}/{kind}",
                meta={
                    "nslc": [net, sta, loc, chan], "kind": kind,
                    "routing": record["routing"], "units": units_label,
                    "sampling_rate_hz": record["sampling_rate_hz"],
                    "path": record.get("path"),
                },
            )
            param.start_date = dataset.start_date
            param.stop_date = dataset.stop_date
            dataset.__dict__[kind] = param

    def _fetch_stream_for_meta(self, meta, nslc, t0, t1, routing):
        if routing.startswith("local:"):
            path = self._find_local_path_for(nslc, routing)
            return _read_local(path)
        return fetch_stream(nslc, t0, t1, routing=routing, timeout=self._settings.fetch_timeout_s)

    def _find_local_path_for(self, nslc, routing):
        for record in self._pending_records:
            key = (record["network"], record["station"], record["location"], record["channel"])
            if key == tuple(nslc) and record["routing"] == routing:
                path = record.get("path")
                if path:
                    return Path(path)
        raise RuntimeError(f"no local file remembered for {nslc} ({routing})")


def _get_or_make_child(parent: SpeasyIndex, name: str, provider: str) -> SpeasyIndex:
    if name in parent.__dict__:
        return parent.__dict__[name]
    node = SpeasyIndex(name=name, provider=provider, uid=f"{parent.spz_uid()}/{name}")
    parent.__dict__[name] = node
    return node


def _coerce_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    import numpy as np
    import obspy
    # np.datetime64 → ISO string so obspy.UTCDateTime doesn't misroute it
    if isinstance(value, np.datetime64):
        value = str(value)
    return datetime.fromtimestamp(obspy.UTCDateTime(value).timestamp, tz=timezone.utc)


def _read_local(path: Path):
    import obspy
    return obspy.read(str(path))
