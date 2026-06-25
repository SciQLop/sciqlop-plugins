"""interrupt() must drain the interrupted task's leftover messages.

Per the Claude Agent SDK docs, ``interrupt()`` does NOT clear the message buffer:
the interrupted task's messages (including its ``ResultMessage`` with
``subtype="error_during_execution"``) remain in the stream and must be drained
with ``receive_response()`` before the next query. Otherwise the next turn reads
the *previous* turn's buffered messages — the chat desyncs (it flips to "done"
on the stale ResultMessage while the real reply only shows up one send later).
https://code.claude.com/docs/en/agent-sdk/python
"""
import asyncio
from types import SimpleNamespace

import pytest

from claude_agent_sdk import AssistantMessage, ResultMessage
from sciqlop_claude.backend import ClaudeBackend, _SDK_AVAILABLE

pytestmark = pytest.mark.skipif(not _SDK_AVAILABLE, reason="claude-agent-sdk not importable")


def _ctx(tmp_path):
    return SimpleNamespace(
        main_window=None, tools=[], tempdir=str(tmp_path),
        confirm_cb=None, allow_writes=False, ask_question_cb=None,
    )


def _assistant(text):
    block = SimpleNamespace(text=text, thinking=None, name=None)
    return AssistantMessage(content=[block], model="test")


def _result(subtype):
    return ResultMessage(subtype=subtype, duration_ms=0, duration_api_ms=0,
                         is_error=subtype != "success", num_turns=1, session_id="s")


class _FakeClient:
    """Mimics the SDK message buffer: each receive_response() drains one turn."""

    def __init__(self, turns):
        self._turns = list(turns)  # list[list[message]]
        self.interrupted = False

    async def interrupt(self):
        self.interrupted = True

    async def query(self, *_a, **_k):
        pass

    def receive_response(self):
        messages = self._turns.pop(0) if self._turns else []

        async def _gen():
            for m in messages:
                yield m

        return _gen()

    async def disconnect(self):
        pass


def test_cancel_drains_interrupted_leftover_so_next_turn_is_clean(tmp_path):
    backend = ClaudeBackend(_ctx(tmp_path))
    # The interrupted turn's messages remain buffered as the first response.
    leftover = [_assistant("STALE interrupted output"), _result("error_during_execution")]
    real = [_assistant("THE REAL NEW ANSWER"), _result("success")]
    backend._client = _FakeClient([leftover, real])

    async def scenario():
        await backend.cancel()  # must drain `leftover`
        out = []
        async for block in backend.ask("new question"):
            out.append(getattr(block, "text", ""))
        return "".join(out)

    text = asyncio.run(scenario())
    assert "THE REAL NEW ANSWER" in text
    assert "STALE" not in text


def test_cancel_does_not_block_on_the_turn_lock(tmp_path):
    """Stop must reach a running turn. ask() holds self._lock for the whole
    streamed turn, so cancel() must fire interrupt() WITHOUT waiting on that lock
    — otherwise the interrupt is deferred until the turn finishes on its own."""
    backend = ClaudeBackend(_ctx(tmp_path))
    backend._client = _FakeClient([])

    async def scenario():
        await backend._lock.acquire()  # simulate an in-flight turn holding the lock
        try:
            await asyncio.wait_for(backend.cancel(), timeout=1.0)
        finally:
            backend._lock.release()
        assert backend._client.interrupted is True

    asyncio.run(scenario())
