"""Translator: radiospectra Spectrogram → SciQLopTimeSeriesPlot colormap.

The only module that imports SciQLop plotting types. Pure transform with
testable sentinels (`_radio_*` attributes) attached to the returned plot
so unit tests can verify axis/data wiring without instantiating real Qt.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

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
    """Astropy Time → float64 unix seconds (what SciQLop time axis expects)."""
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
    """Internal sequence-flattened view with the four fields the renderer needs."""

    def __init__(self, *, times, freqs, unit, data, meta):
        self._times_unix = times
        self._freqs = freqs
        self._freq_unit = unit
        self._data = data
        self.meta = meta


def _flatten_sequence(spec):
    """If `spec` is a SpectrogramSequence, concatenate into a flattened view."""
    children = getattr(spec, "spectrograms", None)
    if children is None:
        return spec

    if not children:
        raise RadioPlotError(source="sequence", reason="empty SpectrogramSequence")

    children = sorted(children, key=lambda s: _times_to_unix_seconds(s.times)[0])

    freqs, unit = _frequencies_to_array(children[0].frequencies)
    if freqs is None or freqs.size == 0:
        raise RadioPlotError(source="sequence", reason="missing .frequencies in first child")
    n_f = freqs.size
    pieces_t = [_times_to_unix_seconds(s.times) for s in children]
    times = np.concatenate(pieces_t)
    data = np.concatenate(
        [_normalize_data(s.data, t.size, n_f, source=_instrument_name(children[0])) for s, t in zip(children, pieces_t)],
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


def _make_theme():
    """Guarded theme construction. NEVER pass a parent to SciQLopTheme."""
    try:
        from SciQLopPlots import SciQLopTheme
    except ImportError:
        return None
    try:
        return SciQLopTheme.dark()
    except Exception:
        return None


def _build_plot_hints(freq_unit: str, data_unit: str, instrument: str):
    try:
        from SciQLop.core.plot_hints import PlotHints
    except ImportError:
        return None
    return PlotHints(
        display_type="spectrogram",
        component_labels=[f"{instrument}"],
        units=data_unit,
        scale_type="log",
        depend_1_units=freq_unit,
        depend_1_scale="log",
    )


def _format_iso(unix_seconds: float) -> str:
    return datetime.fromtimestamp(unix_seconds, tz=timezone.utc).isoformat()


class _StubPlot:
    """Stand-in returned when SciQLopPlots is not importable (tests / headless)."""
    pass


def spectrogram_to_plot(spec, parent=None):
    """Build a configured SciQLopTimeSeriesPlot colormap from a radiospectra Spectrogram.

    Returns the plot widget. Raises RadioPlotError on missing/empty fields.
    """
    spec = _flatten_sequence(spec)
    times_unix, freqs, freq_unit, data, meta = _extract_arrays(spec)
    instrument = str(meta.get("instrument", "unknown"))
    data_unit = str(meta.get("units") or meta.get("data_unit") or "")

    try:
        from SciQLopPlots import SciQLopTimeSeriesPlot
    except ImportError:
        SciQLopTimeSeriesPlot = None

    if SciQLopTimeSeriesPlot is None:
        plot = _StubPlot()
    else:
        plot = SciQLopTimeSeriesPlot(parent)
        theme = _make_theme()
        if theme is not None:
            plot.set_theme(theme)

        plot.colormap(times_unix, freqs, data, name=instrument)

        hints = _build_plot_hints(freq_unit, data_unit, instrument)
        if hints is not None:
            try:
                from SciQLop.core.plot_hints import apply_plot_hints
                apply_plot_hints(plot, hints)
            except ImportError:
                pass

        try:
            plot.y_axis().set_visible(False)  # cmap data lives on y2_axis
            plot.rescale_axes()
            plot.replot()
        except Exception:
            pass

    title = f"{instrument} — {_format_iso(times_unix[0])}"

    plot._radio_n_time_samples = int(times_unix.size)
    plot._radio_n_freq_channels = int(freqs.size)
    plot._radio_data_shape = tuple(data.shape)
    plot._radio_y_array = freqs
    plot._radio_title = title
    plot._radio_instrument = instrument
    return plot
