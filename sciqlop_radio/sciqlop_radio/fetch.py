"""Async Fido search/fetch with Qt signals.

All network calls run on QThreadPool workers. Signals are emitted via
queued connections so they always land on the GUI thread. No asyncio /
qasync — keeps us out of the cancel-scope bug class.

CRITICAL: `import radiospectra.net` BEFORE any Fido.search call — that
side-effect registers RFSClient / eCALLISTOClient / EOVSAClient /
ILOFARClient / RSTNClient with sunpy's client registry. Without it Fido
falls back to default clients (e.g. VSOClient for swaves, returning
TDS-max .txt summaries instead of spectrograms). The import lives in
`_build_attrs` and `_eval_raw_attrs`, both of which run before
`_run_fido_search`, so the invariant is maintained.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


def _format_time_for_fido(t: datetime) -> str:
    """Render a datetime in a format `astropy.time.Time` accepts.

    Astropy's `isot` format does not tolerate a timezone suffix like
    `+00:00`, so naive `datetime.isoformat()` on a UTC-aware datetime
    fails with `Time ... does not match isot format`. Convert to UTC,
    drop tzinfo, then format.
    """
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc).replace(tzinfo=None)
    return t.isoformat(sep="T", timespec="seconds")


def _row_field(row, name: str) -> str:
    """Defensive column access for a Fido QueryResponseRow. Returns '' for a
    missing column. Falls back to attribute access so plain test stubs work.

    The column lookup is only trusted when it returns a plain str or None;
    for anything else (e.g. a MagicMock from tests that don't restrict
    __getitem__) we fall back to getattr so the attribute path wins.
    """
    try:
        val = row[name]
        if not isinstance(val, (str, type(None))):
            val = getattr(row, name, None)
    except (KeyError, TypeError, IndexError):
        val = getattr(row, name, None)
    return "" if val is None else str(val)


def _row_url(row) -> str:
    return _row_field(row, "url")


def _build_attrs(query) -> list:
    """Structured attrs from a RadioQuery. Imports radiospectra.net for the
    side-effect that registers the Fido clients (see module docstring)."""
    import radiospectra.net  # noqa: F401 — registers RFS/eCALLISTO/ILOFAR/RSTN clients
    from sunpy.net import attrs as a  # type: ignore

    attrs = [a.Time(_format_time_for_fido(query.t_start),
                    _format_time_for_fido(query.t_end))]
    if query.instrument:
        attrs.append(a.Instrument(query.instrument))
    if query.wavelength_min_mhz is not None and query.wavelength_max_mhz is not None:
        import astropy.units as u
        attrs.append(a.Wavelength(query.wavelength_min_mhz * u.MHz,
                                  query.wavelength_max_mhz * u.MHz))
    return attrs


def _eval_raw_attrs(text: str) -> list:
    """Evaluate a raw Fido query string in a restricted namespace.

    Only the sunpy attrs module and common attr names are exposed; builtins
    are removed. This is the user's own desktop tool (they can run arbitrary
    Python via SciQLop's console), so the namespace guards footguns, not a
    determined adversary.
    """
    import radiospectra.net  # noqa: F401
    from sunpy.net import attrs as a  # type: ignore
    import astropy.units as u

    ns = {
        "__builtins__": {},
        "a": a, "u": u,
        **{k: getattr(a, k) for k in ("Time", "Instrument", "Wavelength") if hasattr(a, k)},
    }
    try:
        result = eval(text, ns)  # noqa: S307 — restricted namespace; see docstring
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Invalid raw Fido query: {type(e).__name__}: {e}") from e
    return list(result) if isinstance(result, (list, tuple)) else [result]


def _run_fido_search(attrs: list) -> list[Any]:
    """Run Fido.search with a pre-built attrs list; return flat rows. Raises
    if Fido attached errors and returned no rows (otherwise they'd surface as
    a silent zero-rows result)."""
    from sunpy.net import Fido  # type: ignore

    response = Fido.search(*attrs)
    rows: list[Any] = []
    for table in response:
        for row in table:
            rows.append(row)

    errors = list(getattr(response, "errors", []) or [])
    if errors and not rows:
        details = "; ".join(f"{type(e).__name__}: {e}" for e in errors)
        raise RuntimeError(f"Fido client errors (no rows returned): {details}")
    return rows


def _do_search(query) -> list[Any]:
    """Build attrs from a RadioQuery (structured or raw) and run the search."""
    attrs = _eval_raw_attrs(query.raw_attrs_text) if query.raw_attrs_text else _build_attrs(query)
    return _run_fido_search(attrs)


def _do_fetch(rows: Iterable[Any], cache_dir: Path) -> list[Path]:
    """Run Fido.fetch synchronously; return list of local paths in row order.

    Fido.fetch refuses a plain Python list (it wants QueryResponseRow /
    QueryResponseTable / UnifiedResponse), so we drive it one row at a
    time. This is what gives us per-file failure isolation too.
    """
    from sunpy.net import Fido  # type: ignore

    cache_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for row in rows:
        result = Fido.fetch(row, path=str(cache_dir / "{file}"))
        paths.extend(Path(p) for p in result)
    return paths


def _cache_path_for(row: Any, cache_dir: Path) -> Path:
    """Best-effort: derive expected cached filename from a row's url column."""
    url = _row_url(row)
    name = url.rsplit("/", 1)[-1] if url else ""
    return cache_dir / name if name else cache_dir / "__unknown__"


