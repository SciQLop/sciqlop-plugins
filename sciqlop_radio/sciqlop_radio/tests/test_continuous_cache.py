"""Day-bucketed deterministic caching of the continuous-callback Fido search.

The live `Fido.search` is the only network step in the streaming callback that
wasn't cached (download + parse already are). Caching it on raw `(t0, t1)` would
never hit under panning, so we quantize to whole UTC days — the same principle
as Speasy's fragment cache — and store picklable row-dicts. A cached day is only
trusted while its files are still on disk; otherwise we re-search live (we need
real Fido rows to download).

`_fido_search_day_cached` reads/writes the search cache via the raw
`speasy.core.cache.get_item`/`add_item` primitives, which have no in-flight
request deduplication (unlike Speasy's provider-grade `Cacheable`/
`request_locker`). SciQLop's `QThreadPool`-based fetch dispatch can invoke the
same continuous VP's callback from two worker threads concurrently (e.g. two
plots showing the same source), so a per-key `threading.Lock` guards the
live-search + cache-fill section directly in this module.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import pytest


def _ecallisto_source(**over):
    from sciqlop_radio.continuous import ContinuousSource
    base = dict(vp_path="radio/e-CALLISTO/BIR/01", label="BIR/01",
                attrs_factory=lambda: [], station="BIR",
                channel_column="ID", channel_value="01")
    base.update(over)
    return ContinuousSource(**base)


def test_utc_days_are_whole_day_aligned_and_pan_stable():
    """Bucketing depends only on the calendar days spanned, never on the
    intra-day offset — so panning within a day reuses the same cache entries."""
    from sciqlop_radio.continuous import _utc_days
    t0 = datetime(2024, 5, 1, 6, 30, tzinfo=timezone.utc)
    t1 = datetime(2024, 5, 3, 2, 0, tzinfo=timezone.utc)
    days = _utc_days(t0, t1)
    assert [d.isoformat() for d in days] == [
        "2024-05-01T00:00:00+00:00",
        "2024-05-02T00:00:00+00:00",
        "2024-05-03T00:00:00+00:00",
    ]


def test_second_call_same_window_skips_live_search(monkeypatch, tmp_path):
    from sciqlop_radio import continuous as C
    (tmp_path / "BIR_x_01.fit.gz").write_bytes(b"x")  # present → cache hit is valid
    rows = [{"Observatory": "BIR", "ID": "01", "url": "http://a/BIR_x_01.fit.gz"}]
    calls = {"n": 0}

    def live(t0, t1, src):
        calls["n"] += 1
        return [dict(r) for r in rows]

    monkeypatch.setattr(C, "_fido_search", live)
    monkeypatch.setattr(C, "_fetch_paths", lambda rws, cd: [tmp_path / "BIR_x_01.fit.gz"])
    cb = C._build_callback(_ecallisto_source(), tmp_path, lambda p: None)
    cb(0.0, 100.0)
    cb(0.0, 100.0)
    assert calls["n"] == 1, f"second call must hit the search cache; searched {calls['n']}x"


def test_cache_hit_with_missing_files_refetches(monkeypatch, tmp_path):
    """A cached day whose files are no longer on disk can't be trusted (we'd have
    no real row to download with), so we must re-run the live search."""
    from sciqlop_radio import continuous as C
    rows = [{"Observatory": "BIR", "ID": "01", "url": "http://a/missing_01.fit.gz"}]
    calls = {"n": 0}

    def live(t0, t1, src):
        calls["n"] += 1
        return [dict(r) for r in rows]

    monkeypatch.setattr(C, "_fido_search", live)
    monkeypatch.setattr(C, "_fetch_paths", lambda rws, cd: [])  # nothing on disk
    cb = C._build_callback(_ecallisto_source(), tmp_path, lambda p: None)
    cb(0.0, 100.0)
    cb(0.0, 100.0)
    assert calls["n"] == 2, "missing cached files must force a fresh live search"


def test_concurrent_calls_for_same_window_dedupe_the_live_search(monkeypatch, tmp_path):
    """Two threads racing on the same (source, day) must not both hit the
    network: the second must wait for the first's result instead of
    re-running Fido.search (reproduces the 2026-07-10 diagnostic-dump race:
    two SciQLop worker threads caught mid-`_fido_search` for the same day)."""
    from sciqlop_radio import continuous as C

    (tmp_path / "BIR_race_01.fit.gz").write_bytes(b"x")  # present → cache hit is valid
    rows = [{"Observatory": "BIR", "ID": "01", "url": "http://a/BIR_race_01.fit.gz"}]
    calls = {"n": 0}
    calls_lock = threading.Lock()

    def slow_live(t0, t1, src):
        with calls_lock:
            calls["n"] += 1
        time.sleep(0.1)
        return [dict(r) for r in rows]

    monkeypatch.setattr(C, "_fido_search", slow_live)
    source = _ecallisto_source(vp_path="radio/e-CALLISTO/BIR/race",
                               station="BIR", channel_value="01")
    day = datetime(2024, 5, 1, tzinfo=timezone.utc)

    threads = [threading.Thread(target=C._fido_search_day_cached, args=(day, source, tmp_path))
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert calls["n"] == 1, f"concurrent requests for the same window must dedupe; live search ran {calls['n']}x"


def test_day_search_covers_each_spanned_day_once(monkeypatch, tmp_path):
    """A multi-day window issues exactly one live search per spanned UTC day."""
    from sciqlop_radio import continuous as C
    searched_days = []

    def live(t0, t1, src):
        searched_days.append(t0.date().isoformat())
        return []

    monkeypatch.setattr(C, "_fido_search", live)
    monkeypatch.setattr(C, "_fetch_paths", lambda rws, cd: [])
    t0 = datetime(2024, 5, 1, 12, 0, tzinfo=timezone.utc).timestamp()
    t1 = datetime(2024, 5, 3, 1, 0, tzinfo=timezone.utc).timestamp()
    C._build_callback(_ecallisto_source(), tmp_path, lambda p: None)(t0, t1)
    assert searched_days == ["2024-05-01", "2024-05-02", "2024-05-03"]
