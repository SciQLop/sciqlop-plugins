"""LOFAR LBA tied-array dynamic spectra — virtual product.

LOFAR FITS dynamic-spectra files don't live in Speasy or in any of the Fido
clients we already use; instead we ship a static index JSON (one entry per
file) hosted alongside the data at LPP. The index gives us, for each file,
its (beam, SAP, time-range, URL). The callback:

  1. Loads the index once (downloads + unzips to `cache_dir/lofar_index.json`
     on first hit; lru-cached per (beam, SAP) afterwards).
  2. Filters entries that intersect the requested `(start, stop)`.
  3. Reads each FITS via `speasy.core.any_files.any_loc_open(cache_remote_files=True)`
     — Speasy's HTTP cache, so subsequent visits skip the network.
  4. Parses to a 2-D `SpeasyVariable` (time × frequency), `@CacheCall(is_pure=True)`-cached
     by URL so the FITS parse + reshape doesn't re-run cross-session.
  5. Merges them into one `SpeasyVariable` via `speasy.products.variable.merge`.

Beam (0-216) and SAP (0-1) are exposed as knobs so the user can switch
beams without re-registering the VP.
"""
from __future__ import annotations

import io
import json
import logging
import threading
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Callable, Optional

import numpy as np

log = logging.getLogger(__name__)


# Module-level Knob binding — SciQLop's `_arguments_type` calls
# `inspect.signature(callback, eval_str=True)`, which re-evaluates the
# stringified Annotated[int, Knob(...)] annotations in *this* module's
# globals. A lazy import inside `_build_callback` is invisible to that
# eval and raises NameError at VP-registration time. Headless tests
# (no SciQLop install) fall back to a no-op stub so module import
# never breaks.
try:
    from SciQLop.user_api.knobs import Knob
except ImportError:  # pragma: no cover — only hit in headless CI
    class Knob:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            pass


LOFAR_INDEX_URL = "https://hephaistos.lpp.polytechnique.fr/data/jeandet/lofar_index.zip"
LOFAR_INDEX_FILENAME = "lofar_index.json"

# FITS files whose frequency grid isn't the canonical 800-bin LBA layout are
# rejected — merging mismatched grids produces a garbled colormap.
_EXPECTED_N_FREQ = 800

LOFAR_META: dict[str, Any] = {
    "DISPLAY_TYPE": "spectrogram",
    "SCALETYP": "log",
    "description": "LOFAR LBA tied-array dynamic spectrum (10-90 MHz)",
    "provider": "LOFAR",
    "UNITS": "Hz",
}

LOFAR_VP_PATH = "radio/LOFAR/LBA"

_index_download_lock = threading.Lock()


@dataclass(frozen=True)
class _Entry:
    url: str
    t0: datetime
    t1: datetime
    source: str
    filename: str


# ---------------------------------------------------------------------------
# Index download + parse
# ---------------------------------------------------------------------------


def _index_path(cache_dir: Path) -> Path:
    return cache_dir / LOFAR_INDEX_FILENAME


