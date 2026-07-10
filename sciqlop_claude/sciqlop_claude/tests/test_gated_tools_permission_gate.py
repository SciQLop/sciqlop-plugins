"""Gated tools must not bypass the per-call approval dialog.

`allowed_tools` auto-approves listed tools *before* `can_use_tool` is ever
consulted (this is documented SDK behavior — see CanUseToolShadowedWarning).
Gated tool names must therefore be excluded from `allowed_tools` whenever
`can_use_tool` is wired, otherwise `_permission_check`'s write-action gate
(the "Allow write actions" toggle + confirm dialog) never runs for them.
"""
import asyncio
from types import SimpleNamespace

import pytest

from sciqlop_claude.backend import ClaudeBackend, _SDK_AVAILABLE

pytestmark = pytest.mark.skipif(not _SDK_AVAILABLE, reason="claude-agent-sdk not importable")

async def _noop_handler(_args):
    return {}


_TOOLS = [
    {"name": "sciqlop_exec_python", "gated": True, "description": "",
     "input_schema": {}, "handler": _noop_handler},
    {"name": "sciqlop_list_panels", "gated": False, "description": "",
     "input_schema": {}, "handler": _noop_handler},
]


def _ctx(tmp_path, confirm_cb=None, ask_question_cb=None):
    return SimpleNamespace(
        main_window=None, tools=_TOOLS, tempdir=str(tmp_path),
        confirm_cb=confirm_cb, allow_writes=True, ask_question_cb=ask_question_cb,
    )


def _captured_allowed_tools(monkeypatch, backend):
    from sciqlop_claude import backend as bk

    captured = {}

    class _FakeClient:
        def __init__(self, options):
            captured["options"] = options

        async def connect(self):
            return None

    monkeypatch.setattr(bk, "ClaudeSDKClient", _FakeClient)
    asyncio.run(backend._ensure_client())
    return captured["options"].allowed_tools


def test_gated_tool_excluded_from_allowed_tools_when_confirm_cb_wired(tmp_path, monkeypatch):
    async def confirm(name, tool_input):
        return True

    backend = ClaudeBackend(_ctx(tmp_path, confirm_cb=confirm))
    allowed = _captured_allowed_tools(monkeypatch, backend)

    assert "mcp__sciqlop__sciqlop_exec_python" not in allowed
    assert "mcp__sciqlop__sciqlop_list_panels" in allowed


def test_gated_tool_excluded_from_allowed_tools_when_ask_question_cb_wired(tmp_path, monkeypatch):
    async def ask(questions):
        return {}

    backend = ClaudeBackend(_ctx(tmp_path, ask_question_cb=ask))
    allowed = _captured_allowed_tools(monkeypatch, backend)

    assert "mcp__sciqlop__sciqlop_exec_python" not in allowed


def test_gated_tool_stays_allowed_when_no_permission_callback_wired(tmp_path, monkeypatch):
    # No confirm_cb / ask_question_cb -> can_use_tool is None, so there is no
    # other mechanism to allow the call. Preserve today's fallback-allow.
    backend = ClaudeBackend(_ctx(tmp_path))
    allowed = _captured_allowed_tools(monkeypatch, backend)

    assert "mcp__sciqlop__sciqlop_exec_python" in allowed


def test_gated_tool_call_actually_reaches_permission_check(tmp_path):
    seen = {}

    async def confirm(name, tool_input):
        seen["name"] = name
        return False

    backend = ClaudeBackend(_ctx(tmp_path, confirm_cb=confirm))
    res = asyncio.run(
        backend._permission_check("mcp__sciqlop__sciqlop_exec_python", {"code": "1"}, None)
    )
    assert seen["name"] == "sciqlop_exec_python"
    from claude_agent_sdk import PermissionResultDeny
    assert isinstance(res, PermissionResultDeny)
