"""Continuous (per source-channel) virtual products.

Each `ContinuousSource` is registered as one `VirtualProductType.Spectrogram`
virtual product whose callback fetches whatever files cover the requested
`(start, stop)` on demand:

  1. `Fido.search(Time(start, stop), *attrs)` — radiospectra clients are
     registered via `radiospectra.net` (see fetch.py).
  2. Download missing files (re-uses the same on-disk cache as the dock).
  3. Parse + convert each file via `_open_and_convert` (Speasy disk cache).
  4. Concatenate along the time axis into a single `SpeasyVariable`.

The callback runs on SciQLop's data thread (not the GUI thread), so the
synchronous Fido.search/fetch path is acceptable — only the first visit
to a time window pays the network cost; cache hits are instant.

Per-observatory sources (RSTN, e-CALLISTO) are intentionally NOT here:
each carries hundreds of stations with mismatched frequency grids, so a
single per-source VP would render a meaningless blended colormap. They
need an observatory picker first — v2.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional

import numpy as np

log = logging.getLogger(__name__)


MAX_FILES_PER_CALL = 32


@dataclass(frozen=True)
class ContinuousSource:
    """One entry in the continuous-source registry.

    `attrs_factory` returns the `sunpy.net.attrs` list (excluding `a.Time`,
    which we add per call) — lazy because sunpy/radiospectra imports are
    slow and should only fire when SciQLop actually drags a product onto
    a panel.
    """

    vp_path: str
    label: str
    attrs_factory: Callable[[], list]
    max_files: int = MAX_FILES_PER_CALL


def _format_time_for_fido(t: datetime) -> str:
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc).replace(tzinfo=None)
    return t.isoformat(sep="T", timespec="seconds")


def _attrs_psp_rfs_lfr() -> list:
    import astropy.units as u
    from sunpy.net import attrs as a
    return [a.Instrument("RFS"), a.Wavelength(10 * u.kHz, 1.7 * u.MHz)]


def _attrs_psp_rfs_hfr() -> list:
    import astropy.units as u
    from sunpy.net import attrs as a
    return [a.Instrument("RFS"), a.Wavelength(1.3 * u.MHz, 19.2 * u.MHz)]


def _attrs_eovsa() -> list:
    from sunpy.net import attrs as a
    return [a.Instrument("EOVSA")]


def _attrs_ilofar() -> list:
    from sunpy.net import attrs as a
    return [a.Instrument("ILOFAR")]


CONTINUOUS_SOURCES: list[ContinuousSource] = [
    ContinuousSource(
        vp_path="radio/psp_rfs_lfr",
        label="PSP/RFS LFR",
        attrs_factory=_attrs_psp_rfs_lfr,
    ),
    ContinuousSource(
        vp_path="radio/psp_rfs_hfr",
        label="PSP/RFS HFR",
        attrs_factory=_attrs_psp_rfs_hfr,
    ),
    ContinuousSource(
        vp_path="radio/eovsa",
        label="EOVSA",
        attrs_factory=_attrs_eovsa,
    ),
    ContinuousSource(
        vp_path="radio/ilofar",
        label="ILOFAR (mode 357 BST)",
        attrs_factory=_attrs_ilofar,
    ),
]


def _cache_path_for_row(row: Any, cache_dir: Path) -> Path:
    """Mirrors fetch.py's `_cache_path_for` so the on-demand callback and the
    dock's imperative fetch share the same on-disk cache."""
    url = getattr(row, "url", None) or ""
    name = url.rsplit("/", 1)[-1] if url else ""
    return cache_dir / name if name else cache_dir / "__unknown__"


def _fido_search(t0: datetime, t1: datetime, source: ContinuousSource) -> list:
    import radiospectra.net  # noqa: F401 — registers RFS/eCALLISTO/EOVSA/ILOFAR/RSTN
    from sunpy.net import Fido, attrs as a
    response = Fido.search(
        a.Time(_format_time_for_fido(t0), _format_time_for_fido(t1)),
        *source.attrs_factory(),
    )
    rows: list = []
    for table in response:
        for row in table:
            rows.append(row)
    return rows


def _fetch_paths(rows: Iterable[Any], cache_dir: Path) -> List[Path]:
    """Download missing files synchronously. Reuses cached files on disk.

    Returns paths in the same order as `rows` (paths that failed to
    download are silently skipped — the callback handles the deficit)."""
    from sunpy.net import Fido

    cache_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    to_fetch: list[Any] = []
    for row in rows:
        cached = _cache_path_for_row(row, cache_dir)
        if cached.exists():
            out.append(cached)
        else:
            to_fetch.append(row)

    if to_fetch:
        for row in to_fetch:
            try:
                result = Fido.fetch(row, path=str(cache_dir / "{file}"))
                for p in result:
                    out.append(Path(p))
            except Exception as exc:  # noqa: BLE001
                log.warning("continuous: Fido.fetch failed for %s: %s",
                            getattr(row, "url", row), exc)
    return out


