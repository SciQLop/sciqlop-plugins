"""pyspedas spectrogram arrays (get_data) → SpeasyVariable."""
import numpy as np
from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
from speasy.products.variable import SpeasyVariable

from .catalog import OUTPUTS

EFLUX_UNITS = "eV/(cm^2 s sr eV)"


def _bin_axis(bins: np.ndarray, output: str) -> VariableAxis:
    out = OUTPUTS[output]
    return VariableAxis(
        values=bins,
        meta={"FIELDNAM": out.bin_label, "UNITS": out.bin_units,
              "SCALETYP": "log" if out.bin_log else "linear"},
        name=out.bin_label,
        is_time_dependent=bins.ndim == 2,
    )


def spectrum_variable(times, values, bins, output: str, name: str) -> SpeasyVariable:
    data = DataContainer(
        values=np.asarray(values, dtype=np.float64),
        meta={"FIELDNAM": name, "UNITS": EFLUX_UNITS, "SCALETYP": "log",
              "DISPLAY_TYPE": "spectrogram"},
        name=name,
    )
    time_axis = VariableTimeAxis(values=np.asarray(times).astype("datetime64[ns]"))
    return SpeasyVariable(axes=[time_axis, _bin_axis(np.asarray(bins, dtype=np.float64), output)],
                          values=data)


def empty_spectrum(output: str, name: str) -> SpeasyVariable:
    """Zero rows: the "sure there is no data" answer Speasy's cache stores."""
    return spectrum_variable(np.array([], dtype="datetime64[ns]"), np.empty((0, 1)),
                             np.zeros(1), output, name)
