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
    unavailable_reason: str | None = Field(
        default=None,
        description=(
            "If set, the source is shown in the picker but Fido search is"
            " disabled and this message is displayed instead."
        ),
    )
    example_range: str = Field(
        default="",
        description="A date with known data, used in the empty-results hint.",
    )

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
    # Only sources that radiospectra ships a Fido client for. The
    # `fido_instrument` string must match the client's registered
    # `a.Instrument` name (see radiospectra/net/sources/*.py
    # register_values()). Wind/WAVES, Solar Orbiter/RPW and
    # STEREO/SWAVES are NOT here — radiospectra has no client for
    # them, so Fido falls back to default clients that return
    # non-spectrogram data products. Add them back if radiospectra
    # grows a dyn-spectrum client for those instruments.
    RadioSource(
        key="psp_rfs",
        label="PSP / FIELDS / RFS",
        fido_instrument="rfs",
        notes="LFR (10 kHz–1.7 MHz) + HFR (1.3–19.2 MHz); receiver mode varies along orbit",
        example_range="2021-10-28",
    ),
    RadioSource(
        key="ecallisto",
        label="e-CALLISTO (network)",
        fido_instrument="eCALLISTO",
        notes="Worldwide ground-based network; many stations with different frequency windows",
        example_range="2011-06-07",
    ),
    RadioSource(
        key="eovsa",
        label="EOVSA (registration required)",
        fido_instrument=None,
        accepts_local=True,
        unavailable_reason=(
            "EOVSA spectrogram FITS now require registration at "
            "ovsa.njit.edu/eovsadata. Download a .fts there, then use "
            "'Open local…'."
        ),
        notes="Expanded Owens Valley Solar Array; 1–18 GHz imaging spectroscopy",
    ),
    RadioSource(
        key="ilofar",
        label="I-LOFAR (mode 357 BST)",
        fido_instrument="ILOFAR",
        notes="Irish LOFAR station, beam-formed mode 357; sparse campaign-day coverage",
        example_range="2021-09-07",
    ),
    RadioSource(
        key="rstn",
        label="RSTN",
        fido_instrument="RSTN",
        notes="Radio Solar Telescope Network (USAF); data source may be stale",
        example_range="2015-11-04",
    ),
    RadioSource(
        key="custom",
        label="Custom (local file)",
        fido_instrument=None,
        accepts_local=True,
        notes="Generic radiospectra reader; time + frequency + data arrays must be present",
    ),
]
