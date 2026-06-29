"""The Claude client must raise the SDK's stdio buffer above the 1 MB default.

A sciqlop_screenshot_* tool result is an inline base64 PNG the CLI echoes back
over the stdio transport; at the default 1 MB cap it overflows and aborts the
session. _ensure_client must pass a larger max_buffer_size.
"""
import asyncio

import pytest


def test_ensure_client_raises_max_buffer_size(monkeypatch):
    pytest.importorskip("claude_agent_sdk")
    from sciqlop_claude import backend as bk

    captured = {}

    class _FakeClient:
        def __init__(self, options):
            captured["options"] = options

        async def connect(self):
            return None

    monkeypatch.setattr(bk, "ClaudeSDKClient", _FakeClient)

    inst = bk.ClaudeBackend.__new__(bk.ClaudeBackend)
    inst._client = None
    inst._tools = []
    inst._model = None
    inst._resume = None
    inst._confirm_cb = None
    inst._ask_question_cb = None

    asyncio.run(inst._ensure_client())

    opts = captured["options"]
    assert opts.max_buffer_size == bk._MAX_BUFFER_SIZE
    # Must exceed the SDK default (1 MB) that overflowed on screenshots.
    assert opts.max_buffer_size > 1024 * 1024
