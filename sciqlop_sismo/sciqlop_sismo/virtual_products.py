"""Radio-like live virtual-product registration for sismo.

Each channel registers its waveform/raw/spectrogram products with the
per-kind metadata/labels/display names SciQLop's product tree needs, and
`out_of_process=True` so the fetch/filter/STFT work runs in SciQLop's
worker process instead of the GUI thread.

`create_virtual_product` takes neither `metadata` nor `out_of_process`,
so the default factory constructs the `Easy*` providers directly (same
as radio's `make_rich_vp`). Tests inject a fake `vp_factory`.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

KIND_PATHS = ("waveform", "raw", "spectrogram")


def _require_known_kind(kind: str) -> str:
    if kind not in KIND_PATHS:
        raise ValueError(f"unknown kind: {kind!r} (expected one of {KIND_PATHS})")
    return kind


def sismo_metadata_for(kind: str, record: dict) -> dict:
    """Flat primitives-only metadata for one channel kind."""
    _require_known_kind(kind)
    meta = {
        "provider": "sismo",
        "kind": kind,
        "network": record["network"],
        "station": record["station"],
        "location": record["location"],
        "channel": record["channel"],
        "routing": record["routing"],
        "sampling_rate_hz": float(record["sampling_rate_hz"]),
        "description": (
            f"Seismic {kind} "
            f"{record['network']}/{record['station']}/{record['location']}.{record['channel']}"
        ),
    }
    if kind == "spectrogram":
        meta["DISPLAY_TYPE"] = "spectrogram"
        meta["SCALETYP"] = "log"
    else:
        meta["DISPLAY_TYPE"] = "timeseries"
    return meta


def sismo_labels_for(kind: str, record: dict) -> Optional[list]:
    """Scalar kinds need exactly one label; spectrogram needs none."""
    _require_known_kind(kind)
    if kind == "spectrogram":
        return None
    return [record["channel"]]


def sismo_display_name_for(kind: str, record: dict) -> str:
    _require_known_kind(kind)
    return (
        f"{record['network']}/{record['station']}/"
        f"{record['location']}.{record['channel']} {kind}"
    )


def build_live_callback(kind: str, **snapshot):
    """Worker-safe live callback: a module-local closure over plain snapshot
    data only — no provider/Qt/VP capture.

    The closure (not `functools.partial`) carries
    `__module__ == "sciqlop_sismo.virtual_products"`, so SciQLop groups
    sismo remote products under a per-plugin worker instead of core
    SciQLop. Core transports callbacks with cloudpickle.

    `snapshot` carries nslc, routing, sampling_rate_hz, path (absolutized
    for local ingest, else None), bandpass_min_hz, bandpass_max_hz and
    fetch_timeout_s, all frozen at registration.
    """
    _require_known_kind(kind)
    from .worker import sismo_worker_callback

    frozen = dict(
        nslc=tuple(snapshot["nslc"]),
        kind=kind,
        routing=snapshot["routing"],
        sampling_rate_hz=float(snapshot["sampling_rate_hz"]),
        path=snapshot.get("path"),
        bandpass_min_hz=float(snapshot.get("bandpass_min_hz", 0.01)),
        bandpass_max_hz=float(snapshot.get("bandpass_max_hz", 10.0)),
        fetch_timeout_s=snapshot.get("fetch_timeout_s", 120),
    )

    def sismo_live_callback(start: float, stop: float):
        return sismo_worker_callback(start, stop, **frozen)

    return sismo_live_callback


def _default_vp_factory(
    path,
    callback,
    vp_type,
    *,
    metadata=None,
    labels=None,
    out_of_process=False,
    display_name=None,
):
    """Direct `Easy*` construction: `create_virtual_product` accepts neither
    `metadata` nor `out_of_process`.

    Core drops `display_name` for Scalar products (spectrogram keeps it),
    matching radio/core behavior — hence `EasyScalar` takes no
    `display_name` while `EasySpectrogram` does."""
    from SciQLop.components.plotting.backend.easy_provider import (
        EasyScalar,
        EasySpectrogram,
    )
    from SciQLop.user_api.virtual_products import VirtualProductType

    if vp_type == VirtualProductType.Scalar:
        if not labels:
            raise ValueError("Scalar requires labels=[<one_label>]")
        return EasyScalar(
            path,
            callback,
            component_name=labels[0],
            metadata=metadata or {},
            out_of_process=out_of_process,
        )
    if vp_type == VirtualProductType.Spectrogram:
        return EasySpectrogram(
            path,
            callback,
            metadata=metadata or {},
            out_of_process=out_of_process,
            display_name=display_name,
        )
    raise ValueError(f"unknown VirtualProductType: {vp_type!r}")


def register_channel_virtual_products(
    record: dict,
    *,
    kinds=KIND_PATHS,
    vp_factory=None,
    out_of_process: bool = True,
) -> dict:
    """Register one live virtual product per kind. Returns path → VP.

    Raises ImportError when SciQLop's virtual-products API isn't importable
    (headless) — the caller skips registration then. Raises ValueError for
    an unknown kind.
    """
    from SciQLop.user_api.virtual_products import VirtualProductType

    if vp_factory is None:
        vp_factory = _default_vp_factory
    net, sta, loc, chan = (
        record["network"],
        record["station"],
        record["location"],
        record["channel"],
    )
    snapshot = dict(
        nslc=(net, sta, loc, chan),
        routing=record["routing"],
        sampling_rate_hz=record["sampling_rate_hz"],
        path=record.get("path"),
        bandpass_min_hz=record.get("bandpass_min_hz", 0.01),
        bandpass_max_hz=record.get("bandpass_max_hz", 10.0),
        fetch_timeout_s=record.get("fetch_timeout_s", 120),
    )
    vp_types = {
        "waveform": VirtualProductType.Scalar,
        "raw": VirtualProductType.Scalar,
        "spectrogram": VirtualProductType.Spectrogram,
    }
    registered = {}
    for kind in kinds:
        _require_known_kind(kind)
        path = f"sismo/{net}/{sta}/{loc}.{chan}/{kind}"
        try:
            vp = vp_factory(
                path,
                build_live_callback(kind, **snapshot),
                vp_types[kind],
                metadata=sismo_metadata_for(kind, record),
                labels=sismo_labels_for(kind, record),
                out_of_process=out_of_process,
                display_name=sismo_display_name_for(kind, record),
            )
        except Exception:  # noqa: BLE001
            log.exception("sismo VP registration failed for %s", path)
            continue
        registered[path] = vp
    return registered
