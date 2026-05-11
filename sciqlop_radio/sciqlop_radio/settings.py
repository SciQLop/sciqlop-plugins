"""sciqlop_radio plugin settings — persisted via SciQLop ConfigEntry.

Bounded numeric fields clamp on load so a stale or hand-edited YAML
value outside the declared range never crashes the settings panel.
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import Field, field_validator

from SciQLop.components.settings import SettingsCategory
from SciQLop.components.settings.backend import ConfigEntry


class RadioSettings(ConfigEntry):
    category: ClassVar = SettingsCategory.PLUGINS
    subcategory: ClassVar[str] = "Radio Spectra"

    cache_dir: Path = Field(
        default_factory=lambda: Path.home() / ".cache" / "sciqlop_radio",
        description="Directory where fetched radio files are stored",
    )
    download_timeout_s: int = Field(
        default=60,
        ge=5,
        le=600,
        description="Per-file download timeout, seconds",
    )
    parallel_downloads: int = Field(
        default=4,
        ge=1,
        le=16,
        description="Maximum parallel Fido downloads",
    )

    @field_validator("download_timeout_s", mode="before")
    @classmethod
    def _clamp_timeout(cls, v):
        try:
            return max(5, min(600, int(v)))
        except (TypeError, ValueError):
            return v

    @field_validator("parallel_downloads", mode="before")
    @classmethod
    def _clamp_parallel(cls, v):
        try:
            return max(1, min(16, int(v)))
        except (TypeError, ValueError):
            return v
