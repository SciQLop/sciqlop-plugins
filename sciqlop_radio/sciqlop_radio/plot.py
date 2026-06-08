"""Translator: radiospectra Spectrogram → 2-D SpeasyVariable.

The only module that knows about radiospectra's shape quirks. Pure
transform — no Qt, no SciQLop imports. The dock turns the resulting
SpeasyVariable into a virtual product so SciQLop's main timeline can
render it as a colormap natively (per the user_api/virtual_products
contract).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np


class RadioPlotError(RuntimeError):
    """Raised when a spectrogram cannot be rendered (missing fields, empty data)."""

    def __init__(self, source: str, reason: str):
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


def _to_f64(arr) -> np.ndarray:
    a = np.asarray(arr)
    if a.dtype == np.float64 and a.flags["C_CONTIGUOUS"]:
        return a
    return np.ascontiguousarray(a, dtype=np.float64)


def _times_to_unix_seconds(times) -> np.ndarray | None:
    """Astropy Time → float64 unix seconds."""
    if times is None:
        return None
    if hasattr(times, "unix"):
        return _to_f64(times.unix)
    if hasattr(times, "to_datetime"):
        dts = np.asarray(times.to_datetime())
        epoch = np.datetime64("1970-01-01T00:00:00", "ns")
        return ((dts.astype("datetime64[ns]") - epoch).astype("int64") / 1e9).astype(np.float64)
    return _to_f64(times)


def _frequencies_to_array(freqs) -> tuple[np.ndarray | None, str]:
    if freqs is None:
        return None, "Hz"
    if hasattr(freqs, "to_value"):
        unit = str(getattr(freqs, "unit", "Hz"))
        return _to_f64(freqs.to_value(unit)), unit
    return _to_f64(freqs), "Hz"


def _normalize_data(data, n_time: int, n_freq: int, source: str = "unknown") -> np.ndarray:
    """Ensure shape (n_time, n_freq), contiguous float64."""
    a = np.asarray(data)
    if a.shape == (n_freq, n_time):
        a = a.T
    elif a.shape != (n_time, n_freq):
        raise RadioPlotError(
            source=source,
            reason=f"data shape {a.shape!r} matches neither "
                   f"(n_freq,n_time)=({n_freq},{n_time}) nor (n_time,n_freq)",
        )
    return _to_f64(a)


class _Flattened:
    """Internal sequence-flattened view with the four fields the converter needs."""

    def __init__(self, *, times, freqs, unit, data, meta):
        self._times_unix = times
        self._freqs = freqs
        self._freq_unit = unit
        self._data = data
        self.meta = meta


def _flatten_sequence(spec):
    """Collapse a multi-spectrogram result into a single flattened view.

    radiospectra returns either a single Spectrogram, a `SpectrogramSequence`
    (`.spectrograms`), or a plain `list` (e.g. I-LOFAR mode 357 → 3 bands).
    Co-temporal children (one shared time grid, different frequency ranges,
    as for I-LOFAR) are stacked along frequency; otherwise children are
    concatenated along time (the multi-file, shared-frequency case).
    """
    children = getattr(spec, "spectrograms", None)
    if children is None:
        if isinstance(spec, (list, tuple)):
            children = list(spec)
        else:
            return spec

    if not children:
        raise RadioPlotError(source="sequence", reason="empty spectrogram sequence")
    if len(children) == 1:
        return children[0]

    times0 = _times_to_unix_seconds(children[0].times)
    same_time_grid = times0 is not None and all(
        (_times_to_unix_seconds(c.times) is not None
         and _times_to_unix_seconds(c.times).shape == times0.shape
         and np.allclose(_times_to_unix_seconds(c.times), times0))
        for c in children
    )
    return (_stack_frequency_bands(children, times0) if same_time_grid
            else _concat_along_time(children))


def _stack_frequency_bands(children, times_unix):
    """Co-temporal bands → one spectrogram spanning all frequencies (gaps
    between bands left as-is). Children are ordered by ascending frequency so
    the resulting frequency axis is ascending (required by the colormap)."""
    n_t = times_unix.size
    bands = []
    for c in children:
        freqs, unit = _frequencies_to_array(c.frequencies)
        if freqs is None or freqs.size == 0:
            raise RadioPlotError(source=_instrument_name(c), reason="missing .frequencies")
        data = _normalize_data(c.data, n_t, freqs.size, source=_instrument_name(c))
        bands.append((freqs, unit, data))
    bands.sort(key=lambda b: b[0][0])
    freqs = np.concatenate([b[0] for b in bands])
    data = np.concatenate([b[2] for b in bands], axis=1)
    meta = dict(children[0].meta)
    return _Flattened(times=times_unix, freqs=freqs, unit=bands[0][1], data=data, meta=meta)


def _concat_along_time(children):
    """Time-sequential children sharing one frequency axis → concatenate along
    time (e.g. several files of the same instrument over a window)."""
    children = sorted(children, key=lambda s: _times_to_unix_seconds(s.times)[0])
    freqs, unit = _frequencies_to_array(children[0].frequencies)
    if freqs is None or freqs.size == 0:
        raise RadioPlotError(source="sequence", reason="missing .frequencies in first child")
    n_f = freqs.size
    pieces_t = [_times_to_unix_seconds(s.times) for s in children]
    times = np.concatenate(pieces_t)
    data = np.concatenate(
        [_normalize_data(s.data, t.size, n_f, source=_instrument_name(children[0]))
         for s, t in zip(children, pieces_t)],
        axis=0,
    )
    meta = dict(children[0].meta)
    return _Flattened(times=times, freqs=freqs, unit=unit, data=data, meta=meta)


def _extract_arrays(spec):
    if isinstance(spec, _Flattened):
        return spec._times_unix, spec._freqs, spec._freq_unit, spec._data, spec.meta

    if getattr(spec, "times", None) is None:
        raise RadioPlotError(source=_instrument_name(spec), reason="missing .times")
    times_unix = _times_to_unix_seconds(spec.times)

    freqs, unit = _frequencies_to_array(getattr(spec, "frequencies", None))
    if freqs is None or freqs.size == 0:
        raise RadioPlotError(source=_instrument_name(spec), reason="missing .frequencies")

    data = getattr(spec, "data", None)
    if data is None or np.asarray(data).size == 0:
        raise RadioPlotError(source=_instrument_name(spec), reason="empty .data")

    data = _normalize_data(data, times_unix.size, freqs.size, source=_instrument_name(spec))
    meta = dict(getattr(spec, "meta", {}) or {})
    return times_unix, freqs, unit, data, meta


def _instrument_name(spec) -> str:
    meta = getattr(spec, "meta", None) or {}
    return str(meta.get("instrument", "unknown"))


def spectrogram_to_speasy_variable(spec) -> "SpeasyVariable":
    """Convert a radiospectra Spectrogram (or SpectrogramSequence) to a 2-D
    `SpeasyVariable` with axes = [time, frequency]. Pure: no Qt, no SciQLop.

    Raises `RadioPlotError` on malformed input. The dock wraps the result
    in a `VirtualProductType.Spectrogram` so SciQLop's main timeline can
    render it as a colormap.
    """
    from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
    from speasy.products.variable import SpeasyVariable

    spec = _flatten_sequence(spec)
    times_unix, freqs, freq_unit, data, meta = _extract_arrays(spec)
    instrument = str(meta.get("instrument", "unknown"))
    data_unit = str(meta.get("units") or meta.get("data_unit") or "")

    epochs_ns = (times_unix * 1e9).astype("int64").astype("datetime64[ns]")
    time_axis = VariableTimeAxis(values=epochs_ns)
    freq_axis = VariableAxis(
        name="frequency", values=freqs, meta={"UNITS": freq_unit},
    )
    values = DataContainer(
        values=data, meta={"UNITS": data_unit}, name=f"{instrument}.spectrogram",
    )
    return SpeasyVariable(axes=[time_axis, freq_axis], values=values, columns=[instrument])


def frequency_signature(variable, decimals: int = 3) -> tuple:
    """A hashable key identifying a variable's frequency axis. Variables with
    the same signature share a frequency grid and can be concatenated along
    time into one continuous spectrogram (same instrument, different times)."""
    f = np.asarray(variable.axes[1].values, dtype=np.float64)
    return (f.size,) + tuple(np.round(f, decimals).tolist())


def concat_variables_along_time(variables) -> "SpeasyVariable":
    """Merge translated radio SpeasyVariables that share one frequency axis
    into a single time-ordered variable. The caller must group by
    `frequency_signature` first, so the frequency axis is well-defined."""
    from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
    from speasy.products.variable import SpeasyVariable

    variables = [v for v in variables if v is not None]
    if not variables:
        raise RadioPlotError(source="merge", reason="no variables to merge")
    if len(variables) == 1:
        return variables[0]

    variables = sorted(variables, key=lambda v: np.asarray(v.time)[0])
    times = np.concatenate([np.asarray(v.time).astype("datetime64[ns]") for v in variables])
    data = np.ascontiguousarray(
        np.concatenate([np.asarray(v.values) for v in variables], axis=0), dtype=np.float64
    )
    first = variables[0]
    fa = first.axes[1]
    freq_axis = VariableAxis(
        name=getattr(fa, "name", "frequency"),
        values=np.ascontiguousarray(np.asarray(fa.values), dtype=np.float64),
        meta=dict(getattr(fa, "meta", {}) or {}),
    )
    cols = list(getattr(first, "columns", []) or ["radio"])
    values = DataContainer(
        values=data,
        meta={"UNITS": str(getattr(first, "unit", "") or "")},
        name=f"{cols[0]}.spectrogram",
    )
    return SpeasyVariable(axes=[VariableTimeAxis(values=times), freq_axis], values=values, columns=cols)


def _format_iso(unix_seconds: float) -> str:
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).isoformat()
