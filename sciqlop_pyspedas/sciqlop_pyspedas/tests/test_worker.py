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
    _call("energy", T0, T0 + timedelta(minutes=30))
    _call("pa", T0, T0 + timedelta(minutes=30))
    _call("gyro", T0, T0 + timedelta(minutes=30))
    assert len(fake.calls) == 1


def test_repeat_request_served_from_disk_cache(fake):
    _call("energy", T0, T0 + timedelta(minutes=30))
    worker.compute_all.cache_clear()
    _call("energy", T0, T0 + timedelta(minutes=30))
    assert len(fake.calls) == 1


def test_no_data_is_cached_not_refetched(fake):
    fake.has_data = False
    first = _call("energy", T0, T0 + timedelta(minutes=30))
    worker.compute_all.cache_clear()
    second = _call("energy", T0, T0 + timedelta(minutes=30))
    assert first is None or len(first.time) == 0
    assert second is None or len(second.time) == 0
    assert len(fake.calls) == 1


def test_cache_key_distinguishes_hpca_rates(fake):
    _call("energy", T0, T0 + timedelta(minutes=10), source=HPCA_H, data_rate="srvy")
    _call("energy", T0, T0 + timedelta(minutes=10), source=HPCA_H, data_rate="brst")
    assert [c["data_rate"] for c in fake.calls] == ["srvy", "brst"]


def test_range_cap_boundary(fake):
    _call("energy", T0, T0 + timedelta(hours=6))
    with pytest.raises(worker.RangeTooLong, match="Zoom in"):
        _call("energy", T0, T0 + timedelta(hours=6, seconds=1))
    with pytest.raises(worker.RangeTooLong):
        _call("energy", T0, T0 + timedelta(minutes=31), data_rate="brst")


def test_refused_range_downloads_nothing(fake):
    with pytest.raises(worker.RangeTooLong):
        _call("energy", T0, T0 + timedelta(days=1))
    assert fake.calls == []


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