def _concat_spectrograms(variables: list):
    """Concatenate a list of 2-D SpeasyVariables along the time axis.

    Assumes a shared frequency grid (PSP/RFS receiver mode is fixed within a
    source-channel; EOVSA + ILOFAR are also single-grid). Variables with
    a divergent shape are skipped — that's safer than producing a garbled
    colormap.
    """
    from speasy.core.data_containers import DataContainer, VariableTimeAxis
    from speasy.products.variable import SpeasyVariable

    if not variables:
        return None
    variables = sorted(variables, key=lambda v: v.time[0])
    ref = variables[0]
    ref_n_freq = ref.values.shape[1]
    kept = [v for v in variables if v.values.shape[1] == ref_n_freq]
    skipped = len(variables) - len(kept)
    if skipped:
        log.warning("continuous: dropped %d file(s) with mismatched frequency grid", skipped)
    if not kept:
        return None
    if len(kept) == 1:
        return kept[0]
    times = np.concatenate([v.time for v in kept])
    data = np.concatenate([np.asarray(v.values) for v in kept], axis=0)
    time_axis = VariableTimeAxis(values=times.astype("datetime64[ns]"))
    freq_axis = ref.axes[1]
    values = DataContainer(
        values=np.ascontiguousarray(data),
        meta=dict(ref.meta or {}),
        name=ref.name,
    )
    return SpeasyVariable(axes=[time_axis, freq_axis], values=values, columns=ref.columns)


def _build_callback(
    source: ContinuousSource,
    cache_dir: Path,
    open_and_convert: Callable[[Path], Any],
):
    """Return the `(start, stop) → SpeasyVariable | None` callback SciQLop
    will invoke when the user pans/zooms over this product's time range.
    """

    def _callback(start, stop, **kwargs):  # noqa: ARG001 — accept knobs for SciQLop fwd-compat
        t0 = datetime.fromtimestamp(float(start), tz=timezone.utc)
        t1 = datetime.fromtimestamp(float(stop), tz=timezone.utc)
        t_search = time.monotonic()
        log.warning(  # WARNING so it shows up in SciQLop's log widget by default
            "continuous(%s): callback fired for [%s .. %s]",
            source.vp_path, t0.isoformat(), t1.isoformat(),
        )
        try:
            rows = _fido_search(t0, t1, source)
        except Exception as exc:  # noqa: BLE001
            log.exception("continuous(%s): Fido.search failed: %s", source.vp_path, exc)
            return None
        log.warning(
            "continuous(%s): Fido.search returned %d row(s) in %.1fs",
            source.vp_path, len(rows), time.monotonic() - t_search,
        )
        if not rows:
            return None

        # Cap: if the user's visible range covers more files than we'll
        # download in one go, return None and tell them to zoom in. Silent
        # truncation would only show data at one end of the range — confusing.
        if len(rows) > source.max_files:
            log.warning(
                "continuous(%s): %d rows for [%s..%s] exceeds max_files=%d. "
                "Zoom in to a window that covers fewer files (or raise "
                "ContinuousSource.max_files).",
                source.vp_path, len(rows), t0.isoformat(), t1.isoformat(),
                source.max_files,
            )
            return None

        t_fetch = time.monotonic()
        paths = _fetch_paths(rows, cache_dir)
        log.warning(
            "continuous(%s): fetched %d/%d file(s) in %.1fs",
            source.vp_path, len(paths), len(rows), time.monotonic() - t_fetch,
        )

        t_parse = time.monotonic()
        variables = []
        for p in paths:
            try:
                v = open_and_convert(p)
            except Exception as exc:  # noqa: BLE001
                log.warning("continuous(%s): parse failed for %s: %s",
                            source.vp_path, p.name, exc)
                continue
            if v is not None:
                variables.append(v)
        log.warning(
            "continuous(%s): parsed %d/%d file(s) in %.1fs",
            source.vp_path, len(variables), len(paths), time.monotonic() - t_parse,
        )

        out = _concat_spectrograms(variables)
        if out is None:
            log.warning("continuous(%s): no usable data after concat", source.vp_path)
        else:
            log.warning(
                "continuous(%s): returning SpeasyVariable shape=%s",
                source.vp_path, tuple(out.values.shape),
            )
        return out

    return _callback


@dataclass
class ContinuousRegistration:
    """Live handle on the registered VPs — keeps them alive against GC."""

    vps: dict[str, Any] = field(default_factory=dict)


def register_continuous_products(
    cache_dir: Path,
    open_and_convert: Callable[[Path], Any],
) -> Optional[ContinuousRegistration]:
    """Register one VP per `ContinuousSource`. Returns None when SciQLop's
    virtual-products API isn't importable (headless tests)."""
    try:
        from SciQLop.user_api.virtual_products import (
            create_virtual_product, VirtualProductType,
        )
    except ImportError as exc:
        log.warning("continuous: SciQLop user_api unavailable: %s", exc)
        return None

    reg = ContinuousRegistration()
    for src in CONTINUOUS_SOURCES:
        cb = _build_callback(src, cache_dir, open_and_convert)
        try:
            vp = create_virtual_product(src.vp_path, cb, VirtualProductType.Spectrogram)
        except Exception as exc:  # noqa: BLE001
            log.exception("continuous: create_virtual_product failed for %s: %s",
                          src.vp_path, exc)
            continue
        reg.vps[src.vp_path] = vp
    return reg
