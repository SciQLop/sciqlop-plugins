"""Minimal seismic preprocessing.

Pure functions that take an `obspy.Stream` and return a NEW
`Stream` — they never mutate the input. Compositions are explicit
(see `default_pipeline`). No Qt, no Speasy, no network.
"""
from __future__ import annotations

from obspy import Stream

from .settings import SismoSettings


def detrend(stream: Stream, type: str = "demean") -> Stream:
    """Remove the mean (or linear trend) from every trace.

    `type` is forwarded to `obspy.Trace.detrend` — typical values:
    `"demean"`, `"linear"`, `"polynomial"`. Default `"demean"` is
    sufficient for casual inspection; users who care about long-period
    drift should pass `"linear"`.
    """
    out = stream.copy()
    for tr in out:
        tr.detrend(type=type)
    return out


def bandpass(stream: Stream, fmin: float, fmax: float, corners: int = 4) -> Stream:
    """Zero-phase Butterworth bandpass on every trace."""
    out = stream.copy()
    for tr in out:
        tr.filter("bandpass", freqmin=fmin, freqmax=fmax, corners=corners, zerophase=True)
    return out


def default_pipeline(stream: Stream, settings: SismoSettings) -> Stream:
    """Minimal-but-sane defaults: demean + project-wide bandpass."""
    return bandpass(
        detrend(stream, type="demean"),
        fmin=settings.bandpass_min_hz,
        fmax=settings.bandpass_max_hz,
    )
