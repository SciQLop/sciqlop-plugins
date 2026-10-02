"""Translate ObsPy Streams to SpeasyVariable.

Pure functions. No Qt, no Speasy provider, no network. The output is
ready to drop onto a SciQLop panel (the provider exposes these
variables through `get_data`).
"""
from __future__ import annotations

import numpy as np
from obspy import Stream
from scipy.signal import spectrogram as _scipy_spectrogram
from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
from speasy.products.variable import SpeasyVariable


def variable_to_stream(
    variable: SpeasyVariable, nslc: tuple[str, str, str, str], sampling_rate_hz: float
) -> Stream:
    """Rebuild an `obspy.Stream` from a raw-counts `SpeasyVariable`, one trace per run
    of samples without a gap (a time jump or NaNs), each starting at its own time.

    Inverse of `stream_to_speasy_variable`. Used to re-derive processed/spectrogram
    products from the cached raw-counts fetch without touching the network — the
    pipeline then runs on the assembled full window, so no fragment-boundary
    filter/STFT seams are introduced, and never across a gap.
    """
    from obspy import Trace, UTCDateTime

    net, sta, loc, chan = nslc
    data = np.asarray(variable.values, dtype=np.float64).reshape(-1)
    times_ns = variable.time.astype("datetime64[ns]").astype(np.int64)
    valid = np.isfinite(data)
    step_ns = 1e9 / float(sampling_rate_hz)
    breaks = np.flatnonzero((np.diff(times_ns) > 1.5 * step_ns) | (valid[1:] != valid[:-1])) + 1
    header = {"network": net, "station": sta, "location": loc, "channel": chan,
              "sampling_rate": float(sampling_rate_hz)}
    return Stream([Trace(data=data[run], header={**header, "starttime": UTCDateTime(times_ns[run[0]] / 1e9)})
                   for run in np.split(np.arange(len(data)), breaks) if len(run) and valid[run[0]]])


def _pick_trace(stream: Stream, channel: str):
    for tr in stream:
        if tr.stats.channel == channel:
            return tr
    raise KeyError(f"channel {channel!r} not found in stream")


def _merged_trace(stream: Stream, channel: str):
    """A gapped FDSN fetch comes as several traces: keeping only the first dropped the
    rest, and the fragment cache then trimmed the whole window away."""
    traces = stream.select(channel=channel)
    if len(traces) == 0:
        raise KeyError(f"channel {channel!r} not found in stream")
    return traces.copy().merge(method=1, fill_value=None)[0]


def _trace_time_axis(tr) -> VariableTimeAxis:
    n = tr.stats.npts
    dt = tr.stats.delta
    start_ns = int(tr.stats.starttime.timestamp * 1e9)
    step_ns = int(round(dt * 1e9))
    epochs_ns = start_ns + np.arange(n, dtype=np.int64) * step_ns
    return VariableTimeAxis(values=epochs_ns.astype("datetime64[ns]"))


def stream_to_speasy_variable(
    stream: Stream, channel: str, units: str
) -> SpeasyVariable:
    """Convert one channel of a Stream to a 1-D `SpeasyVariable`. All its traces are
    merged onto one time grid; gaps between them become NaN."""
    tr = _merged_trace(stream, channel)
    nslc = ".".join(
        (tr.stats.network, tr.stats.station, tr.stats.location, tr.stats.channel)
    )
    time_axis = _trace_time_axis(tr)
    values = DataContainer(
        values=np.ma.filled(np.ma.asarray(tr.data, dtype=np.float64), np.nan).reshape(-1, 1),
        meta={"UNITS": units},
        name=nslc,
    )
    return SpeasyVariable(axes=[time_axis], values=values, columns=[channel])


def spectrogram_from_stream(
    stream: Stream,
    channel: str,
    nperseg: int = 256,
    noverlap: int = 128,
) -> SpeasyVariable:
    """Compute STFT power spectrogram for one channel.

    Returns a 2-D `SpeasyVariable` with axis[0] = time and
    axis[1] = frequency (Hz). Power is dB (10·log10).
    """
    tr = _pick_trace(stream, channel)
    sr = float(tr.stats.sampling_rate)
    f, t_rel, sxx = _scipy_spectrogram(
        tr.data.astype(np.float64),
        fs=sr,
        nperseg=nperseg,
        noverlap=noverlap,
        scaling="density",
        mode="psd",
    )
    sxx = np.where(sxx > 0, sxx, np.finfo(np.float64).tiny)
    sxx_db = 10.0 * np.log10(sxx)

    start_ns = int(tr.stats.starttime.timestamp * 1e9)
    epochs_ns = start_ns + (t_rel * 1e9).astype(np.int64)
    time_axis = VariableTimeAxis(values=epochs_ns.astype("datetime64[ns]"))
    freq_axis = VariableAxis(
        name="frequency",
        values=f.astype(np.float64),
        meta={"UNITS": "Hz"},
    )
    nslc = ".".join(
        (tr.stats.network, tr.stats.station, tr.stats.location, tr.stats.channel)
    )
    values = DataContainer(
        values=sxx_db.T,
        meta={"UNITS": "dB"},
        name=f"{nslc}.spectrogram",
    )
    return SpeasyVariable(axes=[time_axis, freq_axis], values=values, columns=[channel])
