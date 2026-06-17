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

Per-channel streams (one station + focus code, e.g. e-CALLISTO/RSTN) are built
on demand by the dock via `make_stream_source`, which keys each stream by
station + channel and filters the search results accordingly. The CONTINUOUS_SOURCES
registry below holds only the whole-instrument single-grid sources (EOVSA, ILOFAR)
registered at load time.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional

import numpy as np

from .fetch import _row_field
from .plot import frequency_signature

log = logging.getLogger(__name__)


def _filter_rows_for_stream(rows: list, source: "ContinuousSource") -> list:
    """Client-side station + channel filter. Server-side station filtering
    (radiospectra.net.Observatory) narrows eCALLISTO already; this guarantees
    correctness for every instrument and never folds two channels together."""
    if source.station:
        rows = [r for r in rows if _row_field(r, "Observatory") == source.station]
    if source.channel_column and source.channel_value:
        rows = [r for r in rows
                if _row_field(r, source.channel_column) == source.channel_value]
    return rows


def _frequency_signature_safe(variable):
    try:
        return frequency_signature(variable)
    except Exception:  # noqa: BLE001 — unkeyable variable never matches
        return None


@dataclass(frozen=True)
class ContinuousSource:
    """One entry in the continuous-source registry.

    `attrs_factory` returns the `sunpy.net.attrs` list (excluding `a.Time`,
    which we add per call) — lazy because sunpy/radiospectra imports are
    slow and should only fire when SciQLop actually drags a product onto
    a panel.

    `static_meta` is the ISTP-ish metadata dict surfaced on the product-
    tree node and used by RichEasySpectrogram.plot_hints (pre-fetch).
    Frequency-axis and color-axis units typically come from the parsed
    SpeasyVariable via plot_hints_from_variable (post-fetch), so this is
    intentionally minimal: just DISPLAY_TYPE, SCALETYP, description, and
    a provider tag for tooltips.
    """

    vp_path: str
    label: str
    attrs_factory: Callable[[], list]
    static_meta: dict = field(default_factory=dict)
    # Per-channel stream filters (empty/None = whole-source, e.g. EOVSA/ILOFAR):
    station: str = ""                       # client-side Observatory-column filter
    channel_column: str | None = None       # Fido column for the channel token
    channel_value: str = ""                 # required value in channel_column
    freq_signature: tuple | None = None     # post-parse frequency-grid filter
    # Deterministic key for the per-day search cache. Must encode exactly what
    # the search actually scopes on (instrument + server-side Observatory), so
    # identical searches share an entry and different ones never collide. Falls
    # back to vp_path when unset.
    search_signature: str = ""


def _format_time_for_fido(t: datetime) -> str:
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc).replace(tzinfo=None)
    return t.isoformat(sep="T", timespec="seconds")


def _attrs_eovsa() -> list:
    from sunpy.net import attrs as a
    return [a.Instrument("EOVSA")]


def _attrs_ilofar() -> list:
    from sunpy.net import attrs as a
    return [a.Instrument("ILOFAR")]


# PSP/FIELDS RFS L3 (LFR + HFR) is served via the curated catalog
# (radio/PSP/FIELDS/RFS_*/...) sourced from CDAWeb — calibrated PSD flux
# with a real frequency axis, strictly better than the raw radiospectra
# files we'd fetch here. Don't add a continuous PSP RFS VP back without
# also dropping the catalog entry.

_EOVSA_META = {
    "DISPLAY_TYPE": "spectrogram",
    "SCALETYP": "log",
    "description": "EOVSA solar microwave dynamic spectrum (1-18 GHz)",
    "provider": "radiospectra",
}

_ILOFAR_META = {
    "DISPLAY_TYPE": "spectrogram",
    "SCALETYP": "log",
    "description": "ILOFAR mode 357 BST dynamic spectrum (10-240 MHz)",
    "provider": "radiospectra",
}

CONTINUOUS_SOURCES: list[ContinuousSource] = [
    ContinuousSource(
        vp_path="radio/eovsa",
        label="EOVSA",
        attrs_factory=_attrs_eovsa,
        static_meta=_EOVSA_META,
        search_signature="EOVSA",
    ),
    ContinuousSource(
        vp_path="radio/ilofar",
        label="ILOFAR (mode 357 BST)",
        attrs_factory=_attrs_ilofar,
        static_meta=_ILOFAR_META,
        search_signature="ILOFAR",
    ),
]


