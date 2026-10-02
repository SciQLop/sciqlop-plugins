"""Worker-side MMS particle spectra: range cap → hour-fragment cache →
one mms_part_getspec call for all spectra.

Runs in SciQLop's per-plugin remote worker: single-threaded, so pyspedas's
global tplot store is never shared between concurrent requests."""
import os
from datetime import datetime, timezone
from functools import lru_cache
from types import SimpleNamespace

from speasy.core.cache import Cacheable

from .catalog import OUTPUTS, Source, cache_key, tplot_name
from .convert import empty_spectrum, spectrum_variable

# simplify: fixed caps tuned by hand during the experiment; burst requests
# still compute whole hour fragments (burst data is sparse, so that stays small).
# Upgrade path: a settings entry snapshotted into the callback at registration.
MAX_HOURS = {"fast": 6.0, "srvy": 6.0, "brst": 0.5}


class RangeTooLong(ValueError):
    pass


def check_range(start: datetime, stop: datetime, data_rate: str) -> None:
    hours = (stop - start).total_seconds() / 3600
    cap = MAX_HOURS[data_rate]
    if hours > cap:
        raise RangeTooLong(
            f"MMS {data_rate} particle spectra: {hours:.1f} h requested, "
            f"at most {cap:g} h per request. Zoom in."
        )


def configure_data_dir(environ=os.environ) -> None:
    workspace = environ.get("SCIQLOP_WORKSPACE_DIR")
    if workspace:
        environ["SPEDAS_DATA_DIR"] = os.path.join(workspace, "spedas_data")


def _pyspedas_api() -> SimpleNamespace:
    """The only place pyspedas is imported; tests replace this function."""
    configure_data_dir()
    from pyspedas import del_data, get_data
    from pyspedas.projects.mms import mms_part_getspec

    return SimpleNamespace(getspec=mms_part_getspec, get_data=get_data, del_data=del_data)


def _trange(start: datetime, stop: datetime) -> list:
    return [t.strftime("%Y-%m-%d/%H:%M:%S") for t in (start, stop)]


def _read_output(api, name: str, output: str, produced: list):
    if name not in produced:
        return empty_spectrum(output, name)
    data = api.get_data(name, dt=True)
    return spectrum_variable(data.times, data.y, data.v, output, name)


@lru_cache(maxsize=1)
def compute_all(source: Source, probe: str, data_rate: str, start: datetime, stop: datetime) -> dict:
    """All spectra for one window from a single getspec call; memoized so the
    sibling spectra requested next for the same fragment cost nothing."""
    api = _pyspedas_api()
    try:
        produced = api.getspec(instrument=source.instrument, probe=probe, species=source.species,
                               data_rate=data_rate, trange=_trange(start, stop),
                               output=list(OUTPUTS)) or []
        return {out: _read_output(api, tplot_name(source, probe, data_rate, out), out, produced)
                for out in OUTPUTS}
    finally:
        api.del_data("*")


class _SpectrumCache:
    """Method-style holder: speasy's Cacheable wraps (self, product, start, stop, ...)."""

    @Cacheable(prefix="pyspedas_mms", fragment_hours=lambda product: 1)
    def spectrum(self, product, start_time, stop_time, *, source, probe, data_rate, output):
        return compute_all(source, probe, data_rate, start_time, stop_time)[output]


_CACHE = _SpectrumCache()


def worker_callback(start: float, stop: float, *, source: Source, output: str,
                    probe: str, data_rate: str):
    t0 = datetime.fromtimestamp(float(start), tz=timezone.utc)
    t1 = datetime.fromtimestamp(float(stop), tz=timezone.utc)
    check_range(t0, t1, data_rate)
    return _CACHE.spectrum(cache_key(source, probe, data_rate, output), t0, t1,
                           source=source, probe=probe, data_rate=data_rate, output=output)
