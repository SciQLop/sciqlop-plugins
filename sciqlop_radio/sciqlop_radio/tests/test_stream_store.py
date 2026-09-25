"""Tests for the persisted-stream store.

Without this, a stream registered lazily by the dock (e.g. dragging an
e-CALLISTO search result onto a panel) only exists in memory: after a
SciQLop restart the product-tree node is gone, so a saved panel template
that references it can't be reloaded. `stream_store` remembers every
registered stream on disk so it can be re-registered at plugin load.
"""
from __future__ import annotations

import json
import time

from sciqlop_radio.streams import StreamIdentity


def _ecallisto_identity():
    return StreamIdentity(source_key="ecallisto", instrument="eCALLISTO",
                          path_name="e-CALLISTO", station="BIR", channel="59")


def test_load_missing_file_returns_empty(tmp_path):
    from sciqlop_radio.stream_store import load_saved_streams
    assert load_saved_streams(tmp_path / "streams.json") == []


def test_save_then_load_roundtrips_identity(tmp_path):
    from sciqlop_radio.stream_store import load_saved_streams, save_stream
    store = tmp_path / "streams.json"
    identity = _ecallisto_identity()
    save_stream(store, identity, (4, 1.0, 2.0, 3.0, 4.0))

    [entry] = load_saved_streams(store)
    assert entry.source_key == "ecallisto"
    assert entry.station == "BIR"
    assert entry.channel == "59"
    assert entry.path_name == "e-CALLISTO"
    assert entry.to_identity().vp_path == identity.vp_path
    assert entry.freq_signature == [4, 1.0, 2.0, 3.0, 4.0]


def test_save_upserts_by_vp_path(tmp_path):
    """Re-saving the same stream (e.g. plotted again after a frequency-grid
    change) must update the one entry, not accumulate duplicates."""
    from sciqlop_radio.stream_store import load_saved_streams, save_stream
    store = tmp_path / "streams.json"
    identity = _ecallisto_identity()
    save_stream(store, identity, (3, 1.0, 2.0, 3.0))
    save_stream(store, identity, (5, 1.0, 2.0, 3.0, 4.0, 5.0))

    entries = load_saved_streams(store)
    assert len(entries) == 1
    assert entries[0].freq_signature == [5, 1.0, 2.0, 3.0, 4.0, 5.0]


def test_load_drops_invalid_entries_and_rewrites_the_file(tmp_path):
    """A hand-edited or corrupted entry (missing the required source_key)
    must not crash restoration — it's dropped and the file self-heals."""
    from sciqlop_radio.stream_store import load_saved_streams
    store = tmp_path / "streams.json"
    store.write_text(json.dumps([
        {"instrument": "eCALLISTO", "station": "BIR"},  # missing source_key
        {"source_key": "rstn", "station": "learmonth", "last_used": time.time()},
    ]))

    entries = load_saved_streams(store)
    assert [e.source_key for e in entries] == ["rstn"]
    on_disk = json.loads(store.read_text())
    assert len(on_disk) == 1


def test_load_drops_entries_for_a_source_the_plugin_no_longer_knows(tmp_path):
    """The source was renamed or removed from sources.py — the saved entry
    would never resolve to a real product, so drop it rather than let it
    linger forever."""
    from sciqlop_radio.stream_store import load_saved_streams
    store = tmp_path / "streams.json"
    store.write_text(json.dumps([
        {"source_key": "no_longer_exists", "last_used": time.time()},
        {"source_key": "rstn", "station": "learmonth", "last_used": time.time()},
    ]))

    entries = load_saved_streams(store)
    assert [e.source_key for e in entries] == ["rstn"]


def test_load_drops_entries_unused_for_over_a_year(tmp_path):
    from sciqlop_radio.stream_store import load_saved_streams
    store = tmp_path / "streams.json"
    now = time.time()
    year = 365 * 86400
    store.write_text(json.dumps([
        {"source_key": "rstn", "station": "learmonth", "last_used": now - 2 * year},
        {"source_key": "rstn", "station": "sagamore", "last_used": now - 10},
    ]))

    entries = load_saved_streams(store, now=now)
    assert [e.station for e in entries] == ["sagamore"]


def test_forget_all_removes_the_file(tmp_path):
    from sciqlop_radio.stream_store import forget_all, load_saved_streams, save_stream
    store = tmp_path / "streams.json"
    save_stream(store, _ecallisto_identity(), None)
    assert store.exists()

    forget_all(store)

    assert not store.exists()
    assert load_saved_streams(store) == []


def test_forget_all_is_a_noop_when_nothing_was_saved(tmp_path):
    from sciqlop_radio.stream_store import forget_all
    forget_all(tmp_path / "streams.json")  # must not raise
