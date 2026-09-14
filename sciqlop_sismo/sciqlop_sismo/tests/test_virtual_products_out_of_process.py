"""Regression tests for radio-aligned out-of-process sismo virtual products.

sismo registers live products with bare `create_virtual_product` callbacks
that capture the live SismoProvider (unpicklable in SciQLop's worker
process), while radio live products use `out_of_process=True` with
worker-safe callbacks capturing only plain data. These tests pin the
worker-safe contract; they fail until the worker module + registration
helper exist.
"""

from datetime import datetime, timezone

import numpy as np
import pytest
from obspy import Stream, Trace, UTCDateTime


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def fake_stream():
    tr = Trace(
        data=np.linspace(0, 1, 1000, dtype=np.float64),
        header={
            "network": "G",
            "station": "SSB",
            "location": "00",
            "channel": "HHZ",
            "sampling_rate": 100.0,
            "starttime": UTCDateTime("2026-01-01T00:00:00"),
        },
    )
    return Stream([tr])


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIQLOP_SISMO_INVENTORY_DIR", str(tmp_path))
    from sciqlop_sismo.provider import SismoProvider

    p = SismoProvider()
    p.add_channel(
        network="G",
        station="SSB",
        location="00",
        channel="HHZ",
        start_date=_utc(2020, 1, 1),
        stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0,
        routing="iris-federator",
    )
    return p


def _snapshot(**overrides):
    base = dict(
        nslc=("G", "SSB", "00", "HHZ"),
        routing="iris-federator",
        sampling_rate_hz=100.0,
        path=None,
        bandpass_min_hz=0.01,
        bandpass_max_hz=10.0,
        fetch_timeout_s=120,
    )
    base.update(overrides)
    return base


def test_worker_callback_does_not_capture_provider(provider):
    """The registered live callback must survive pickling to SciQLop's worker
    process: no SismoProvider (or Qt/VP object) in its closure/args."""
    import inspect

    from sciqlop_sismo.provider import SismoProvider
    from sciqlop_sismo.virtual_products import build_live_callback

    cb = build_live_callback(kind="waveform", **_snapshot())
    assert cb.__module__.startswith("sciqlop_sismo"), cb.__module__
    assert cb.__name__ == "sismo_live_callback"
    closure_vars = inspect.getclosurevars(cb)
    assert not any(
        isinstance(v, SismoProvider)
        for v in list(closure_vars.nonlocals.values())
        + list(closure_vars.globals.values())
    )
    for value in closure_vars.nonlocals.get("frozen", {}).values():
        assert not isinstance(value, SismoProvider), "callback captures provider"
    import cloudpickle

    cloudpickle.dumps(cb)


def test_three_kinds_share_one_fetch(fake_stream):
    """Raw/waveform/spectrogram worker callbacks for one channel share a
    single cached raw fetch — no refetch per kind."""
    from unittest.mock import patch

    from sciqlop_sismo.virtual_products import build_live_callback

    t0 = _utc(2026, 1, 1).timestamp()
    t1 = _utc(2026, 1, 1, 0, 1).timestamp()
    with patch("sciqlop_sismo.worker.fetch_stream", return_value=fake_stream) as fs:
        for kind in ("raw", "waveform", "spectrogram"):
            var = build_live_callback(kind=kind, **_snapshot())(t0, t1)
            assert var is not None, kind
    assert fs.call_count == 1, f"three kinds must share one fetch, got {fs.call_count}"


def test_worker_routing_change_refetches(fake_stream):
    """Same routing shares the worker fetch; a changed routing refetches and
    never serves the old route's cached fragments."""
    from unittest.mock import patch

    from sciqlop_sismo.virtual_products import build_live_callback

    t0 = _utc(2026, 1, 1).timestamp()
    t1 = _utc(2026, 1, 1, 0, 1).timestamp()
    with patch("sciqlop_sismo.worker.fetch_stream", return_value=fake_stream) as fs:
        assert build_live_callback(kind="raw", **_snapshot())(t0, t1) is not None
        assert build_live_callback(kind="waveform", **_snapshot())(t0, t1) is not None
    assert fs.call_count == 1, f"same routing must share one fetch, got {fs.call_count}"
    with patch("sciqlop_sismo.worker.fetch_stream", return_value=fake_stream) as fs2:
        assert (
            build_live_callback(kind="raw", **_snapshot(routing="eida-routing"))(t0, t1)
            is not None
        )
    assert fs2.call_count == 1, "changed routing must refetch, not reuse old fragments"


def test_remove_channel_drops_live_vp_refs(tmp_path, monkeypatch):
    """Stale inventory: removing a channel drops its live VP refs so SciQLop
    can reap the nodes; re-adding re-registers all three kinds."""
    from sciqlop_sismo.provider import SismoProvider
    from sciqlop_sismo.virtual_products import KIND_PATHS

    monkeypatch.setenv("SCIQLOP_SISMO_INVENTORY_DIR", str(tmp_path))
    local_provider = SismoProvider(vp_factory=lambda *a, **k: object())
    kw = dict(
        network="G",
        station="SSB",
        location="00",
        channel="HHZ",
        start_date=_utc(2020, 1, 1),
        stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0,
        routing="iris-federator",
    )
    local_provider.add_channel(**kw)
    prefix = "sismo/G/SSB/00.HHZ/"
    assert {p for p in local_provider._virtual_products if p.startswith(prefix)} == {
        prefix + k for k in KIND_PATHS
    }
    local_provider.remove_channel("G", "SSB", "00", "HHZ")
    assert not [p for p in local_provider._virtual_products if p.startswith(prefix)]
    local_provider.add_channel(**kw)
    assert {p for p in local_provider._virtual_products if p.startswith(prefix)} == {
        prefix + k for k in KIND_PATHS
    }


