"""Waterfall (record section) of several channels: ordering, common grid, live feed."""
from datetime import datetime, timezone

import numpy as np
import pytest
from speasy.core.data_containers import DataContainer, VariableTimeAxis
from speasy.products.variable import SpeasyVariable


def _row(sta, lat, lon):
    return {"network": "G", "station": sta, "location": "00", "channel": "HHZ",
            "latitude": lat, "longitude": lon}


def _variable(t0: float, t1: float, rate_hz: float, value=None):
    times = np.arange(t0, t1, 1.0 / rate_hz)
    data = np.sin(times) if value is None else np.full(len(times), value, dtype=float)
    axis = VariableTimeAxis(values=(times * 1e9).astype("int64").astype("datetime64[ns]"))
    return SpeasyVariable(axes=[axis], values=DataContainer(data.reshape(-1, 1)), columns=["HHZ"])


def waterfall_matrix(variables, t0, t1, points):
    from sciqlop_sismo.waterfall import common_grid, resample

    grid = common_grid(t0, t1, points)
    return grid, np.vstack([resample(v, grid) for v in variables])


def test_rows_are_ordered_nearest_first_from_the_event():
    from sciqlop_sismo.waterfall import order_rows

    far, near, mid = _row("FAR", 0.0, 60.0), _row("NEAR", 0.0, 1.0), _row("MID", 0.0, 20.0)
    assert [r["station"] for r in order_rows([far, near, mid], origin=(0.0, 0.0))] == [
        "NEAR", "MID", "FAR"]


def test_rows_keep_selection_order_without_an_event():
    from sciqlop_sismo.waterfall import order_rows

    rows = [_row("B", 0.0, 60.0), _row("A", 0.0, 1.0)]
    assert order_rows(rows, origin=None) == rows


def test_rows_without_coordinates_go_last_instead_of_failing():
    from sciqlop_sismo.waterfall import order_rows

    lost = {**_row("LOST", 0.0, 0.0), "latitude": None, "longitude": None}
    rows = [lost, _row("NEAR", 0.0, 1.0)]
    assert [r["station"] for r in order_rows(rows, origin=(0.0, 0.0))] == ["NEAR", "LOST"]


def test_trace_label_is_the_full_channel_code():
    from sciqlop_sismo.waterfall import trace_label

    assert trace_label(_row("SSB", 0, 0)) == "G.SSB.00.HHZ"


def test_matrix_puts_every_channel_on_one_shared_grid():
    t0, t1 = 1000.0, 1100.0
    x, z = waterfall_matrix([_variable(t0, t1, 100.0), _variable(t0, t1, 20.0)], t0, t1, points=500)
    assert x.shape == (500,) and z.shape == (2, 500)
    assert x[0] == t0 and x[-1] == t1
    assert np.isfinite(z[:, 1:-1]).all()


def test_missing_or_partial_channels_become_nan_not_flat_lines():
    t0, t1 = 0.0, 100.0
    x, z = waterfall_matrix([None, _variable(50.0, 100.0, 10.0, value=3.0)], t0, t1, points=101)
    assert np.isnan(z[0]).all()
    assert np.isnan(z[1][x < 49.0]).all()
    assert np.allclose(z[1][(x > 51.0) & (x < 99.0)], 3.0)


def test_grid_breaks_across_a_gap_inside_a_trace():
    var = _variable(0.0, 100.0, 10.0, value=1.0)
    values = np.asarray(var.values).copy()
    values[400:600] = np.nan
    gapped = SpeasyVariable(axes=[var.axes[0]], values=DataContainer(values), columns=["HHZ"])
    x, z = waterfall_matrix([gapped], 0.0, 100.0, points=101)
    assert np.isnan(z[0][(x > 41.0) & (x < 59.0)]).all()


class _Range:
    def __init__(self, start, stop):
        self._start, self._stop = start, stop

    def start(self):
        return self._start

    def stop(self):
        return self._stop


def _feed(qtbot, fetch, sink, jobs=None):
    from sciqlop_sismo.waterfall import LiveWaterfall

    run = (lambda job: job()) if jobs is None else jobs.append
    feed = LiveWaterfall(fetch=fetch, uids=["a", "b"], sink=sink, run=run, debounce_ms=0, points=11)
    return feed


def test_range_change_fetches_every_channel_and_pushes_one_matrix(qtbot):
    fetched, pushed = [], []

    def fetch(uid, t0, t1):
        fetched.append((uid, t0, t1))
        return _variable(t0, t1, 1.0, value=1.0)

    feed = _feed(qtbot, fetch, lambda x, y, z: pushed.append((x, y, z)))
    feed.on_range_changed(_Range(0.0, 10.0))
    qtbot.waitUntil(lambda: len(pushed) == 1, timeout=2000)
    assert fetched == [("a", 0.0, 10.0), ("b", 0.0, 10.0)]
    x, y, z = pushed[0]
    assert list(y) == [0, 1] and z.shape == (2, 11)


def test_a_slow_stale_result_never_overwrites_a_newer_one(qtbot):
    jobs, pushed = [], []
    feed = _feed(qtbot, lambda uid, t0, t1: _variable(t0, t1, 1.0, value=t0),
                 lambda x, y, z: pushed.append(x[0]), jobs=jobs)
    feed.on_range_changed(_Range(0.0, 10.0))
    qtbot.waitUntil(lambda: len(jobs) == 1, timeout=2000)
    feed.on_range_changed(_Range(100.0, 110.0))
    qtbot.waitUntil(lambda: len(jobs) == 2, timeout=2000)
    jobs[1]()
    jobs[0]()
    qtbot.wait(50)
    assert pushed == [100.0]


def test_a_failing_channel_becomes_an_empty_trace_and_is_reported(qtbot):
    pushed, failures = [], []

    def fetch(uid, t0, t1):
        if uid == "b":
            raise RuntimeError("timeout")
        return _variable(t0, t1, 1.0, value=1.0)

    from sciqlop_sismo.waterfall import LiveWaterfall

    feed = LiveWaterfall(fetch=fetch, uids=["a", "b"], sink=lambda x, y, z: pushed.append(z),
                         run=lambda job: job(), debounce_ms=0, points=11,
                         on_failures=failures.append)
    feed.on_range_changed(_Range(0.0, 10.0))
    qtbot.waitUntil(lambda: len(pushed) == 1, timeout=2000)
    assert np.isnan(pushed[0][1]).all() and not np.isnan(pushed[0][0]).all()
    assert failures and "b" in failures[0][0]


def test_a_closed_panel_stops_the_feed_instead_of_raising(qtbot):
    calls = []

    def dead_sink(x, y, z):
        calls.append(1)
        raise ValueError("The waterfall graph does not exist anymore.")

    feed = _feed(qtbot, lambda uid, t0, t1: None, dead_sink)
    feed.on_range_changed(_Range(0.0, 10.0))
    qtbot.waitUntil(lambda: len(calls) == 1, timeout=2000)
    feed.on_range_changed(_Range(10.0, 20.0))
    qtbot.wait(50)
    assert calls == [1]
