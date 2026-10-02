"""Live waterfall (record section) of several channels in one plot.

SciQLop's Waterfall takes static arrays on one shared x grid, so the live
part is ours: on every panel range change, refetch each channel's processed
waveform (through the provider's cache), resample it onto a common grid and
push the matrix with `Waterfall.set_data`.
"""
from __future__ import annotations

import math
from typing import Callable, Optional, Sequence

import numpy as np
from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal
from speasy.core import datetime64_to_epoch

# simplify: linear interpolation onto a fixed grid can skip short spikes.
# Upgrade path: a per-bin min/max envelope (what NeoQCP does for line plots).
DEFAULT_POINTS = 4000
TRACE_GAIN = 0.45  # normalized traces are ±1; × the mean gap keeps neighbours apart
DEBOUNCE_MS = 200


def trace_label(row: dict) -> str:
    return f"{row['network']}.{row['station']}.{row['location']}.{row['channel']}"


def waveform_uid(row: dict) -> str:
    return f"{row['network']}/{row['station']}/{row['location']}.{row['channel']}/waveform"


def _distance_deg(row: dict, origin: tuple[float, float]) -> float:
    from obspy.geodetics import locations2degrees

    lat, lon = row.get("latitude"), row.get("longitude")
    if lat is None or lon is None:
        return math.inf
    return locations2degrees(origin[0], origin[1], lat, lon)


def order_rows(rows: Sequence[dict], origin: Optional[tuple[float, float]]) -> list[dict]:
    """Nearest-first to the event `origin` (lat, lon); selection order without one."""
    if origin is None:
        return list(rows)
    return sorted(rows, key=lambda row: _distance_deg(row, origin))


def trace_distances(rows: Sequence[dict], origin: Optional[tuple[float, float]]):
    """Epicentral distance (°) per row, or None when they can't lay out a record
    section: no event, a station without coordinates, or all at one distance."""
    if origin is None or not rows:
        return None
    distances = np.array([_distance_deg(row, origin) for row in rows])
    if not np.isfinite(distances).all() or np.ptp(distances) == 0.0:
        return None
    return distances


def trace_layout(rows: Sequence[dict], origin: Optional[tuple[float, float]]):
    """(offsets, gain): each trace's y position and half-height. A trace sits at
    its distance — the record section's y axis, which shows the moveout — or,
    without usable distances, at its index."""
    distances = trace_distances(rows, origin)
    if distances is None:
        return np.arange(len(rows), dtype=float), TRACE_GAIN
    return distances, TRACE_GAIN * float(np.ptp(distances)) / max(len(rows) - 1, 1)


def common_grid(t0: float, t1: float, points: int) -> np.ndarray:
    return np.linspace(t0, t1, points)


def resample(variable, grid: np.ndarray) -> np.ndarray:
    """One trace on `grid`: NaN where the channel has no samples (outside its
    coverage, or across a NaN gap), so the waterfall line breaks there."""
    if variable is None or len(variable) == 0:
        return np.full(len(grid), np.nan)
    times = datetime64_to_epoch(variable.time)
    values = np.asarray(variable.values, dtype=np.float64).reshape(len(times), -1)[:, 0]
    return np.interp(grid, times, values, left=np.nan, right=np.nan)


class LiveWaterfall(QObject):
    """Refetches every channel when the panel's time range changes.

    Fetches run off the GUI thread; each carries a generation number so a slow,
    stale result never overwrites a newer one. A sink that raises ValueError
    (the waterfall graph was destroyed with its panel) stops the feed."""

    _computed = Signal(int, object)

    def __init__(self, fetch: Callable, uids: Sequence[str], sink: Callable, *,
                 run: Optional[Callable] = None, debounce_ms: int = DEBOUNCE_MS,
                 points: int = DEFAULT_POINTS,
                 on_failures: Callable[[list[str]], None] = lambda failures: None):
        super().__init__()
        self._fetch, self._uids, self._sink = fetch, list(uids), sink
        self._run = run or QThreadPool.globalInstance().start
        self._points = points
        self._on_failures = on_failures
        self._generation = 0
        self._window = None
        self.stopped = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(debounce_ms)
        self._timer.timeout.connect(self._launch)
        self._computed.connect(self._deliver)

    def on_range_changed(self, time_range) -> None:
        self.request(float(time_range.start()), float(time_range.stop()))

    def request(self, t0: float, t1: float) -> None:
        if self.stopped:
            return
        self._window = (t0, t1)
        self._timer.start()

    def _launch(self) -> None:
        self._generation += 1
        generation, (t0, t1) = self._generation, self._window
        self._run(lambda: self._computed.emit(generation, self._compute(t0, t1)))

    def _compute(self, t0: float, t1: float):
        grid = common_grid(t0, t1, self._points)
        rows, failures = [], []
        for uid in self._uids:
            try:
                rows.append(resample(self._fetch(uid, t0, t1), grid))
            except Exception as exc:  # noqa: BLE001 — one bad channel must not blank the others
                rows.append(np.full(len(grid), np.nan))
                failures.append(f"{uid}: {type(exc).__name__}: {exc}")
        return grid, np.vstack(rows), failures

    def _deliver(self, generation: int, result) -> None:
        if self.stopped or generation != self._generation:
            return
        grid, z, failures = result
        try:
            self._sink(grid, np.arange(len(z)), z)
        except ValueError:
            self.stopped = True
            return
        if failures:
            self._on_failures(failures)


def _tick_labels(rows: Sequence[dict], offsets: np.ndarray, at_distance: bool) -> dict:
    if not at_distance:
        return {float(y): trace_label(row) for y, row in zip(offsets, rows)}
    return {float(y): f"{trace_label(row)} ({y:.1f}°)" for y, row in zip(offsets, rows)}


def _label_traces(plot, labels: dict) -> None:
    try:
        plot.set_axis_tick_labels("y", labels)
    except AttributeError:
        pass  # text ticks need SciQLop >= 0.14; the traces still plot unlabelled


def plot_live_waterfall(panel, rows: Sequence[dict], origin: Optional[tuple[float, float]],
                        fetch: Callable, t0: float, t1: float,
                        on_failures: Callable[[list[str]], None]) -> LiveWaterfall:
    """One waterfall plot in `panel`, kept in sync with the panel's time range.
    `rows` must already be ordered (see `order_rows`). Keep the returned feed
    referenced: once collected, its timer and range connection die silently."""
    grid = common_grid(t0, t1, DEFAULT_POINTS)
    empty = np.full((len(rows), len(grid)), np.nan)
    offsets, gain = trace_layout(rows, origin)
    graph = panel.waterfall(grid, offsets, empty, name="waterfall",
                            normalize=True, offsets=offsets, gain=gain)
    at_distance = trace_distances(rows, origin) is not None
    _label_traces(panel.plots[-1], _tick_labels(rows, offsets, at_distance))
    feed = LiveWaterfall(fetch=fetch, uids=[waveform_uid(r) for r in rows],
                         sink=graph.set_data, on_failures=on_failures)
    # Reach-through: user_api exposes no public "time range changed" hook; it
    # wires its own live histograms to this same signal.
    panel._impl.time_range_changed.connect(feed.on_range_changed)
    feed.request(t0, t1)
    return feed