def _download_index(cache_dir: Path) -> Path:
    """Ensure the LOFAR index JSON exists under `cache_dir`. Downloads the
    zip from LPP on first hit and extracts `index.json` into `cache_dir`.
    Concurrent calls are serialized; we don't re-download if the file's
    already there."""
    import requests

    cache_dir.mkdir(parents=True, exist_ok=True)
    target = _index_path(cache_dir)
    with _index_download_lock:
        if target.exists():
            return target
        log.warning("lofar: downloading index from %s", LOFAR_INDEX_URL)
        resp = requests.get(LOFAR_INDEX_URL, timeout=60)
        resp.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            members = [m for m in z.namelist() if m.lower().endswith(".json")]
            if not members:
                raise RuntimeError(
                    f"lofar: {LOFAR_INDEX_URL} contains no .json file (got {z.namelist()!r})"
                )
            # Materialize to a temp file alongside the target, then atomic-rename
            # so a torn write doesn't leave a half-extracted JSON in cache_dir.
            data = z.read(members[0])
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        return target


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 timestamp from the index. Naive timestamps are
    treated as UTC (the LOFAR index ships UTC throughout)."""
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_index(text: str) -> list[_Entry]:
    """Parse the LOFAR index JSON text into `_Entry` objects.

    Tolerates entries missing keys — they are skipped with a warning.
    Exported (no underscore-prefix) so tests can hit it without going through
    the on-disk cache.
    """
    raw = json.loads(text)
    if not isinstance(raw, list):
        raise ValueError(f"lofar: index must be a JSON list, got {type(raw).__name__}")
    out: list[_Entry] = []
    for i, item in enumerate(raw):
        try:
            url = item["url"]
            tr = item["time_range"]
            t0 = _parse_iso(tr[0])
            t1 = _parse_iso(tr[1])
            source = item["source"]
            filename = item["filename"]
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("lofar: skipping malformed index entry %d: %s", i, exc)
            continue
        out.append(_Entry(url=url, t0=t0, t1=t1, source=source, filename=filename))
    return out


def _load_index(cache_dir: Path) -> list[_Entry]:
    """Load the index from disk (downloading if needed), unparsed-cache once."""
    return _load_index_cached(_download_index(cache_dir))


@lru_cache(maxsize=4)
def _load_index_cached(path: Path) -> list[_Entry]:
    return parse_index(path.read_text())


@lru_cache(maxsize=512)
def _entries_for(cache_dir: Path, beam: str, sap: str) -> tuple[_Entry, ...]:
    """All entries matching `beam` and `sap`, sorted by start time. Cached so
    repeated callback hits don't re-filter the whole index."""
    entries = [e for e in _load_index(cache_dir) if beam in e.source and sap in e.source]
    entries.sort(key=lambda e: e.t0)
    return tuple(entries)


def _entries_in_range(
    cache_dir: Path, t0: datetime, t1: datetime, beam: str, sap: str
) -> list[_Entry]:
    return [e for e in _entries_for(cache_dir, beam, sap) if e.t0 < t1 and e.t1 > t0]


def _fits_url_for_entry(entry: _Entry) -> str:
    """Translate a `.../json_files/<name>.json` index URL into the matching
    `.../dynamic_spectra/<name>.fits` data URL."""
    head, _, _ = entry.url.rpartition("/json_files/")
    if not head:
        # Index already points at the data URL — pass through.
        return entry.url
    stem = entry.filename[:-5] if entry.filename.lower().endswith(".json") else entry.filename
    return f"{head}/dynamic_spectra/{stem}.fits"


# ---------------------------------------------------------------------------
# FITS → SpeasyVariable
# ---------------------------------------------------------------------------


def _lofar_time(t_arr: np.ndarray) -> np.ndarray:
    """Convert a LOFAR FITS TIME column to `datetime64[ns]`.

    The TIME column in LOFAR FITS dynamic spectra is days-since-epoch; the
    epoch is either Unix (1970-01-01) for recent files or 0000-12-31 (a
    Julian-ish reference) for older ones. We pick by magnitude — modern
    UTC days are < 1e5, JD-like values are >> 1e5. Inherited from the
    LPP LOFAR FITS files; updating this requires testing against a real
    file from each cohort.
    """
    t_arr = np.asarray(t_arr, dtype=np.float64)
    base = np.datetime64("1970-01-01") if t_arr[0] < 1e5 else np.datetime64("0000-12-31")
    days = np.floor(t_arr).astype(np.int64)
    ns = np.round((t_arr - days) * 86400e9).astype(np.int64)
    return base + days.astype("timedelta64[D]") + ns.astype("timedelta64[ns]")


_cached_read_lofar = None


def _make_cached_read_lofar():
    from datetime import timedelta

    from speasy.core.cache import CacheCall

    @CacheCall(cache_retention=timedelta(days=30), is_pure=True)
    def _cached(url: str):
        return _read_lofar_uncached(url)

    return _cached