def _cache_path_for_row(row: Any, cache_dir: Path) -> Path:
    """Mirrors fetch.py's `_cache_path_for` so the on-demand callback and the
    dock's imperative fetch share the same on-disk cache. Accepts both live Fido
    rows and cached row-dicts (url is read column-first via `_row_field`)."""
    url = _row_field(row, "url")
    name = url.rsplit("/", 1)[-1] if url else ""
    return cache_dir / name if name else cache_dir / "__unknown__"


# ---------------------------------------------------------------------------
# Day-bucketed deterministic search cache
# ---------------------------------------------------------------------------

_SEARCH_CACHE_TTL_S = 6 * 3600  # short enough that on-disk eviction self-heals fast


def _utc_days(t0: datetime, t1: datetime) -> List[datetime]:
    """Whole-UTC-day bucket starts covering [t0, t1]. Deterministic in the
    calendar days spanned (not the intra-day offset), so panning within a day
    reuses the same cache entries."""
    day = t0.replace(hour=0, minute=0, second=0, microsecond=0)
    out: list[datetime] = []
    while day < t1:
        out.append(day)
        day += timedelta(days=1)
    return out or [day]  # degenerate t0 == t1 → the containing day


def _search_signature(source: "ContinuousSource") -> str:
    return source.search_signature or source.vp_path


def _search_cache_key(source: "ContinuousSource", day: datetime) -> str:
    return f"sciqlop_radio/search/{_search_signature(source)}/{day.date().isoformat()}"


