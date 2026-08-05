"""A background Task must not desync the chat by one turn.

The Claude Agent SDK exposes a single shared, ordered message stream and
``receive_response()`` returns at the first ``ResultMessage``. When the model
spawns a background ``Task``, its continuation (the model's reaction to the
completed task, plus that task's own ``ResultMessage``) is emitted *after* the
foreground ``ResultMessage`` — with nobody reading the stream. The next
``ask()`` then drains that orphaned continuation instead of the response to the
new prompt, so every turn shows the *previous* turn's answer (a persistent
one-turn lag).

The fix: a turn ends only at a ``ResultMessage`` reached with no background task
still outstanding, so the background continuation is attributed to the turn that
spawned it. https://code.claude.com/docs/en/agent-sdk/python
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


def _result():
    return ResultMessage(subtype="success", duration_ms=0, duration_api_ms=0,
                         is_error=False, num_turns=1, session_id="s")


class _TaskStartedMessage:
    """Minimal stand-in — only the class name and task_id are inspected."""

    def __init__(self, task_id):
        self.task_id = task_id


class _TaskNotificationMessage:
    def __init__(self, task_id, status):
        self.task_id = task_id
        self.status = status


class _InitMessage:
    """SystemMessage(subtype='init') stand-in — the CLI turn boundary marker."""

    subtype = "init"


# The backend keys active-task tracking on ``type(message).__name__``.
_TaskStartedMessage.__name__ = "TaskStartedMessage"
_TaskNotificationMessage.__name__ = "TaskNotificationMessage"
_InitMessage.__name__ = "SystemMessage"


class _SharedStreamClient:
    """Models the SDK's single shared queue: sequential receive_messages()
    calls resume from where the previous turn stopped, so anything left
    unconsumed by one turn bleeds into the next."""

    def __init__(self, messages):
        self._it = iter(messages)

    async def query(self, *_a, **_k):
        pass

    def receive_messages(self):
        async def _gen():
            for m in self._it:
                yield m

        return _gen()

    def receive_response(self):
        """Faithful to the real SDK: drains the shared stream up to and
        including the first ResultMessage, then stops (this is the behaviour
        that causes the desync on the unfixed backend)."""
        async def _gen():
            for m in self._it:
                yield m
                if isinstance(m, ResultMessage):
                    return

        return _gen()

    async def disconnect(self):
        pass


def test_background_task_continuation_stays_in_its_own_turn(tmp_path):
    backend = ClaudeBackend(_ctx(tmp_path))
    backend._client = _SharedStreamClient([
        # Turn 1: foreground finishes while a background task is still running,
        # then the task completes and its continuation streams in.
        _assistant("FOREGROUND ANSWER"),
        _TaskStartedMessage("t1"),
        _result(),                                    # foreground result — t1 still active
        _assistant("BACKGROUND RESULT"),
        _TaskNotificationMessage("t1", "completed"),  # t1 done
        _result(),                                    # turn truly ends here
        # Turn 2: the response to the *next* prompt.
        _assistant("ANSWER TO NEXT PROMPT"),
        _result(),
    ])

    async def turn(prompt):
        out = []
        async for block in backend.ask(prompt):
            out.append(getattr(block, "text", ""))
        return "".join(out)

    async def scenario():
        return await turn("do work"), await turn("next")

    first, second = asyncio.run(scenario())

    assert "FOREGROUND ANSWER" in first
    assert "BACKGROUND RESULT" in first          # attributed to the spawning turn
    assert "ANSWER TO NEXT PROMPT" in second
    assert "BACKGROUND RESULT" not in second     # did not leak forward


class _SlowSharedStreamClient(_SharedStreamClient):
    """Like ``_SharedStreamClient``, but a marked message is preceded by a real
    ``asyncio.sleep`` — standing in for a background task that is simply slow
    to report back, not stuck. Real tool runs commonly idle well past any
    short polling window while still being perfectly healthy."""

    def __init__(self, messages, *, delay_before, delay_s):
        super().__init__(messages)
        self._delay_before = delay_before
        self._delay_s = delay_s

    def receive_messages(self):
        async def _gen():
            for m in self._it:
                if m is self._delay_before:
                    await asyncio.sleep(self._delay_s)
                yield m

        return _gen()


def test_slow_background_task_is_not_abandoned_mid_turn(tmp_path):
    """A background task that stays quiet for a while must NOT cause the turn
    to give up on it.

    An earlier version of this code gave up waiting after an idle timeout.
    That doesn't stop the task: the SDK subprocess keeps running and its
    buffered messages (including a whole extra ResultMessage) still land on the
    shared stream later, unread. Whichever turn happens to be listening next
    then drains that backlog and misattributes it — a worse version of the
    exact one-turn-lag bug this module exists to prevent. There must be no
    idle-based escape hatch: keep waiting for a started task's terminal status
    no matter how long it takes. (A hung task is instead handled by Stop /
    ``cancel()``, which works independently of this wait.)
    """
    backend = ClaudeBackend(_ctx(tmp_path))
    background_result = _assistant("BACKGROUND RESULT")
    backend._client = _SlowSharedStreamClient(
        [
            _assistant("FOREGROUND ANSWER"),
            _TaskStartedMessage("t1"),
            _result(),                                    # foreground result — t1 still active
            background_result,                             # arrives late
            _TaskNotificationMessage("t1", "completed"),  # t1 done
            _result(),                                    # turn truly ends here
            _assistant("ANSWER TO NEXT PROMPT"),
            _result(),
        ],
        delay_before=background_result,
        delay_s=0.05,
    )

    async def turn(prompt):
        out = []
        async for block in backend.ask(prompt):
            out.append(getattr(block, "text", ""))
        return "".join(out)

    async def scenario():
        return await turn("do work"), await turn("next")

    first, second = asyncio.run(scenario())

    assert "BACKGROUND RESULT" in first          # still attributed to the spawning turn
    assert "ANSWER TO NEXT PROMPT" in second
    assert "BACKGROUND RESULT" not in second     # did not leak forward


def _phantom_result():
    """The bookkeeping ResultMessage a fresh client emits when it reconciles a
    stale background task on resume: success, no model call, no answer."""
    return ResultMessage(subtype="success", duration_ms=100, duration_api_ms=0,
                         is_error=False, num_turns=0, session_id="s")


def test_stale_task_phantom_result_does_not_close_the_turn(tmp_path):
    """Stream shape captured from the real CLI (SDK 0.2.128) on resume with a
    stale background task:

        TaskNotification(stopped, unknown task) -> init -> phantom ResultMessage
        -> init -> AssistantMessage(real answer) -> ResultMessage

    The phantom result carries no AssistantMessage and no model work. Ending
    the turn there shows an empty answer and shifts every later turn by one —
    the persistent one-turn lag. A success result with no AssistantMessage
    since the last init must not close the turn (slash commands like /clear,
    /cost, /context were verified to always carry one)."""
    backend = ClaudeBackend(_ctx(tmp_path))
    backend._client = _SharedStreamClient([
        _TaskNotificationMessage("stale1", "stopped"),
        _InitMessage(),
        _phantom_result(),                      # bookkeeping — NOT the answer
        _InitMessage(),
        _assistant("REAL ANSWER"),
        _result(),
        _assistant("ANSWER TO NEXT PROMPT"),
        _result(),
    ])

    async def turn(prompt):
        out = []
        async for block in backend.ask(prompt):
            out.append(getattr(block, "text", ""))
        return "".join(out)

    async def scenario():
        return await turn("first after resume"), await turn("next")

    first, second = asyncio.run(scenario())

    assert "REAL ANSWER" in first               # not the empty phantom answer
    assert "ANSWER TO NEXT PROMPT" in second
    assert "REAL ANSWER" not in second          # no one-turn lag


def test_content_free_slash_command_still_closes_its_turn(tmp_path):
    """Guard the other side: a legit success turn with num_turns=0 (slash
    command) DOES carry an AssistantMessage and must end normally."""
    backend = ClaudeBackend(_ctx(tmp_path))
    backend._client = _SharedStreamClient([
        _InitMessage(),
        _assistant("(no content)"),             # /clear's confirmation
        _phantom_result(),                      # num_turns=0 success result
        _assistant("ANSWER TO NEXT PROMPT"),
        _result(),
    ])

    async def turn(prompt):
        out = []
        async for block in backend.ask(prompt):
            out.append(getattr(block, "text", ""))
        return "".join(out)

    async def scenario():
        return await turn("/clear"), await turn("next")

    first, second = asyncio.run(scenario())

    assert "(no content)" in first
    assert "ANSWER TO NEXT PROMPT" in second
    assert "(no content)" not in second
