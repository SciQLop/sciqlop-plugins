"""Single-entry-point reader for radio dyn-spectra files.

Thin shim around `radiospectra.Spectrogram(path)` so the rest of the
plugin can mock one function and so per-source workarounds can be
added in one place when needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Union


def open_spectrogram(path: Union[str, Path]):
    """Open a radio dyn-spectra file. Returns radiospectra Spectrogram or SpectrogramSequence."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"radio file not found: {p}")

    from radiospectra.spectrogram import Spectrogram  # type: ignore
    return Spectrogram(str(p))
