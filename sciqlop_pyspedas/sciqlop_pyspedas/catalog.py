"""What the plugin exposes: MMS particle sources × spectra, and the names
pyspedas 2.2 gives them."""
from dataclasses import dataclass
from typing import NamedTuple


class Output(NamedTuple):
    label: str
    bin_label: str
    bin_units: str
    bin_log: bool


OUTPUTS = {
    "energy": Output("energy", "energy", "eV", True),
    "pa": Output("pitch angle", "pitch angle", "deg", False),
    "gyro": Output("gyrophase", "gyrophase", "deg", False),
}


@dataclass(frozen=True)
class Source:
    instrument: str
    species: str
    label: str
    data_rates: tuple


_FPI_RATES = ("fast", "brst")
_HPCA_RATES = ("srvy", "brst")

SOURCES = (
    Source("fpi", "i", "FPI ions", _FPI_RATES),
    Source("fpi", "e", "FPI electrons", _FPI_RATES),
    Source("hpca", "hplus", "HPCA H+", _HPCA_RATES),
    Source("hpca", "heplus", "HPCA He+", _HPCA_RATES),
    Source("hpca", "heplusplus", "HPCA He++", _HPCA_RATES),
    Source("hpca", "oplus", "HPCA O+", _HPCA_RATES),
)

PROBES = ("1", "2", "3", "4")


def tplot_name(source: Source, probe: str, data_rate: str, output: str) -> str:
    """Output name built by pyspedas mms_part_getspec/mms_part_products."""
    if source.instrument == "fpi":
        base = f"mms{probe}_d{source.species}s_dist_{data_rate}"
    else:
        base = f"mms{probe}_hpca_{source.species}_phase_space_density"
    return f"{base}_{output}"


def cache_key(source: Source, probe: str, data_rate: str, output: str) -> str:
    # Not tplot_name: HPCA names carry no data rate, so srvy and brst would collide.
    return f"mms{probe}/{source.instrument}/{source.species}/{data_rate}/{output}"


def product_path(source: Source, output: str) -> str:
    return f"pyspedas/MMS/{source.label}/{OUTPUTS[output].label}"
