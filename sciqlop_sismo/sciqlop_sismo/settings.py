"""Project-wide settings for sciqlop_sismo.

Bounded numeric fields clamp on load (per `feedback_configentry_clamp_bounds`)
so stale YAML never crashes a panel.
"""
from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator


def _default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "sciqlop" / "sismo"


class SismoSettings(BaseModel):
    default_routing: str = Field(default="iris-federator")
    bandpass_min_hz: float = Field(default=0.01)
    bandpass_max_hz: float = Field(default=10.0)
    cache_retention_days: int = Field(default=7)
    stationxml_cache_hours: int = Field(default=12)
    search_timeout_s: int = Field(default=60)
    fetch_timeout_s: int = Field(default=120)
    cache_dir: Path = Field(default_factory=_default_cache_dir)

    @field_validator("default_routing", mode="before")
    @classmethod
    def _lowercase_routing(cls, v):
        return str(v).lower()

    @field_validator("bandpass_min_hz", "bandpass_max_hz", mode="before")
    @classmethod
    def _clamp_band(cls, v):
        return max(0.0, min(1000.0, float(v)))

    @field_validator("cache_retention_days", mode="before")
    @classmethod
    def _clamp_retention(cls, v):
        return max(0, min(365, int(v)))

    @field_validator("stationxml_cache_hours", mode="before")
    @classmethod
    def _clamp_xml_hours(cls, v):
        return max(0, min(24 * 30, int(v)))

    @field_validator("search_timeout_s", "fetch_timeout_s", mode="before")
    @classmethod
    def _clamp_timeout(cls, v):
        return max(1, min(3600, int(v)))

    @model_validator(mode="after")
    def _swap_band_if_inverted(self):
        if self.bandpass_min_hz > self.bandpass_max_hz:
            self.bandpass_min_hz, self.bandpass_max_hz = (
                self.bandpass_max_hz,
                self.bandpass_min_hz,
            )
        return self
