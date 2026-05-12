"""Async Fido search/fetch with Qt signals.

All network calls run on QThreadPool workers. Signals are emitted via
queued connections so they always land on the GUI thread. No asyncio /
qasync — keeps us out of the cancel-scope bug class.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


def _do_search(source, t_start: datetime, t_end: datetime) -> list[Any]:
    """Run Fido.search synchronously; return a flat list of result rows.

    Isolated so tests can patch it without touching sunpy.
    """
    from sunpy.net import Fido, attrs as a  # type: ignore

    if not source.fido_instrument:
        raise RuntimeError(f"source {source.key!r} does not support Fido search")

    response = Fido.search(
        a.Time(t_start.isoformat(), t_end.isoformat()),
        a.Instrument(source.fido_instrument),
    )
    rows: list[Any] = []
    for table in response:
        for row in table:
            rows.append(row)
    return rows


def _do_fetch(rows: Iterable[Any], cache_dir: Path) -> list[Path]:
    """Run Fido.fetch synchronously; return list of local paths in row order."""
    from sunpy.net import Fido  # type: ignore

    cache_dir.mkdir(parents=True, exist_ok=True)
    result = Fido.fetch(list(rows), path=str(cache_dir / "{file}"))
    return [Path(p) for p in result]


def _cache_path_for(row: Any, cache_dir: Path) -> Path:
    """Best-effort: derive expected cached filename from a row's url."""
    url = getattr(row, "url", None) or ""
    name = url.rsplit("/", 1)[-1] if url else ""
    return cache_dir / name if name else cache_dir / "__unknown__"


class _SearchTask(QRunnable):
    def __init__(self, svc: "RadioFetchService", source, t_start, t_end):
        super().__init__()
        self._svc = svc
        self._source = source
        self._t_start = t_start
        self._t_end = t_end

    def run(self):
        svc = self._svc
        try:
            rows = _do_search(self._source, self._t_start, self._t_end)
            svc.searchCompleted.emit(rows)
        except Exception as e:
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
    """

    searchCompleted = Signal(list)            # list[FidoRow]
    searchFailed = Signal(str)
    fetchProgress = Signal(int, int)          # done, total
    fetchCompleted = Signal(list, list)       # list[Path], list[(row, msg)]
    fetchFailed = Signal(str)

    def __init__(self, cache_dir: Path, timeout_s: int = 60, parent: QObject | None = None):
        super().__init__(parent)
        self._cache_dir = Path(cache_dir)
        self._timeout_s = int(timeout_s)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._pool = QThreadPool.globalInstance()
        self._inflight = threading.Event()
        self._inflight.set()  # initially idle (set = no work)

    def search(self, source, t_start: datetime, t_end: datetime) -> None:
        self._inflight.clear()
        self._pool.start(_SearchTask(self, source, t_start, t_end))

    def fetch(self, rows: list[Any]) -> None:
        self._inflight.clear()
        self._pool.start(_FetchTask(self, list(rows)))

    def _mark_finished(self):
        self._inflight.set()

    def wait_for_finished(self, timeout_s: float = 30.0) -> bool:
        """Block until the currently-queued task finishes. For tests."""
        return self._inflight.wait(timeout=timeout_s)