def test_remove_then_readd_with_new_routing_replaces_without_colliding(
    tmp_path, monkeypatch
):
    """Remove-then-readd safety at the provider bookkeeping level: removal
    clears wrappers and snapshots, so re-adding (even with a new routing)
    re-registers exactly three products with no key collision."""
    from sciqlop_sismo.provider import SismoProvider
    from sciqlop_sismo.virtual_products import KIND_PATHS

    monkeypatch.setenv("SCIQLOP_SISMO_INVENTORY_DIR", str(tmp_path))
    calls = []

    def counting_factory(path, *a, **k):
        calls.append(path)
        return object()

    local_provider = SismoProvider(vp_factory=counting_factory)
    kw = dict(
        network="G",
        station="SSB",
        location="00",
        channel="HHZ",
        start_date=_utc(2020, 1, 1),
        stop_date=_utc(2030, 1, 1),
        sampling_rate_hz=100.0,
        routing="iris-federator",
    )
    prefix = "sismo/G/SSB/00.HHZ/"
    local_provider.add_channel(**kw)
    assert len(calls) == 3
    local_provider.remove_channel("G", "SSB", "00", "HHZ")
    assert not [p for p in local_provider._virtual_products if p.startswith(prefix)]
    assert not [p for p in local_provider._vp_snapshots if p.startswith(prefix)]
    local_provider.add_channel(**{**kw, "routing": "eida-routing"})
    assert {p for p in local_provider._virtual_products if p.startswith(prefix)} == {
        prefix + k for k in KIND_PATHS
    }
    assert len(calls) == 6
    assert (
        len({p for p in local_provider._virtual_products if p.startswith(prefix)}) == 3
    )


def test_worker_local_missing_file_returns_none(tmp_path):
    """A missing local file must yield None, never raise into the data path."""
    from sciqlop_sismo.virtual_products import build_live_callback

    snap = _snapshot(routing="local:deadbeef", path=str(tmp_path / "gone.mseed"))
    t0 = _utc(2026, 1, 1).timestamp()
    t1 = _utc(2026, 1, 1, 0, 1).timestamp()
    assert build_live_callback(kind="waveform", **snap)(t0, t1) is None


def test_worker_freezes_timeout_and_bandpass_at_registration(provider, fake_stream):
    """Timeout/bandpass are frozen as plain values in the worker snapshot:
    later settings edits must not change live-callback behavior."""
    from unittest.mock import patch

    from sciqlop_sismo.virtual_products import build_live_callback

    snap = _snapshot(fetch_timeout_s=7, bandpass_min_hz=0.5, bandpass_max_hz=5.0)
    cb = build_live_callback(kind="waveform", **snap)
    provider._settings.fetch_timeout_s = 999
    provider._settings.bandpass_min_hz = 0.001
    t0 = _utc(2026, 1, 1).timestamp()
    t1 = _utc(2026, 1, 1, 0, 1).timestamp()
    with patch("sciqlop_sismo.worker.fetch_stream", return_value=fake_stream) as fs:
        with patch(
            "sciqlop_sismo.worker.bandpass", side_effect=lambda s, fmin, fmax, **k: s
        ) as bp:
            assert cb(t0, t1) is not None
    assert fs.call_args[1]["timeout"] == 7
    assert bp.call_args[1]["fmin"] == 0.5
    assert bp.call_args[1]["fmax"] == 5.0


def test_live_registration_supplies_metadata_labels_and_out_of_process(provider):
    """Radio-like registration: per-kind metadata/labels/display names plus
    out_of_process=True for every live product."""
    calls = []

    def fake_factory(
        path,
        callback,
        vp_type,
        *,
        metadata=None,
        labels=None,
        out_of_process=False,
        display_name=None,
    ):
        calls.append(
            dict(
                path=path,
                callback=callback,
                vp_type=vp_type,
                metadata=metadata,
                labels=labels,
                out_of_process=out_of_process,
                display_name=display_name,
            )
        )
        return object()

    from sciqlop_sismo.virtual_products import register_channel_virtual_products

    record = dict(
        network="G",
        station="SSB",
        location="00",
        channel="HHZ",
        routing="iris-federator",
        sampling_rate_hz=100.0,
        path=None,
        bandpass_min_hz=0.01,
        bandpass_max_hz=10.0,
        fetch_timeout_s=120,
    )
    out = register_channel_virtual_products(record, vp_factory=fake_factory)
    assert len(out) == 3
    by_kind = {c["path"].rsplit("/", 1)[-1]: c for c in calls}
    assert set(by_kind) == {"waveform", "raw", "spectrogram"}
    for kind, c in by_kind.items():
        assert c["out_of_process"] is True, kind
        assert c["display_name"], kind
        assert c["metadata"].get("DISPLAY_TYPE"), kind
        assert c["metadata"].get("provider") == "sismo", kind
    assert by_kind["waveform"]["labels"] == ["HHZ"]
    assert by_kind["raw"]["labels"] == ["HHZ"]
    assert by_kind["spectrogram"]["labels"] is None


def test_live_registration_rejects_unknown_kind():
    from sciqlop_sismo.virtual_products import register_channel_virtual_products

    with pytest.raises(ValueError, match="unknown kind"):
        register_channel_virtual_products(
            dict(
                network="G",
                station="SSB",
                location="00",
                channel="HHZ",
                routing="iris-federator",
                sampling_rate_hz=100.0,
            ),
            kinds=("waveform", "bogus"),
            vp_factory=lambda *a, **k: object(),
        )
