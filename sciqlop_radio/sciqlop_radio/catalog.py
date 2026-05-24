"""Curated catalog of space-mission radio dynamic-spectra sourced from Speasy.

A declarative `radio_catalog.yaml` lists products that already exist in
Speasy (AMDA/CDAWeb). At plugin load each resolvable entry is registered as a
`VirtualProductType.Spectrogram` (or vector/scalar/multicomponent) virtual
product under `radio/<path>`, whose callback fetches via `speasy.get_data`.
Spectrogram styling is inherited from the returned SpeasyVariable's metadata.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Union

from pydantic import BaseModel, field_validator, model_validator

log = logging.getLogger(__name__)

ProductType = Literal["spectrogram", "vector", "scalar", "multicomponent"]


class CuratedRadioProduct(BaseModel):
    """One catalog entry: a Speasy product re-surfaced under radio/<path>."""

    path: str
    speasy_id: str
    type: ProductType = "spectrogram"
    label: Optional[str] = None
    labels: Optional[list[str]] = None

    @field_validator("path")
    @classmethod
    def _clean_path(cls, v: str) -> str:
        v = v.strip().strip("/").strip()
        if not v:
            raise ValueError("path must be non-blank")
        return v

    @field_validator("speasy_id")
    @classmethod
    def _check_speasy_id(cls, v: str) -> str:
        v = v.strip()
        provider, sep, uid = v.partition("/")
        provider, uid = provider.strip(), uid.strip()
        if not sep or not provider or not uid:
            raise ValueError("speasy_id must be '<provider>/<uid>'")
        return f"{provider}/{uid}"

    @model_validator(mode="after")
    def _finalize(self) -> "CuratedRadioProduct":
        if self.type != "spectrogram" and not self.labels:
            raise ValueError(f"labels required for type={self.type!r}")
        if self.label is None:
            self.label = self.path
        return self


def load_catalog(path: Union[str, Path]) -> list[CuratedRadioProduct]:
    """Read + validate the YAML catalog. Fail-soft: missing file or top-level
    parse error -> []; a malformed entry is logged and skipped, others kept."""
    p = Path(path)
    if not p.exists():
        return []
    import yaml

    try:
        raw = yaml.safe_load(p.read_text()) or []
    except yaml.YAMLError as exc:
        log.error("catalog: failed to parse %s: %s", p, exc)
        return []
    if not isinstance(raw, list):
        log.error("catalog: %s must be a YAML list, got %s", p, type(raw).__name__)
        return []

    out: list[CuratedRadioProduct] = []
    for i, item in enumerate(raw):
        try:
            out.append(CuratedRadioProduct(**item))
        except Exception as exc:  # noqa: BLE001 — ValidationError or bad mapping
            log.warning("catalog: skipping entry %d (%r): %s", i, item, exc)
    return out



_TYPE_TO_VP = {
    "spectrogram": "Spectrogram",
    "vector": "Vector",
    "scalar": "Scalar",
    "multicomponent": "MultiComponent",
}


def _resolves(speasy_id: str, speasy_module) -> bool:
    """True if `<provider>/<uid>` is present in the in-memory Speasy inventory.

    SciQLop's speasy_provider builds the inventories at startup (before our
    load() runs), so this is a dict lookup, not a network call."""
    provider, _, uid = speasy_id.partition("/")
    flat = getattr(speasy_module.inventories.flat_inventories, provider, None)
    if flat is None:
        return False
    params = getattr(flat, "parameters", None) or {}
    return uid in params


def _vp_type_for(entry_type: str, vp_types):
    """Map a catalog `type` string to a SciQLop VirtualProductType member."""
    return getattr(vp_types, _TYPE_TO_VP[entry_type])


def _build_callback(entry: "CuratedRadioProduct", speasy_module):
    """Return SciQLop's `(start, stop, **kwargs) -> SpeasyVariable | None`
    callback. Never raises into SciQLop's data thread."""

    def _cb(start, stop, **kwargs):  # noqa: ARG001 — accept SciQLop knobs
        t0 = datetime.fromtimestamp(float(start), tz=timezone.utc)
        t1 = datetime.fromtimestamp(float(stop), tz=timezone.utc)
        try:
            return speasy_module.get_data(entry.speasy_id, t0, t1)
        except Exception as exc:  # noqa: BLE001
            log.warning("catalog(%s): get_data failed: %s", entry.path, exc)
            return None

    return _cb


@dataclass
class CatalogRegistration:
    """Live handle on the registered catalog VPs — keeps them alive vs GC."""

    vps: dict[str, Any] = field(default_factory=dict)


def _register_entries(
    entries: list["CuratedRadioProduct"],
    create_vp: Callable[..., Any],
    vp_types,
    speasy_module,
) -> CatalogRegistration:
    reg = CatalogRegistration()
    for e in entries:
        if not _resolves(e.speasy_id, speasy_module):
            log.info("catalog: skip %s — %s not in Speasy inventory", e.path, e.speasy_id)
            continue
        vptype = _vp_type_for(e.type, vp_types)
        cb = _build_callback(e, speasy_module)
        path = f"radio/{e.path}"
        try:
            if e.type == "spectrogram":
                vp = create_vp(path, cb, vptype)
            else:
                vp = create_vp(path, cb, vptype, labels=e.labels)
        except Exception as exc:  # noqa: BLE001
            log.exception("catalog: create_virtual_product failed for %s: %s", path, exc)
            continue
        reg.vps[path] = vp
    return reg


def register_catalog_products(
    catalog_path: Union[str, Path], *, speasy_module=None
) -> Optional[CatalogRegistration]:
    """Read the catalog and register one virtual product per resolvable entry.

    Returns an empty `CatalogRegistration` when the catalog is empty/missing,
    and `None` when SciQLop's virtual-products API isn't importable (headless
    tests) — mirroring `continuous.register_continuous_products`."""
    entries = load_catalog(catalog_path)
    if not entries:
        return CatalogRegistration()
    try:
        from SciQLop.user_api.virtual_products import (
            create_virtual_product,
            VirtualProductType,
        )
    except ImportError as exc:
        log.warning("catalog: SciQLop user_api unavailable: %s", exc)
        return None
    if speasy_module is None:
        import speasy as speasy_module  # noqa: PLW0127
    return _register_entries(entries, create_virtual_product, VirtualProductType, speasy_module)
