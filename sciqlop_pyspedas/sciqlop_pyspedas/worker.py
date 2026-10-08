"""Worker-side MMS particle spectra on a fixed cache grid: every window is cut
into 1 h fragments aligned on UTC hours, each fragment is one
mms_part_getspec call and one cache entry per spectrum.

Runs in SciQLop's per-plugin remote worker: single-threaded, so pyspedas's
global tplot store is never shared between concurrent requests."""
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
from speasy.core.cache import add_item, get_item
from speasy.products.variable import merge

from .catalog import OUTPUTS, Source, cache_key, tplot_name
from .convert import empty_spectrum, spectrum_variable

# One size for every data rate: bounds memory for burst electrons, and keeps
# cache entries predictable (same key grid whatever window the user asks for).
FRAGMENT = timedelta(hours=1)


def configure_data_dir(environ=os.environ) -> None:
    workspace = environ.get("SCIQLOP_WORKSPACE_DIR")
    if workspace:
        environ["SPEDAS_DATA_DIR"] = os.path.join(workspace, "spedas_data")


def _pyspedas_api() -> SimpleNamespace:
    """The only place pyspedas is imported; tests replace this function."""
    configure_data_dir()
    from pyspedas import del_data, get_data
    from pyspedas.projects.mms import mms_part_getspec

    from . import espec, regrid
    espec.install()
    regrid.install()
    return SimpleNamespace(getspec=mms_part_getspec, get_data=get_data, del_data=del_data)


def fragments(start: datetime, stop: datetime):
    """Start times of the fixed hour fragments covering [start, stop)."""
    t = start.replace(minute=0, second=0, microsecond=0)
    while t < stop:
        yield t
        t += FRAGMENT


def _trange(start: datetime, stop: datetime) -> list:
    return [t.strftime("%Y-%m-%d/%H:%M:%S") for t in (start, stop)]


def _read_output(api, name: str, output: str, produced: list):
    if name not in produced:
        return empty_spectrum(output, name)
    data = api.get_data(name, dt=True)
    return spectrum_variable(data.times, data.y, data.v, output, name)


def compute_all(source: Source, probe: str, data_rate: str, start: datetime, stop: datetime) -> dict:
    """All spectra for one window from a single getspec call."""
    api = _pyspedas_api()
    try:
        produced = api.getspec(instrument=source.instrument, probe=probe, species=source.species,
                               data_rate=data_rate, trange=_trange(start, stop),
                               output=list(OUTPUTS)) or []
        return {out: _read_output(api, tplot_name(source, probe, data_rate, out), out, produced)
                for out in OUTPUTS}
    finally:
        api.del_data("*")


def _fragment_key(source, probe, data_rate, output, start: datetime) -> str:
    return f"sciqlop_pyspedas/{cache_key(source, probe, data_rate, output)}/{start:%Y-%m-%dT%H}"


def _compute_fragment(source, probe, data_rate, start: datetime) -> dict:
    """Compute one fragment and cache every non-empty spectrum of it.

    Empty spectra are never cached: pyspedas returns nothing both for real gaps
    and failed downloads, so caching would blank a window after one glitch.
    Retrying a real gap only costs an SDC file-list query."""
    spectra = compute_all(source, probe, data_rate, start, start + FRAGMENT)
    for output, variable in spectra.items():
        if len(variable.time):
            add_item(_fragment_key(source, probe, data_rate, output, start), variable)
    return spectra


def _fragment_spectrum(start: datetime, *, source, output, probe, data_rate):
    cached = get_item(_fragment_key(source, probe, data_rate, output, start))
    if cached is not None:
        return cached
    variable = _compute_fragment(source, probe, data_rate, start)[output]
    return variable if len(variable.time) else None


def _trim(variable, start: datetime, stop: datetime):
    lo, hi = (np.datetime64(t.replace(tzinfo=None), "ns") for t in (start, stop))
    keep = (variable.time >= lo) & (variable.time < hi)
    return variable[keep] if keep.any() else None


def worker_callback(start: float, stop: float, *, source: Source, output: str,
                    probe: str, data_rate: str):
    t0 = datetime.fromtimestamp(float(start), tz=timezone.utc)
    t1 = datetime.fromtimestamp(float(stop), tz=timezone.utc)
    parts = [_fragment_spectrum(f, source=source, output=output, probe=probe, data_rate=data_rate)
             for f in fragments(t0, t1)]
    whole = merge([p for p in parts if p is not None])
    return None if whole is None else _trim(whole, t0, t1)
