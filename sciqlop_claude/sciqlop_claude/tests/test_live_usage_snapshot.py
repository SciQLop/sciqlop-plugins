"""End-to-end check against the real `claude` CLI — opt-in.

The mocked tests pin the mapping; this pins that the mapping is fed anything at
all. It exists because the strip once shipped blank while every unit test
passed: `usage_snapshot()` was correct in isolation and starved in practice,
because nothing verified that a real client answers before the first turn.

Off by default — it spawns the CLI and needs a logged-in account. Run with:

    SCIQLOP_LIVE_CLAUDE=1 PYTHONPATH=<plugins>/sciqlop_claude \\
    uv run --no-sync --project <SciQLop> \\
    pytest sciqlop_claude/sciqlop_claude/tests/test_live_usage_snapshot.py -v -s

No model tokens are consumed: `get_context_usage` and `list_slash_commands` are
control requests to the local CLI, not API calls.
"""
import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from SciQLop.components.agents import backend as _agents_backend

pytestmark = [
    pytest.mark.skipif(
        isinstance(_agents_backend, MagicMock),
        reason="SciQLop is stubbed in this environment"),
    pytest.mark.skipif(
        not os.environ.get("SCIQLOP_LIVE_CLAUDE"),
        reason="live CLI test; set SCIQLOP_LIVE_CLAUDE=1 to run"),
    pytest.mark.skipif(
        shutil.which("claude") is None, reason="claude CLI not on PATH"),
]


def test_a_freshly_connected_backend_reports_context_before_any_turn():
    """The dock's bind sequence, unmocked: connect via `list_slash_commands`,
    then ask for usage. This is the path that was silently returning nothing."""
    from SciQLop.components.agents import BackendContext
    from SciQLop.components.agents.chat.formatters import info_segments
    from sciqlop_claude.backend import ClaudeBackend

    async def _confirm(name, tool_input):
        return True

    async def _run():
        tempdir = Path(tempfile.mkdtemp(prefix="sciqlop_live_claude_"))
        backend = ClaudeBackend(BackendContext(
            main_window=None, tools=[], tempdir=tempdir, confirm_cb=_confirm))
        try:
            assert await backend.usage_snapshot() is None, \
                "nothing is known before the client exists"

            await asyncio.wait_for(backend.list_slash_commands(), timeout=90)
            snapshot = await asyncio.wait_for(backend.usage_snapshot(), timeout=90)

            assert snapshot is not None, \
                "a connected backend reported nothing — the strip would be blank"
            assert snapshot.context_tokens and snapshot.context_tokens > 0
            assert snapshot.context_max and snapshot.context_max > snapshot.context_tokens
            assert snapshot.model
            # no turn has run, so per-turn figures must stay absent
            assert snapshot.tokens is None and snapshot.cost is None

            segments = info_segments(snapshot, "high")
            print(f"\nstrip would read: {' · '.join(segments)}")
            assert len(segments) >= 3      # model, effort, context %
        finally:
            await backend._disconnect()
            shutil.rmtree(tempdir, ignore_errors=True)

    asyncio.run(_run())
