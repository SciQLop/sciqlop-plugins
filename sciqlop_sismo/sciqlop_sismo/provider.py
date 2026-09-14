"""Speasy provider for FDSN seismic waveforms."""
from __future__ import annotations

import logging
import os
import re
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
from .worker import raw_cache_key
from .stream_to_variable import (
    spectrogram_from_stream,
    stream_to_speasy_variable,
    variable_to_stream,
)
from speasy.core.cache import Cacheable

PROVIDER_NAME = "sismo"

log = logging.getLogger(__name__)


def _absolutize_path(path) -> Optional[str]:
    """Absolutize a local-file ingest path at registration so worker snapshots
    (and later processes) resolve the same file regardless of cwd."""
    if not path:
        return None
    return str(Path(path).absolute())


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

    def __init__(self, settings: Optional[SismoSettings] = None, *, vp_factory=None):
        self._settings = settings or SismoSettings()
        # Factory for live virtual products (radio-like registration goes
        # through `virtual_products.register_channel_virtual_products`).
        # None selects the real Easy* factory; tests inject a fake.
        self._vp_factory = vp_factory
        # Must be set before DataProvider.__init__ because that calls
        # update_inventory() → build_inventory() immediately.
        self._pending_records: list[dict] = []
        # Keep VirtualProduct references alive — SciQLop's product tree owns
        # them weakly via the callback; losing the Python wrapper drops the node.
        self._virtual_products: dict[str, object] = {}
        # Frozen registration snapshot per VP path. Guards idempotency:
        # re-registering an unchanged channel is a no-op (no duplicate
        # nodes/callbacks), while a changed snapshot re-registers (replace).
        self._vp_snapshots: dict[str, dict] = {}
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
            # Persisted channels must get their live virtual products at
            # startup, mirroring radio which registers at load. Idempotent:
            # unchanged channels are skipped inside `_register_virtual_products`.
            self._register_virtual_products(record)
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
        channel = nslc[3]

        stream = self._raw_stream(meta, nslc, t0, t1, routing)
        if stream is None or len(stream) == 0:
            return None

        if kind == "raw":
            return stream_to_speasy_variable(stream, channel=channel, units="counts")
        if kind == "waveform":
            processed = default_pipeline(stream, self._settings)
            return stream_to_speasy_variable(processed, channel=channel, units="m/s")
        if kind == "spectrogram":
            processed = default_pipeline(stream, self._settings)
            return spectrogram_from_stream(processed, channel=channel)
        raise ValueError(f"unknown kind: {kind!r}")

    def _raw_stream(self, meta, nslc, t0, t1, routing):
        """Raw, kind-independent waveform stream for the requested window.

        Local files are read directly (already on disk). Remote FDSN data goes
        through the range-aware Speasy cache, keyed on the dataset uid so the
        three derived products of a channel share one fetch, and re-visited time
        windows reassemble from cached hourly fragments instead of re-fetching.
        Processing (detrend/filter/STFT) runs downstream on the assembled
        window, so caching never introduces fragment-boundary seams.
        """
        if routing.startswith("local:"):
            return self._fetch_stream_for_meta(meta, nslc, t0, t1, routing)
        dataset_uid = f"{nslc[0]}/{nslc[1]}/{nslc[2]}.{nslc[3]}"
        counts = self._get_raw_counts(
            raw_cache_key(dataset_uid, routing), t0, t1, nslc=nslc, routing=routing
        )
        if counts is None:
            return None
        return variable_to_stream(counts, nslc, meta.get("sampling_rate_hz"))

    @Cacheable(prefix="sismo", fragment_hours=lambda product: 1)
    def _get_raw_counts(
        self, product, start_time, stop_time, *, nslc=None, routing=None
    ):
        """Range-aware-cached raw counts for one channel + routing.

        `product` is the route-aware cache key (`worker.raw_cache_key`), so
        the three kinds of one channel+routing share one fetch while a
        routing change misses the old route's fragments and refetches.
        `nslc`/`routing` ride along as kwargs for the fetch; when absent
        they fall back to the stored channel record.

        Returns None for a window with no data so a gap doesn't fail the whole
        request — Speasy's fragment cache stores nothing for a None fragment."""
        from obspy.clients.fdsn.header import FDSNNoDataException

        if nslc is None or routing is None:
            record = self._record_for_dataset_uid(product)
            nslc = (record["network"], record["station"],
                    record["location"], record["channel"])
            routing = record["routing"]
        try:
            stream = fetch_stream(
                tuple(nslc), start_time, stop_time, routing=routing,
                timeout=self._settings.fetch_timeout_s, allow_empty=True,
            )
        except FDSNNoDataException:
            return None
        if len(stream) == 0:
            return None
        return stream_to_speasy_variable(stream, channel=tuple(nslc)[3], units="counts")

    def _record_for_dataset_uid(self, uid: str) -> dict:
        bare = uid.split("#", 1)[0]
        for r in self._pending_records:
            if f"{r['network']}/{r['station']}/{r['location']}.{r['channel']}" == bare:
                return r
        raise RuntimeError(f"no channel record for dataset uid {uid!r}")

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
        *,
        defer_refresh: bool = False,
    ) -> None:
        record = {
            "network": network, "station": station, "location": location,
            "channel": channel,
            "start_date": _to_iso_utc(start_date), "stop_date": _to_iso_utc(stop_date),
            "sampling_rate_hz": float(sampling_rate_hz), "routing": routing,
        }
        replaced = self._upsert_record(record)
        self._invalidate_stale_route_cache(replaced, record)
        self._register_virtual_products(record)
        if not defer_refresh:
            self.update_inventory()

    def add_channel_from_local(self, info: ChannelInfo, *, defer_refresh: bool = False) -> None:
        record = {
            "network": info.network, "station": info.station,
            "location": info.location, "channel": info.channel,
            "start_date": _to_iso_utc(info.start_date),
            "stop_date": _to_iso_utc(info.stop_date),
            "sampling_rate_hz": info.sampling_rate_hz,
            "routing": info.routing,
            "path": _absolutize_path(info.path) if info.path else None,
        }
        replaced = self._upsert_record(record)
        self._invalidate_stale_route_cache(replaced, record)
        self._register_virtual_products(record)
        if not defer_refresh:
            self.update_inventory()

    def remove_channel(
        self, network: str, station: str, location: str, channel: str
    ) -> None:
        """Drop a channel from the inventory and our live-product bookkeeping.

        Removes local refs (pending record, VirtualProduct wrappers,
        registration snapshots) and rebuilds the Speasy inventory, so
        re-adding the same channel later re-registers cleanly (replace,
        never collide).

        Residual limitation: neither SciQLop's product registry
        (`VPRegistry`: register/get only) nor its out-of-process
        `RemoteRegistry` (register only, no remove) offers unregistration,
        and the product-tree node added by `EasyProvider` has no Python-side
        removal API — so the remote specs and tree nodes of a removed
        channel persist until SciQLop restarts. They simply go unused: our
        callbacks are dropped here and the worker never re-reads the yaml.
        """
        key = (network, station, location, channel)
        self._pending_records = [
            r for r in self._pending_records
            if (r["network"], r["station"], r["location"], r["channel"]) != key
        ]
        self._persist_records()
        # Drop our VirtualProduct refs for this channel; SciQLop will reap them.
        prefix = f"sismo/{key[0]}/{key[1]}/{key[2]}.{key[3]}/"
        for path in [p for p in self._virtual_products if p.startswith(prefix)]:
            self._virtual_products.pop(path, None)
            self._vp_snapshots.pop(path, None)
        self.update_inventory()

    # ----- Virtual-product registration -------------------------------------

    def _register_virtual_products(self, record: dict) -> None:
        """Register the channel's waveform/raw/spectrogram in SciQLop's product
        tree with per-kind metadata/labels and `out_of_process=True`, so the
        fetch/filter/STFT work runs in SciQLop's worker process.

        The live callback captures only the plain snapshot frozen here
        (see `virtual_products.build_live_callback`) — never this provider.
        Silently skips when SciQLop isn't importable (headless tests). The
        dock's direct-plot path keeps calling `get_data` in-process.

        Idempotent: kinds whose frozen snapshot is unchanged since the last
        successful registration are skipped (no duplicate nodes/callbacks),
        so `build_inventory` re-registering persisted channels at startup and
        `add_channel` re-registering before `update_inventory` are both safe.
        A changed snapshot (routing, path, bandpass, timeout, ...) re-registers
        that kind, replacing our wrapper ref.
        """
        try:
            from .virtual_products import KIND_PATHS, register_channel_virtual_products
        except ImportError:
            return
        snapshot = dict(
            record,
            path=_absolutize_path(record.get("path")),
            bandpass_min_hz=self._settings.bandpass_min_hz,
            bandpass_max_hz=self._settings.bandpass_max_hz,
            fetch_timeout_s=self._settings.fetch_timeout_s,
        )
        prefix = (
            f"sismo/{record['network']}/{record['station']}/"
            f"{record['location']}.{record['channel']}/"
        )
        kinds = tuple(
            kind
            for kind in KIND_PATHS
            if self._vp_snapshots.get(prefix + kind) != snapshot
            or (prefix + kind) not in self._virtual_products
        )
        if not kinds:
            return
        try:
            registered = register_channel_virtual_products(
                snapshot,
                kinds=kinds,
                vp_factory=self._vp_factory,
                out_of_process=True,
            )
        except ImportError:
            return
        except Exception:  # noqa: BLE001
            log.exception(
                "sismo VP registration failed for %s/%s/%s.%s",
                record["network"],
                record["station"],
                record["location"],
                record["channel"],
            )
            return
        self._virtual_products.update(registered)
        for path in registered:
            self._vp_snapshots[path] = dict(snapshot)

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

    def _upsert_record(self, record: dict) -> Optional[dict]:
        """Replace any stored record for this channel; return the replaced one."""
        key = (record["network"], record["station"], record["location"], record["channel"])
        replaced = next(
            (
                r
                for r in self._pending_records
                if (r["network"], r["station"], r["location"], r["channel"]) == key
            ),
            None,
        )
        self._pending_records = [
            r for r in self._pending_records
            if (r["network"], r["station"], r["location"], r["channel"]) != key
        ]
        self._pending_records.append(record)
        self._persist_records()
        return replaced

    def _invalidate_stale_route_cache(self, old: Optional[dict], new: dict) -> None:
        """Drop the previous routing's cached fragments on a route change.

        The route-aware cache key already retires old-route fragments (they
        simply miss); this explicit drop just frees the disk entries early.
        Best-effort: cache failures never break channel registration.
        """
        if old is None or old.get("routing") == new.get("routing"):
            return
        old_routing = old.get("routing") or ""
        if old_routing.startswith("local:"):
            return
        dataset_uid = (
            f"{new['network']}/{new['station']}/{new['location']}.{new['channel']}"
        )
        try:
            from speasy.core.cache import drop_matching_entries

            drop_matching_entries(
                re.compile(
                    re.escape(f"sismo/{raw_cache_key(dataset_uid, old_routing)}/")
                    + ".*"
                )
            )
        except Exception:  # noqa: BLE001
            log.debug("sismo: stale route cache drop failed", exc_info=True)

    def _materialize_record(self, root: SpeasyIndex, record: dict) -> None:
        net = record["network"]
        sta = record["station"]
        loc = record["location"]
        chan = record["channel"]
        dataset_uid = f"{net}/{sta}/{loc}.{chan}"
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
            try:
                path = self._find_local_path_for(nslc, routing)
            except RuntimeError:
                return None
            if path is None:
                return None
            try:
                if not path.is_file():
                    return None
            except OSError:
                return None
            try:
                return _read_local(path)
            except Exception:  # noqa: BLE001
                # Corrupt/unreadable files yield None (with a warning), never
                # raise into the data path — matching the worker snapshot read.
                log.warning("sismo: cannot read local file %s", path)
                return None
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