class _SearchTask(QRunnable):
    def __init__(self, svc: "RadioFetchService", query, cache_key=None):
        super().__init__()
        self._svc = svc
        self._query = query
        self._cache_key = cache_key

    def run(self):
        svc = self._svc
        try:
            rows = _do_search(self._query)
            if self._cache_key is not None:
                svc._search_cache_store(self._cache_key, rows)
            svc.searchCompleted.emit(rows)
        except Exception as e:  # noqa: BLE001
            svc.searchFailed.emit(f"{type(e).__name__}: {e}")
        finally:
            svc._mark_finished()


class _FetchTask(QRunnable):
    def __init__(self, svc: "RadioFetchService", rows: list[Any]):
        super().__init__()
        self._svc = svc
        self._rows = rows

    def run(self):
        svc = self._svc
        ok: list[Path] = []
        failed: list[tuple[Any, str]] = []
        to_fetch: list[Any] = []
        for row in self._rows:
            cached = _cache_path_for(row, svc._cache_dir)
            if cached.exists():
                ok.append(cached)
            else:
                to_fetch.append(row)

        if to_fetch:
            paths: list = []
            try:
                paths = _do_fetch(to_fetch, svc._cache_dir)
                ok.extend(paths)
            except Exception as e:
                for row in to_fetch:
                    failed.append((row, f"{type(e).__name__}: {e}"))
            else:
                # Account for per-file failures that Fido swallows: if fewer files came
                # back than were requested, mark the deficit as failed (we lack a
                # row→path mapping from Fido, so report a count discrepancy).
                if len(paths) < len(to_fetch):
                    deficit = len(to_fetch) - len(paths)
                    failed.append((None, f"{deficit} of {len(to_fetch)} files failed during Fido.fetch (no per-row diagnostic)"))

        svc.fetchProgress.emit(len(ok), len(self._rows))
        svc.fetchCompleted.emit(ok, failed)
        svc._mark_finished()


class RadioFetchService(QObject):
    """Async wrapper around sunpy.net.Fido with Qt signals.

    The settings page exposes a `download_timeout_s` field, but the current
    implementation does not pass it to Fido (Fido.fetch has no timeout
    parameter). Plumb it through a custom parfive.Downloader when needed.

    In-memory search cache: repeat `search(query)` calls within
    `search_cache_ttl_s` skip Fido.search and re-emit the previous rows.
    Lives in-process only (FidoRow objects aren't picklable, so a disk
    cache isn't practical for the search path — for the spectrogram side
    Speasy's `@CacheCall` does survive restarts).
    """

    searchCompleted = Signal(list)            # list[FidoRow]
    searchFailed = Signal(str)
    fetchProgress = Signal(int, int)          # done, total
    fetchCompleted = Signal(list, list)       # list[Path], list[(row, msg)]
    fetchFailed = Signal(str)

    def __init__(
        self, cache_dir: Path, timeout_s: int = 60,
        search_cache_ttl_s: int = 600,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._cache_dir = Path(cache_dir)
        self._timeout_s = int(timeout_s)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._pool = QThreadPool.globalInstance()
        self._inflight = threading.Event()
        self._inflight.set()  # initially idle (set = no work)
        self._search_cache_ttl_s = int(search_cache_ttl_s)
        self._search_cache: dict[tuple, tuple[float, list]] = {}

    @staticmethod
    def _search_cache_key(query) -> tuple:
        return (
            query.instrument,
            query.raw_attrs_text,
            query.wavelength_min_mhz,
            query.wavelength_max_mhz,
            _format_time_for_fido(query.t_start),
            _format_time_for_fido(query.t_end),
        )

    def _search_cache_hit(self, key: tuple) -> list | None:
        entry = self._search_cache.get(key)
        if entry is None:
            return None
        ts, rows = entry
        import time as _time
        if _time.monotonic() - ts > self._search_cache_ttl_s:
            self._search_cache.pop(key, None)
            return None
        return rows

    def _search_cache_store(self, key: tuple, rows: list) -> None:
        import time as _time
        self._search_cache[key] = (_time.monotonic(), rows)

    def search(self, query) -> None:
        key = self._search_cache_key(query)
        cached = self._search_cache_hit(key)
        if cached is not None:
            # Re-emit on the next event-loop tick so listeners see the same
            # ordering as a real async search.
            self._inflight.clear()
            from PySide6.QtCore import QTimer
            def _emit():
                self.searchCompleted.emit(list(cached))
                self._mark_finished()
            QTimer.singleShot(0, _emit)
            return
        self._inflight.clear()
        self._pool.start(_SearchTask(self, query, cache_key=key))

    def fetch(self, rows: list[Any]) -> None:
        self._inflight.clear()
        self._pool.start(_FetchTask(self, list(rows)))

    def _mark_finished(self):
        self._inflight.set()

    def wait_for_finished(self, timeout_s: float = 30.0) -> bool:
        """Block until the currently-queued task finishes. For tests."""
        return self._inflight.wait(timeout=timeout_s)
