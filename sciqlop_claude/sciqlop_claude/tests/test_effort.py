"""Effort selection: SDK-accepted levels, narrowed per model, applied on reconnect."""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from SciQLop.components.agents import backend as _agents_backend

pytestmark = pytest.mark.skipif(
    isinstance(_agents_backend, MagicMock),
    reason="SciQLop is stubbed in this environment",
)


def _backend(model=None):
    from sciqlop_claude import backend as mod

    be = object.__new__(mod.ClaudeBackend)
    be._model = model
    be._effort = None
    be._client = None
    be._resume = None
    be._lock = asyncio.Lock()
    be._slash_cache = None
    return be


def test_effort_values_default_to_the_full_sdk_set():
    from sciqlop_claude.backend import SDK_EFFORT_LEVELS

    assert _backend().effort_values() == SDK_EFFORT_LEVELS
    assert "xhigh" in SDK_EFFORT_LEVELS


def test_effort_values_are_narrowed_by_the_models_registry(monkeypatch):
    from sciqlop_claude import backend as mod

    monkeypatch.setattr(
        mod, "capabilities_for",
        lambda provider, model, **kw: SimpleNamespace(
            effort_values=("low", "medium", "high", "max")))
    # "xhigh" is in the SDK set but not this model's set — intersection wins,
    # and SDK order is preserved.
    assert _backend("claude-sonnet-4-6").effort_values() == (
        "low", "medium", "high", "max")


def test_unknown_model_keeps_the_sdk_set(monkeypatch):
    from sciqlop_claude import backend as mod
    from sciqlop_claude.backend import SDK_EFFORT_LEVELS

    monkeypatch.setattr(mod, "capabilities_for", lambda *a, **k: None)
    assert _backend("mystery").effort_values() == SDK_EFFORT_LEVELS


def test_set_effort_keeps_a_live_client_and_defers_the_reconnect():
    """Effort is only read when ClaudeAgentOptions is built, so a client that
    is already up cannot honour a new value regardless. Dropping it here killed
    the connection the session-info strip reads context from, on every bind
    that restored a persisted effort — the strip went permanently blank."""
    be = _backend()
    disconnected = []

    async def fake_disconnect():
        disconnected.append(True)
        be._client = None

    be._client = SimpleNamespace()
    be._disconnect = fake_disconnect
    asyncio.run(be.set_effort("high"))

    assert be._effort == "high"
    assert disconnected == []                 # the live client survives
    assert be._effort_dirty is True           # ...but the next turn reconnects


def test_a_pending_effort_change_reconnects_on_the_next_turn():
    from sciqlop_claude import backend as mod

    be = _backend()
    disconnected = []

    async def fake_disconnect():
        disconnected.append(True)
        be._client = None

    async def fake_ensure():
        be._client = SimpleNamespace(
            query=lambda *a, **k: _done(), receive_messages=_empty_stream)
        return be._client

    be._client = SimpleNamespace()
    be._disconnect = fake_disconnect
    be._ensure_client = fake_ensure
    asyncio.run(be.set_effort("high"))
    assert disconnected == []

    async def _drive():
        async for _ in be.ask("hi"):
            pass

    asyncio.run(_drive())
    assert disconnected == [True]              # dropped exactly once, at the turn
    assert be._effort_dirty is False


async def _done():
    return None


async def _empty_stream():
    return
    yield  # pragma: no cover — makes this an async generator


def test_set_effort_without_a_client_does_not_disconnect():
    be = _backend()
    called = []
    be._disconnect = lambda: called.append(True)
    asyncio.run(be.set_effort("low"))
    assert be._effort == "low"
    assert called == []


def test_set_effort_with_the_same_value_does_not_disconnect():
    be = _backend()
    be._effort = "high"
    disconnected = []

    async def fake_disconnect():
        disconnected.append(True)
        be._client = None

    be._client = SimpleNamespace()
    be._disconnect = fake_disconnect

    asyncio.run(be.set_effort("high"))
    assert be._effort == "high"
    assert be._client is not None
    assert disconnected == []

    asyncio.run(be.set_effort("max"))
    assert be._effort == "max"
    assert disconnected == []                  # still no teardown of a live client
    assert be._effort_dirty is True            # the change lands on the next turn


def test_result_message_session_id_is_recorded_for_resume():
    from sciqlop_claude.backend import remember_session

    be = _backend()
    remember_session(be, SimpleNamespace(session_id="sess-42"))
    assert be._resume == "sess-42"


def test_remember_session_ignores_a_blank_session_id():
    from sciqlop_claude.backend import remember_session

    be = _backend()
    be._resume = "existing"
    remember_session(be, SimpleNamespace(session_id=""))
    assert be._resume == "existing"
