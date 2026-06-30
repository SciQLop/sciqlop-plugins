"""Claude backend allows the built-in WebSearch/WebFetch tools."""
import asyncio

import pytest


def test_ensure_client_allows_web_tools(monkeypatch):
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
    allowed = captured["options"].allowed_tools
    assert "WebSearch" in allowed
    assert "WebFetch" in allowed
