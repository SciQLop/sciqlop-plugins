"""The single value the fetch layer consumes to run a Fido search.

A `RadioQuery` is either structured (instrument + optional wavelength) or a
raw escape hatch (`raw_attrs_text`, eval'd against sunpy attrs). Building it
in one place keeps the dock and the fetch service decoupled and testable.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RadioQuery(BaseModel):
    """Describes one Fido search. `raw_attrs_text`, when set, overrides the
    structured fields. `expect_spectrogram` is False for raw queries so the
    dock does not silently drop rows the user explicitly asked for."""

    t_start: datetime
    t_end: datetime
    instrument: str | None = None
    wavelength_min_mhz: float | None = None
    wavelength_max_mhz: float | None = None
    raw_attrs_text: str | None = None
    expect_spectrogram: bool = True

    @classmethod
    def from_source(cls, source, t_start: datetime, t_end: datetime) -> "RadioQuery":
        return cls(
            t_start=t_start,
            t_end=t_end,
            instrument=source.fido_instrument,
            expect_spectrogram=True,
        )
