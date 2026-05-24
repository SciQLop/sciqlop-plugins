"""Curated catalog of space-mission radio dynamic-spectra sourced from Speasy.

A declarative `radio_catalog.yaml` lists products that already exist in
Speasy (AMDA/CDAWeb). At plugin load each resolvable entry is registered as a
`VirtualProductType.Spectrogram` (or vector/scalar/multicomponent) virtual
product under `radio/<path>`, whose callback fetches via `speasy.get_data`.
Spectrogram styling is inherited from the returned SpeasyVariable's metadata.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

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
