from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from sciqlop_pyspedas import worker
from sciqlop_pyspedas.catalog import Source, tplot_name

FPI_I = Source("fpi", "i", "FPI ions", ("fast", "brst"))
HPCA_H = Source("hpca", "hplus", "HPCA H+", ("srvy", "brst"))
T0 = datetime(2020, 1, 1, tzinfo=timezone.utc)


class FakePyspedas:
    """Stands in for pyspedas: records getspec calls, serves a tplot-like store."""

    def __init__(self, has_data=True, fail_get_data=False):
        self.has_data = has_data
        self.fail_get_data = fail_get_data
        self.calls = []
        self.store = {}
        self.cleared = 0

    def getspec(self, *, instrument, probe, species, data_rate, trange, output):
        self.calls.append(dict(instrument=instrument, probe=probe, species=species,
                               data_rate=data_rate, trange=trange))
        if not self.has_data:
            return []
        t0, t1 = (np.datetime64(t.replace("/", "T"), "ns") for t in trange)
        times = np.arange(t0, t1, np.timedelta64(60, "s"))
        source = Source(instrument, species, "", ())
        names = []
        for out in output:
            name = tplot_name(source, probe, data_rate, out)
            self.store[name] = SimpleNamespace(times=times, y=np.ones((len(times), 4)),
                                               v=np.array([10., 100., 1e3, 1e4]))
            names.append(name)
        return names

    def get_data(self, name, dt=False):
        if self.fail_get_data:
            raise RuntimeError("boom")
        return self.store[name]

    def del_data(self, pattern):
        self.cleared += 1
        self.store.clear()


@pytest.fixture
def fake(monkeypatch):
    f = FakePyspedas()
    monkeypatch.setattr(worker, "_pyspedas_api", lambda: f)
    return f


def _call(output, start, stop, source=FPI_I, data_rate="fast"):
    return worker.worker_callback(start.timestamp(), stop.timestamp(), source=source,
                                  output=output, probe="1", data_rate=data_rate)


def test_returns_requested_spectrum(fake):
    v = _call("energy", T0, T0 + timedelta(minutes=30))
    assert v is not None and len(v.time) > 0
    assert v.values.shape[1] == 4
    assert fake.calls[0]["instrument"] == "fpi" and fake.calls[0]["species"] == "i"


def test_sibling_spectra_share_one_compute(fake):
    _call("energy", T0, T0 + timedelta(hours=24))
    _call("pa", T0, T0 + timedelta(hours=24))
    _call("gyro", T0, T0 + timedelta(hours=24))
    assert len(fake.calls) == 24


def test_repeat_request_served_from_disk_cache(fake):
    _call("energy", T0, T0 + timedelta(minutes=30))
    _call("energy", T0, T0 + timedelta(minutes=30))
    assert len(fake.calls) == 1


def test_no_data_returns_none_and_is_retried_later(fake):
    # pyspedas returns nothing both for real gaps and failed downloads, so an
    # empty answer must never be cached or one glitch blanks the window forever.
    fake.has_data = False
    assert _call("energy", T0, T0 + timedelta(minutes=30)) is None
    fake.has_data = True
    later = _call("energy", T0, T0 + timedelta(minutes=30))
    assert later is not None and len(later.time) > 0
    assert len(fake.calls) == 2


def _trange(call):
    return [datetime.strptime(t, "%Y-%m-%d/%H:%M:%S") for t in call["trange"]]


def test_every_compute_is_one_hour_on_the_hour_grid(fake):
    _call("energy", T0 + timedelta(minutes=30), T0 + timedelta(hours=3, minutes=10))
    hours = [T0.replace(tzinfo=None) + timedelta(hours=h) for h in range(5)]
    assert [_trange(c) for c in fake.calls] == [[a, b] for a, b in zip(hours, hours[1:])]


def test_burst_uses_the_same_fragments(fake):
    _call("energy", T0, T0 + timedelta(hours=3), data_rate="brst")
    assert len(fake.calls) == 3


def test_cache_key_distinguishes_hpca_rates(fake):
    _call("energy", T0, T0 + timedelta(minutes=10), source=HPCA_H, data_rate="srvy")
    _call("energy", T0, T0 + timedelta(minutes=10), source=HPCA_H, data_rate="brst")
    assert [c["data_rate"] for c in fake.calls] == ["srvy", "brst"]


def test_long_window_is_returned_whole_and_trimmed(fake):
    start = T0 + timedelta(minutes=30)
    stop = start + timedelta(days=1)
    v = _call("energy", start, stop)
    assert len(fake.calls) == 25
    naive = lambda t: np.datetime64(t.replace(tzinfo=None), "ns")
    assert naive(start) <= v.time[0] <= naive(start + timedelta(minutes=1))
    assert naive(stop - timedelta(minutes=1)) <= v.time[-1] <= naive(stop)
    assert len(np.unique(v.time)) == len(v.time)


def test_overlapping_window_reuses_cached_fragments(fake):
    _call("energy", T0, T0 + timedelta(hours=6))
    _call("energy", T0, T0 + timedelta(hours=12))
    assert len(fake.calls) == 12


def test_store_cleared_after_compute(fake):
    _call("energy", T0, T0 + timedelta(minutes=30))
    assert fake.cleared == 1 and fake.store == {}


def test_store_cleared_even_on_error(fake):
    fake.fail_get_data = True
    with pytest.raises(RuntimeError):
        _call("energy", T0, T0 + timedelta(minutes=30))
    assert fake.cleared == 1


def test_data_dir_is_inside_workspace():
    env = {"SCIQLOP_WORKSPACE_DIR": "/ws"}
    worker.configure_data_dir(env)
    assert env["SPEDAS_DATA_DIR"] == "/ws/spedas_data"


def test_data_dir_untouched_without_workspace():
    env = {}
    worker.configure_data_dir(env)
    assert "SPEDAS_DATA_DIR" not in env
