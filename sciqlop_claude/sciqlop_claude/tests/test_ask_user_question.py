"""AskUserQuestion must be answered via the can_use_tool callback.

When the model calls the built-in AskUserQuestion tool, the SDK delivers it to
`_permission_check`. The host must render it, collect the user's answers, and
return PermissionResultAllow(updated_input={..., "answers": ...}) — otherwise the
tool resolves with no answer and the model silently falls back to defaults.
"""
import asyncio
from types import SimpleNamespace

import pytest

from sciqlop_claude.backend import ClaudeBackend, _SDK_AVAILABLE
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

pytestmark = pytest.mark.skipif(not _SDK_AVAILABLE, reason="claude-agent-sdk not importable")


def _ctx(tmp_path, ask_question_cb=None):
    return SimpleNamespace(
        main_window=None, tools=[], tempdir=str(tmp_path),
        confirm_cb=None, write_mode="none", ask_question_cb=ask_question_cb,
    )


def test_ask_user_question_routes_to_callback_and_returns_answers(tmp_path):
    seen = {}

    async def ask(questions):
        seen["questions"] = questions
        return {"Format?": "Summary"}

    backend = ClaudeBackend(_ctx(tmp_path, ask_question_cb=ask))
    qin = {"questions": [{"question": "Format?", "header": "Fmt",
                          "options": [{"label": "Summary"}, {"label": "Detailed"}],
                          "multiSelect": False}]}
    res = asyncio.run(backend._permission_check("AskUserQuestion", qin, None))
    assert isinstance(res, PermissionResultAllow)
    assert res.updated_input["answers"] == {"Format?": "Summary"}
    assert seen["questions"] == qin["questions"]


def test_ask_user_question_without_callback_falls_back_to_allow(tmp_path):
    # no ask_question_cb wired → must not crash; degrades to allow (today's behavior)
    backend = ClaudeBackend(_ctx(tmp_path, ask_question_cb=None))
    res = asyncio.run(backend._permission_check("AskUserQuestion", {"questions": []}, None))
    assert isinstance(res, PermissionResultAllow)


def test_ask_user_question_callback_failure_denies(tmp_path):
    async def boom(questions):
        raise RuntimeError("ui gone")
    backend = ClaudeBackend(_ctx(tmp_path, ask_question_cb=boom))
    res = asyncio.run(backend._permission_check("AskUserQuestion", {"questions": []}, None))
    assert isinstance(res, PermissionResultDeny)
