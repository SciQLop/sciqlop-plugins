"""Executable resolution: `which` first, well-known macOS locations, login-shell probe last."""

import asyncio
from unittest.mock import MagicMock

import pytest

from SciQLop.components.agents import backend as _agents_backend

pytestmark = pytest.mark.skipif(
    isinstance(_agents_backend, MagicMock),
    reason="SciQLop is stubbed in this environment",
)


def test_which_hit_is_returned_as_is(monkeypatch):
    from sciqlop_claude import backend as mod

    monkeypatch.setattr(
        "shutil.which", lambda name: "/usr/bin/claude" if name == "claude" else None
    )

    def _no_shell():
        raise AssertionError("shell must not be probed when which hits")

    monkeypatch.setattr(mod, "_shell_probe", _no_shell)
    assert mod.resolve_claude_executable() == "/usr/bin/claude"


def test_well_known_homebrew_path_covers_finder_launches(monkeypatch):
    """Finder-launched SciQLop inherits a minimal PATH without /opt/homebrew/bin."""
    from sciqlop_claude import backend as mod

    assert "/opt/homebrew/bin/claude" in mod._well_known_candidates()
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("os.path.isfile", lambda p: p == "/opt/homebrew/bin/claude")
    monkeypatch.setattr("os.access", lambda p, mode: True)

    def _no_shell():
        raise AssertionError("shell must not be probed on a well-known hit")

    monkeypatch.setattr(mod, "_shell_probe", _no_shell)
    assert mod.resolve_claude_executable() == "/opt/homebrew/bin/claude"


def test_non_executable_candidates_are_skipped(monkeypatch):
    from sciqlop_claude import backend as mod

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(
        mod,
        "_well_known_candidates",
        lambda: ["/opt/homebrew/bin/claude", "/usr/local/bin/claude"],
    )
    monkeypatch.setattr("os.path.isfile", lambda p: True)
    monkeypatch.setattr("os.access", lambda p, mode: p != "/opt/homebrew/bin/claude")
    monkeypatch.setattr(mod, "_shell_probe", lambda: None)
    assert mod.resolve_claude_executable() == "/usr/local/bin/claude"


def test_login_shell_probe_is_the_last_resort(monkeypatch):
    from sciqlop_claude import backend as mod

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(mod, "_well_known_candidates", lambda: [])
    calls = []
    monkeypatch.setattr(
        mod, "_shell_probe", lambda: calls.append(True) or "/some/dir/claude"
    )
    assert mod.resolve_claude_executable() == "/some/dir/claude"
    assert calls == [True]


def test_none_when_nothing_is_found_anywhere(monkeypatch):
    from sciqlop_claude import backend as mod

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(mod, "_well_known_candidates", lambda: [])
    monkeypatch.setattr(mod, "_shell_probe", lambda: None)
    assert mod.resolve_claude_executable() is None


@pytest.mark.parametrize(
    ("resolved", "expected"),
    [("/opt/homebrew/bin/claude", True), (None, False)],
)
def test_claude_cli_available_reflects_the_resolver(monkeypatch, resolved, expected):
    from sciqlop_claude import backend as mod

    monkeypatch.setattr(mod, "resolve_claude_executable", lambda: resolved)
    assert mod.claude_cli_available() is expected


def _bare_backend(mod):
    be = object.__new__(mod.ClaudeBackend)
    be._model = None
    be._effort = None
    be._resume = None
    be._tools = []
    be._confirm_cb = None
    be._ask_question_cb = None
    be._guidance = ""
    be._write_mode = "default"
    be._client = None
    return be


def test_ensure_client_passes_resolved_cli_path(monkeypatch, tmp_path):
    from sciqlop_claude import backend as mod

    captured = {}

    class FakeClient:
        def __init__(self, options):
            captured["options"] = options

        async def connect(self):
            return None

    monkeypatch.setattr(mod, "ClaudeSDKClient", FakeClient)
    monkeypatch.setattr(mod, "create_sdk_mcp_server", lambda **kw: object())
    monkeypatch.setattr(
        mod, "resolve_claude_executable", lambda: "/opt/homebrew/bin/claude"
    )
    monkeypatch.setattr(mod._sessions, "current_workspace_dir", lambda: tmp_path)

    asyncio.run(_bare_backend(mod)._ensure_client())
    assert captured["options"].cli_path == "/opt/homebrew/bin/claude"


def test_fetch_models_throwaway_client_carries_resolved_cli_path(monkeypatch):
    from sciqlop_claude import backend as mod

    captured = {}

    class FakeClient:
        def __init__(self, options):
            captured["options"] = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_server_info(self):
            return {"models": [{"value": "default", "displayName": "Default"}]}

    monkeypatch.setattr(mod, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(mod, "ClaudeSDKClient", FakeClient)
    monkeypatch.setattr(
        mod, "resolve_claude_executable", lambda: "/opt/homebrew/bin/claude"
    )

    assert mod.fetch_models(timeout=5.0) == [("Default", None)]
    assert captured["options"].cli_path == "/opt/homebrew/bin/claude"