def _read_lofar_uncached(url: str):
    """Open a LOFAR FITS file by URL, parse, return a 2-D `SpeasyVariable` or None.

    Returns None (with a warning) for files whose frequency grid isn't the
    canonical 800-bin layout — keeping them would either force-skip the merge
    or produce a garbled colormap. Returns None for any parse error too.
    """
    from astropy.io import fits
    import speasy as spz
    from speasy.core.data_containers import DataContainer, VariableAxis, VariableTimeAxis
    from speasy.products.variable import SpeasyVariable

    try:
        with fits.open(spz.core.any_files.any_loc_open(url, cache_remote_files=True)) as hdul:
            values = hdul[0].data.astype(np.float32)
            header_meta = dict(hdul[0].header)
            axes_table = hdul[1].data
            freq = np.asarray(axes_table["FREQ"][0]).astype(np.float32)
            time = _lofar_time(axes_table["TIME"][0])
    except Exception as exc:  # noqa: BLE001
        log.warning("lofar: parse failed for %s: %s", url, exc)
        return None

    if freq.shape[0] != _EXPECTED_N_FREQ:
        log.debug(
            "lofar: dropping %s — frequency grid is %d bins, expected %d",
            url, freq.shape[0], _EXPECTED_N_FREQ,
        )
        return None

    return SpeasyVariable(
        axes=[
            VariableTimeAxis(time, meta={"FIELDNAM": "Time"}),
            VariableAxis(
                freq * 1e6,  # MHz → Hz; 1-D, the LBA receiver grid is fixed within a file
                meta={"FIELDNAM": "Frequency", "UNITS": "Hz"},
            ),
        ],
        values=DataContainer(values, meta=header_meta),
    )


def _read_lofar(url: str):
    """Cached front-end for `_read_lofar_uncached` — uses Speasy's `CacheCall`
    when available, falls back to a direct call if the cache layer isn't
    importable (headless tests)."""
    global _cached_read_lofar
    try:
        if _cached_read_lofar is None:
            _cached_read_lofar = _make_cached_read_lofar()
        return _cached_read_lofar(url)
    except Exception:  # noqa: BLE001
        return _read_lofar_uncached(url)


# ---------------------------------------------------------------------------
# Virtual-product callback + registration
# ---------------------------------------------------------------------------


def _build_callback(cache_dir: Path) -> Callable[..., Any]:
    """Build the SciQLop callback. `Knob` is bound at module top so the
    stringified Annotated[int, Knob(...)] annotations resolve when SciQLop
    introspects the signature."""

    def lofar(
        start: float,
        stop: float,
        beam: Annotated[int, Knob(min=0, max=216, step=1, label="Beam")] = 0,
        sap: Annotated[int, Knob(min=0, max=1, step=1, label="SAP")] = 0,
    ):
        from speasy.products.variable import merge

        t0 = datetime.fromtimestamp(start, tz=timezone.utc)
        t1 = datetime.fromtimestamp(stop, tz=timezone.utc)
        beam_tag = f"B{int(beam):03d}"
        sap_tag = f"SAP00{int(sap)}"
        try:
            entries = _entries_in_range(cache_dir, t0, t1, beam_tag, sap_tag)
        except Exception as exc:  # noqa: BLE001
            log.exception("lofar: failed to read index: %s", exc)
            return None
        if not entries:
            log.debug(
                "lofar: no files cover [%s..%s] for %s/%s",
                t0.isoformat(), t1.isoformat(), beam_tag, sap_tag,
            )
            return None
        log.debug(
            "lofar: %d file(s) for [%s..%s] %s/%s",
            len(entries), t0.isoformat(), t1.isoformat(), beam_tag, sap_tag,
        )
        variables = []
        for entry in entries:
            v = _read_lofar(_fits_url_for_entry(entry))
            if v is not None:
                variables.append(v)
        if not variables:
            return None
        try:
            return merge(variables)
        except Exception as exc:  # noqa: BLE001
            log.warning("lofar: merge failed (%d var(s)): %s", len(variables), exc)
            return None

    return lofar


@dataclass
class LofarRegistration:
    """Live handle on the registered LOFAR VP — keeps it alive vs GC."""

    vp: Any = None


def register_lofar_product(
    cache_dir: Path,
    *,
    vp_factory: Optional[Callable[..., Any]] = None,
) -> Optional[LofarRegistration]:
    """Register the single LOFAR LBA virtual product. Returns None when
    SciQLop's user_api isn't importable (headless tests)."""
    try:
        from SciQLop.user_api.virtual_products import VirtualProductType
    except ImportError as exc:
        log.warning("lofar: SciQLop user_api unavailable: %s", exc)
        return None

    if vp_factory is None:
        from .hints import make_rich_vp
        vp_factory = make_rich_vp

    cb = _build_callback(Path(cache_dir))
    try:
        vp = vp_factory(
            LOFAR_VP_PATH, cb, VirtualProductType.Spectrogram,
            metadata=LOFAR_META,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("lofar: vp_factory failed: %s", exc)
        return LofarRegistration()
    return LofarRegistration(vp=vp)
