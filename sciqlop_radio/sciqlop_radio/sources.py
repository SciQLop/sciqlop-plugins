"""Static registry of supported radio-spectra sources.

Each entry corresponds to a source `sunpy.radiospectra` knows how to
parse. Adding a new source = adding one entry here; behavior elsewhere
is data-driven from this list.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RadioSource(BaseModel):
    """One supported radio instrument/observatory."""

    key: str = Field(description="Stable identifier used in UI state and tests")
    label: str = Field(description="Human-readable name shown in the dropdown")
    fido_instrument: str | None = Field(
        default=None,
        description=(
            "Argument for sunpy.net.attrs.Instrument; None means this source"
            " is local-file-only (no Fido search supported)"
        ),
    )
    notes: str = Field(default="", description="Tooltip text; coverage caveats")
    accepts_local: bool = Field(default=True)

    @field_validator("key")
    @classmethod
    def _key_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("key must be non-blank")
        return v

    @field_validator("label")
    @classmethod
    def _label_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("label must be non-blank")
        return v


SOURCES: list[RadioSource] = [
    RadioSource(
        key="psp_rfs",
        label="PSP / FIELDS / RFS",
        fido_instrument="rfs",
        notes="LFR (10 kHz–1.7 MHz) + HFR (1.3–19.2 MHz); receiver mode varies along orbit",
    ),
    RadioSource(
        key="solo_rpw",
        label="Solar Orbiter / RPW",
        fido_instrument="rpw",
        notes="TNR + HFR L2/L3; multi-receiver sequence",
    ),
    RadioSource(
        key="wind_waves",
        label="Wind / WAVES",
        fido_instrument="waves",
        notes="RAD1 (20–1040 kHz) + RAD2 (1.075–13.825 MHz)",
    ),
    RadioSource(
        key="stereo_swaves",
        label="STEREO / SWAVES",
        fido_instrument="swaves",
        notes="2.5 kHz – 16 MHz; STEREO-A only post 2014",
    ),
    RadioSource(
        key="ecallisto",
        label="e-CALLISTO (network)",
        fido_instrument="callisto",
        notes="Worldwide ground-based network; many stations with different frequency windows",
    ),
    RadioSource(
        key="eovsa",
        label="EOVSA",
        fido_instrument="eovsa",
        notes="Expanded Owens Valley Solar Array; 1–18 GHz imaging spectroscopy",
    ),
    RadioSource(
        key="ilofar",
        label="I-LOFAR (mode 357 BST)",
        fido_instrument="ilofar",
        notes="Irish LOFAR station, beam-formed mode 357",
    ),
    RadioSource(
        key="rstn",
        label="RSTN",
        fido_instrument="rstn",
        notes="Radio Solar Telescope Network (USAF); data source may be stale",
    ),
    RadioSource(
        key="custom",
        label="Custom (local file)",
        fido_instrument=None,
        accepts_local=True,
        notes="Generic radiospectra reader; time + frequency + data arrays must be present",
    ),
]
