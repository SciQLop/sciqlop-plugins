"""Permission gating tests for OpencodeBackend's PreToolUse hook.

The hook is tested in isolation — we don't need a real opencode SDK
running, only the dict-in / dict-out contract.
"""
import asyncio

from sciqlop_opencode import backend as bk


class _StubConfirm:
    def __init__(self, decision: bool):
        self.decision = decision
        self.calls = []

    async def __call__(self, name, args):
        self.calls.append((name, args))
        return self.decision


def _make_backend(*, gated, allow_writes, confirm_decision=True):
    inst = bk.OpencodeBackend.__new__(bk.OpencodeBackend)
    inst._gated_names = set(gated)
    inst._allow_writes = allow_writes
    inst._confirm_cb = _StubConfirm(confirm_decision)
    return inst


def _input(name, **fields):
    return {"tool_name": f"mcp__sciqlop__{name}", "tool_input": fields}


def _call_hook(inst, input_data):
    """Invoke the hook (async). Returns its decision dict or None."""
    return asyncio.run(inst._pre_tool_use_hook(input_data, "tool-use-1", {}))


def test_ungated_tool_is_allowed():
    inst = _make_backend(gated={"sciqlop_exec_python"}, allow_writes=False)
    result = _call_hook(inst, _input("sciqlop_window_state"))
    assert result is None  # None / no decision = allow


def test_gated_tool_denied_when_writes_disabled():
    inst = _make_backend(gated={"sciqlop_exec_python"}, allow_writes=False)
    result = _call_hook(inst, _input("sciqlop_exec_python", code="print(1)"))
    assert result["permissionDecision"] == "deny"
    assert "Allow write actions" in result["permissionDecisionReason"]


def test_gated_tool_allowed_when_user_confirms():
    inst = _make_backend(gated={"sciqlop_exec_python"}, allow_writes=True, confirm_decision=True)
    result = _call_hook(inst, _input("sciqlop_exec_python", code="print(1)"))
    assert result["permissionDecision"] == "allow"
    assert inst._confirm_cb.calls == [("sciqlop_exec_python", {"code": "print(1)"})]


def test_gated_tool_denied_when_user_refuses():
    inst = _make_backend(gated={"sciqlop_exec_python"}, allow_writes=True, confirm_decision=False)
    result = _call_hook(inst, _input("sciqlop_exec_python", code="print(1)"))
    assert result["permissionDecision"] == "deny"
