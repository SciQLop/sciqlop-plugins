"""Virtual product registration for the ground-fit MSA moments."""
from datetime import datetime, timedelta, timezone

import numpy as np

from .moments_compute import fit_day
from .moments_fit import SPECIES_MASS_TABLE

FIELDS = {
    "density": ("n_tot", "cm^-3"),
    "T_c": ("T_c", "eV"),
    "T_eff": ("T_eff", "eV"),
}

_APPROXIMATE_SPECIES = {
    "heavies": "O+ proxy (A=16, q=1) — diff_dir_en_flux_heavies sums species of different mass.",
    "total": "proton-equivalent (A=1.00728, q=1) — diff_dir_en_flux_total sums species of different mass.",
}

_registered_vps = []


def _days_between(start_dt: datetime, stop_dt: datetime):
    day = start_dt.date()
    last_day = stop_dt.date()
    while day <= last_day:
        yield day
        day += timedelta(days=1)


def _description(species: str, field: str) -> str:
    base = f"MSA {species} ground-fit {field}, from a Maxwellian+Kappa spectral fit."
    approx = _APPROXIMATE_SPECIES.get(species)
    return f"{base} Approximate: fitted assuming a {approx}" if approx else base


def _make_callback(species: str, field: str):
    attr, unit = FIELDS[field]

    def callback(start: float, stop: float):
        from speasy.products import SpeasyVariable, VariableTimeAxis, DataContainer

        start_dt = datetime.fromtimestamp(float(start), tz=timezone.utc)
        stop_dt = datetime.fromtimestamp(float(stop), tz=timezone.utc)

        times, values = [], []
        for day in _days_between(start_dt, stop_dt):
            day_fits = fit_day(species, day)
            if day_fits is None:
                continue
            times.append(day_fits.time)
            values.append(getattr(day_fits, attr))

        if not times:
            return None

        time = np.concatenate(times)
        value = np.concatenate(values)
        order = np.argsort(time)
        time, value = time[order], value[order]

        keep = (time >= float(start)) & (time <= float(stop))
        time, value = time[keep], value[keep]
        if len(time) == 0:
            return None

        return SpeasyVariable(
            axes=[VariableTimeAxis(values=(time * 1e9).astype("int64").astype("datetime64[ns]"))],
            values=DataContainer(
                values=value,
                meta={
                    "UNITS": unit,
                    "LABLAXIS": field,
                    "SCALETYP": "log",
                    "CATDESC": _description(species, field),
                },
                is_time_dependent=True,
            ),
        )

    return callback


def register_moments_vps() -> list:
    from SciQLop.user_api.virtual_products import create_virtual_product, VirtualProductType

    for species in SPECIES_MASS_TABLE:
        for field in FIELDS:
            display_name = f"{field} ({species}, approx.)" if species in _APPROXIMATE_SPECIES else None
            label = f"{field} (approx.)" if species in _APPROXIMATE_SPECIES else field
            vp = create_virtual_product(
                path=f"msa/moments_fit/{species}/{field}",
                callback=_make_callback(species, field),
                product_type=VirtualProductType.Scalar,
                labels=[label],
                cachable=True,
                display_name=display_name,
            )
            _registered_vps.append(vp)
    return _registered_vps
