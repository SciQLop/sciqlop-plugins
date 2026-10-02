"""One live, out-of-process spectrogram product per (source, spectrum).

Probe and data rate are Literal knobs read off the callback signature.
Callbacks capture only the frozen Source and the output name, so they
cloudpickle into SciQLop's worker; their module groups them under one
per-plugin worker process."""
import logging
from typing import Literal

from .catalog import OUTPUTS, SOURCES, Source, product_path
from .convert import EFLUX_UNITS
from .worker import worker_callback

log = logging.getLogger(__name__)

Probe = Literal["1", "2", "3", "4"]
FpiRate = Literal["fast", "brst"]
HpcaRate = Literal["srvy", "brst"]


def build_callback(source: Source, output: str):
    if source.instrument == "fpi":
        def mms_spectrum(start: float, stop: float, probe: Probe = "1", data_rate: FpiRate = "fast"):
            return worker_callback(start, stop, source=source, output=output,
                                   probe=probe, data_rate=data_rate)
    else:
        def mms_spectrum(start: float, stop: float, probe: Probe = "1", data_rate: HpcaRate = "srvy"):
            return worker_callback(start, stop, source=source, output=output,
                                   probe=probe, data_rate=data_rate)
    return mms_spectrum


def hint_spec(output: str) -> dict:
    out = OUTPUTS[output]
    return {
        "display_type": "spectrogram",
        "y2": {"label": out.bin_label, "unit": out.bin_units,
               "scale": "log" if out.bin_log else "linear"},
        "z": {"label": "eflux", "unit": EFLUX_UNITS, "scale": "log"},
    }


def _metadata(source: Source, output: str) -> dict:
    return {
        "DISPLAY_TYPE": "spectrogram",
        "description": f"MMS {source.label} {OUTPUTS[output].label} spectrogram "
                       f"(pyspedas mms_part_getspec)",
    }


def _default_vp_factory(path, callback, *, hints, metadata):
    from SciQLop.components.plotting.backend.easy_provider import EasySpectrogram
    from SciQLop.core.plot_hints import PlotHints

    plot_hints = PlotHints.model_validate(hints)

    # Out-of-process results come back as bare arrays, so the variable-derived
    # hints never run: the log/linear axes must be declared on the product.
    class MmsSpectrogram(EasySpectrogram):
        def plot_hints(self, node):
            return plot_hints

    return MmsSpectrogram(path, callback, metadata=metadata, out_of_process=True)


def register_all(vp_factory=None) -> dict:
    vp_factory = vp_factory or _default_vp_factory
    registered = {}
    for source in SOURCES:
        for output in OUTPUTS:
            path = product_path(source, output)
            try:
                registered[path] = vp_factory(path, build_callback(source, output),
                                              hints=hint_spec(output),
                                              metadata=_metadata(source, output))
            except Exception:  # noqa: BLE001
                log.exception("pyspedas: registration failed for %s", path)
    return registered
