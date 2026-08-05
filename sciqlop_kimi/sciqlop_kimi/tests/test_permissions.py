"""Permission decisions and MCP-layer gating.

The permission layer answers Kimi's ACP session/request_permission: SciQLop
MCP tools auto-approve unless gated; gated ones go through the dock's confirm
dialog when writes are enabled; Kimi's built-in tools (shell, file edits) are
always rejected. The MCP server re-checks the same gate inside the tool call,
so a tool the agent never asks permission for is still blocked.
"""
from types import SimpleNamespace

import pytest


def _options():
    from acp.schema import PermissionOption
    return [
        PermissionOption(kind="allow_once", name="Allow once", option_id="allow-once"),
        PermissionOption(kind="allow_always", name="Always allow", option_id="allow-always"),
        PermissionOption(kind="reject_once", name="Reject once", option_id="reject-once"),
        PermissionOption(kind="reject_always", name="Always reject", option_id="reject-always"),
    ]


def _tool_call(title, raw_input=None):
    return SimpleNamespace(title=title, raw_input=raw_input or {})


def _backend(tools, allow_writes=False, confirm_cb=None):
    from sciqlop_kimi.backend import KimiBackend

    backend = KimiBackend.__new__(KimiBackend)
    backend._tools = tools
    backend._tool_names = {t["name"] for t in tools}
    backend._gated_names = {t["name"] for t in tools if t.get("gated")}
    backend._confirm_cb = confirm_cb
    backend._allow_writes = allow_writes
    return backend


def _tool(name="sciqlop_dummy", gated=False):
    return {"name": name, "description": "d",
            "input_schema": {"type": "object", "properties": {}}, "gated": gated,
            "handler": lambda args: "ok"}


async def _decide(backend, title, raw_input=None):
    return await backend._decide_permission(_options(), _tool_call(title, raw_input))


def _selected_option_id(response):
    return getattr(response.outcome, "option_id", None)


def test_read_tool_auto_approves():
    pytest.importorskip("acp")
    import asyncio
    backend = _backend([_tool()])
    resp = asyncio.run(_decide(backend, "sciqlop_dummy"))
    assert _selected_option_id(resp) == "allow-once"


def test_gated_tool_rejected_when_writes_disabled():
    pytest.importorskip("acp")
    import asyncio
    backend = _backend([_tool(gated=True)], allow_writes=False)
    resp = asyncio.run(_decide(backend, "sciqlop_dummy"))
    assert _selected_option_id(resp) == "reject-once"


def test_gated_tool_asks_user_when_writes_enabled():
    pytest.importorskip("acp")
    import asyncio
    seen = {}

    async def confirm(name, args):
        seen.update(name=name, args=args)
        return True

    backend = _backend([_tool(gated=True)], allow_writes=True, confirm_cb=confirm)
    resp = asyncio.run(_decide(backend, "mcp__sciqlop__sciqlop_dummy", {"code": "1+1"}))
    assert _selected_option_id(resp) == "allow-once"
    assert seen["name"] == "sciqlop_dummy"
    assert seen["args"] == {"code": "1+1"}


def test_gated_tool_denied_by_user():
    pytest.importorskip("acp")
    import asyncio

    async def confirm(name, args):
        return False

    backend = _backend([_tool(gated=True)], allow_writes=True, confirm_cb=confirm)
    resp = asyncio.run(_decide(backend, "sciqlop_dummy"))
    assert _selected_option_id(resp) == "reject-once"


def test_builtin_tools_are_rejected():
    pytest.importorskip("acp")
    import asyncio
    backend = _backend([_tool()], allow_writes=True)
    for title in ("Shell", "WriteFile", "StrReplaceFile"):
        resp = asyncio.run(_decide(backend, title))
        assert _selected_option_id(resp) == "reject-once", title


# ------------------------------------------------------------- MCP layer ---


def _mcp_server(tools, allow_writes=False, confirm_cb=None):
    from sciqlop_kimi.mcp_server import SciqlopMcpServer

    return SciqlopMcpServer(
        tools,
        {t["name"] for t in tools if t.get("gated")},
        is_write_allowed=lambda: allow_writes,
        confirm_cb=confirm_cb,
    )


def _texts(content):
    return [getattr(c, "text", "") for c in content]


def test_mcp_dispatch_runs_handler_and_wraps_text():
    pytest.importorskip("mcp")
    import asyncio
    server = _mcp_server([{**_tool(), "handler": lambda args: "plain result"}])
    out = asyncio.run(server._dispatch("sciqlop_dummy", {}))
    assert _texts(out) == ["plain result"]


def test_mcp_dispatch_converts_images():
    pytest.importorskip("mcp")
    import asyncio

    def handler(args):
        return {"content": [
            {"type": "text", "text": "shot"},
            {"type": "image", "data": "QUJD", "mimeType": "image/png"},
        ]}

    server = _mcp_server([{**_tool(), "handler": handler}])
    out = asyncio.run(server._dispatch("sciqlop_dummy", {}))
    assert _texts(out)[0] == "shot"
    images = [c for c in out if getattr(c, "data", None)]
    assert images and images[0].data == "QUJD" and images[0].mimeType == "image/png"


def test_mcp_dispatch_blocks_gated_tool_when_writes_disabled():
    pytest.importorskip("mcp")
    import asyncio
    called = []
    tool = {**_tool(gated=True), "handler": lambda args: called.append(args) or "ok"}
    server = _mcp_server([tool], allow_writes=False)
    out = asyncio.run(server._dispatch("sciqlop_dummy", {}))
    assert "disabled" in _texts(out)[0]
    assert called == []


def test_mcp_dispatch_gated_tool_needs_confirmation():
    pytest.importorskip("mcp")
    import asyncio

    async def confirm(name, args):
        return True

    tool = {**_tool(gated=True), "handler": lambda args: "ran"}
    server = _mcp_server([tool], allow_writes=True, confirm_cb=confirm)
    out = asyncio.run(server._dispatch("sciqlop_dummy", {}))
    assert _texts(out) == ["ran"]


def test_mcp_dispatch_handler_exception_becomes_error_text():
    pytest.importorskip("mcp")
    import asyncio

    def boom(args):
        raise ValueError("bad path")

    server = _mcp_server([{**_tool(), "handler": boom}])
    out = asyncio.run(server._dispatch("sciqlop_dummy", {}))
    assert "ValueError" in _texts(out)[0] and "bad path" in _texts(out)[0]