def _parse_start_epoch(value: str) -> Optional[float]:
    """Best-effort parse of a Fido 'Start Time' value to epoch seconds; None if
    unparseable (such rows are never trimmed — we keep them to be safe)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).strip().replace(" ", "T"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _row_to_dict(row: Any, source: "ContinuousSource") -> dict:
    """Picklable projection of a Fido row carrying exactly what the callback
    needs downstream: url (download + disk path), the station/channel columns
    (client-side filtering) and Start Time (window trimming)."""
    out = {
        "url": _row_field(row, "url"),
        "Observatory": _row_field(row, "Observatory"),
        "Start Time": _row_field(row, "Start Time"),
    }
    if source.channel_column:
        out[source.channel_column] = _row_field(row, source.channel_column)
    return out


def _dedup_by_url(rows: list) -> list:
    seen: set = set()
    out: list = []
    for row in rows:
        url = _row_field(row, "url")
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        out.append(row)
    return out


def _all_files_on_disk(rows: list, cache_dir: Path) -> bool:
    return all(_cache_path_for_row(r, cache_dir).exists() for r in rows)


def _fido_search_day_cached(day: datetime, source: "ContinuousSource", cache_dir: Path) -> list:
    """Return the rows for one whole UTC day, hitting the disk-backed day cache.

    Cache HIT (and every cached file still on disk) → return the picklable
    row-dicts. Otherwise run the live search (`_fido_search`, which tests patch),
    refresh the cache, and return the real Fido rows so missing files can be
    downloaded."""
    from speasy.core.cache import add_item, get_item

    key = _search_cache_key(source, day)
    cached = get_item(key)
    if cached is not None and _all_files_on_disk(cached, cache_dir):
        return cached
    rows = _fido_search(day, day + timedelta(days=1), source)
    add_item(key, [_row_to_dict(r, source) for r in rows], _SEARCH_CACHE_TTL_S)
    return rows


def _rows_overlapping(rows: list, t0: datetime, t1: datetime) -> list:
    """Trim a full-day row list to files overlapping [t0, t1]. A file's coverage
    is approximated as [start, next_file_start); the last file extends to t1.
    Rows without a parseable Start Time are always kept."""
    epoch0, epoch1 = t0.timestamp(), t1.timestamp()
    timed: list[tuple[float, Any]] = []
    keep: list = []
    for row in rows:
        start = _parse_start_epoch(_row_field(row, "Start Time"))
        if start is None:
            keep.append(row)
        else:
            timed.append((start, row))
    timed.sort(key=lambda x: x[0])
    for i, (start, row) in enumerate(timed):
        end = timed[i + 1][0] if i + 1 < len(timed) else epoch1
        if start < epoch1 and end > epoch0:
            keep.append(row)
    return keep


def _search_rows_for_window(t0: datetime, t1: datetime, source: "ContinuousSource",
                            cache_dir: Path) -> list:
    """Day-bucketed, cache-backed replacement for a single windowed Fido.search.
    Searches each spanned UTC day (cached), dedups, and trims to the window."""
    rows: list = []
    for day in _utc_days(t0, t1):
        rows.extend(_fido_search_day_cached(day, source, cache_dir))
    return _rows_overlapping(_dedup_by_url(rows), t0, t1)


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

    def _callback(start: float, stop: float):
        t0 = datetime.fromtimestamp(start, tz=timezone.utc)
        t1 = datetime.fromtimestamp(stop, tz=timezone.utc)
        t_search = time.monotonic()
        log.warning(  # WARNING so it shows up in SciQLop's log widget by default
            "continuous(%s): callback fired for [%s .. %s]",
            source.vp_path, t0.isoformat(), t1.isoformat(),
        )
        try:
            rows = _search_rows_for_window(t0, t1, source, cache_dir)
        except Exception as exc:  # noqa: BLE001
            log.exception("continuous(%s): Fido.search failed: %s", source.vp_path, exc)
            return None
        log.warning(
            "continuous(%s): Fido.search returned %d row(s) in %.1fs",
            source.vp_path, len(rows), time.monotonic() - t_search,
        )
        rows = _filter_rows_for_stream(rows, source)
        if not rows:
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

        if source.freq_signature is not None:
            variables = [v for v in variables
                         if _frequency_signature_safe(v) == source.freq_signature]

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


def make_stream_source(identity, freq_signature) -> ContinuousSource:
    """Build a per-channel streaming source from a dock-fetched group's identity
    (`sciqlop_radio.streams.StreamIdentity`) and its reference frequency grid."""
    from .streams import rule_for, stream_fido_attrs

    rule = rule_for(identity.source_key)
    label = " ".join(p for p in (identity.instrument, identity.station,
                                 identity.channel) if p)
    # The search scopes on instrument + (server-side Observatory only). Focus
    # code is a client-side filter, so streams differing only in focus code at
    # one station share a day's cached search.
    server_station = identity.station if rule.server_side else ""
    return ContinuousSource(
        vp_path=identity.vp_path,
        label=label or identity.source_key,
        attrs_factory=lambda: stream_fido_attrs(identity),
        station=identity.station if rule.per_station else "",
        channel_column=rule.channel_column,
        channel_value=identity.channel,
        freq_signature=freq_signature,
        search_signature=f"{identity.instrument}|{server_station}",
    )


@dataclass
class ContinuousRegistration:
    """Live handle on the registered VPs — keeps them alive against GC."""

    vps: dict[str, Any] = field(default_factory=dict)


def register_continuous_products(
    cache_dir: Path,
    open_and_convert: Callable[[Path], Any],
    *,
    vp_factory: Optional[Callable[..., Any]] = None,
) -> Optional[ContinuousRegistration]:
    """Register one VP per `ContinuousSource`. Returns None when SciQLop's
    virtual-products API isn't importable (headless tests).

    `vp_factory` defaults to `sciqlop_radio.hints.make_rich_vp` so the VPs
    carry the same plot-hints overrides as the catalog. Tests can inject
    a fake."""
    try:
        from SciQLop.user_api.virtual_products import VirtualProductType
    except ImportError as exc:
        log.warning("continuous: SciQLop user_api unavailable: %s", exc)
        return None

    if vp_factory is None:
        from .hints import make_rich_vp
        vp_factory = make_rich_vp

    reg = ContinuousRegistration()
    for src in CONTINUOUS_SOURCES:
        cb = _build_callback(src, cache_dir, open_and_convert)
        try:
            vp = vp_factory(src.vp_path, cb, VirtualProductType.Spectrogram,
                             metadata=src.static_meta)
        except Exception as exc:  # noqa: BLE001
            log.exception("continuous: vp_factory failed for %s: %s",
                          src.vp_path, exc)
            continue
        reg.vps[src.vp_path] = vp
    return reg
