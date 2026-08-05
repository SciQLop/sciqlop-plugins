"""Streamed and replayed messages must carry thinking and completeness.

Two regressions are pinned here:
- `_decode_message` only looked at `.text`, so SDK ThinkingBlocks (which carry
  `.thinking`) were silently dropped from the transcript.
- Assistant texts were yielded without `complete=True`, so the dock glued one
  API round's markdown straight onto the previous one ("…done.## Results"),
  corrupting live rendering while session replay looked fine.

Block classes are injected as lightweight dataclasses because the real ones
live in SciQLop's chat package, which may be stubbed in this test env.
"""
from dataclasses import dataclass

import pytest


@dataclass
class _Text:
    text: str = ""
    complete: bool = False


@dataclass
class _Thinking:
    text: str = ""
    complete: bool = False


@dataclass
class _Image:
    path: str = ""


@dataclass
class _Tool:
    tool_name: str = ""
    tool_input: dict = None
    result: object = None
    tool_use_id: str = ""


def test_replay_keeps_thinking_blocks(monkeypatch):
    from sciqlop_claude import sessions

    monkeypatch.setattr(sessions, "ThinkingBlock", _Thinking)
    blocks = sessions._render_blocks(
        [
            {"type": "thinking", "thinking": "pondering", "signature": "sig"},
            {"type": "text", "text": "Answer"},
        ],
        None,
        _Text,
        _Image,
        _Tool,
    )
    assert blocks == [_Thinking(text="pondering"), _Text(text="Answer")]


def test_replay_skips_blank_thinking(monkeypatch):
    from sciqlop_claude import sessions

    monkeypatch.setattr(sessions, "ThinkingBlock", _Thinking)
    blocks = sessions._render_blocks(
        [{"type": "thinking", "thinking": "  \n"}], None, _Text, _Image, _Tool
    )
    assert blocks == []


def test_replay_renders_tool_use_as_activity_block():
    from sciqlop_claude import sessions

    blocks = sessions._render_blocks(
        [{"type": "tool_use", "id": "tu1",
          "name": "mcp__sciqlop__sciqlop_screenshot_panel",
          "input": {"name": "P1"}}],
        None, _Text, _Image, _Tool,
    )
    assert blocks == [_Tool(tool_name="sciqlop_screenshot_panel",
                            tool_input={"name": "P1"}, tool_use_id="tu1")]


def test_replay_skips_task_notification_user_message(tmp_path):
    """The CLI persists background-task wakeups as user records whose text is
    raw <task-notification> XML — an artifact of the live turn, not something
    the user typed. The replay must drop it (and it must never become the
    session's label)."""
    import json
    from sciqlop_claude import sessions

    line = json.dumps({
        "type": "user",
        "message": {"content": [{"type": "text", "text":
            "<task-notification>\n<task-id>b49xqqbke</task-id>\n"
            "<status>completed</status>\n</task-notification>"}]},
    })
    messages = []
    sessions._append_record(line, messages, tmp_path, *_stub_message_types())
    assert messages == []


def test_replay_attaches_tool_result_to_matching_activity(tmp_path):
    """A tool_result-only user record must fill the matching activity block's
    result (live-path parity), not just append images."""
    import json
    from sciqlop_claude import sessions

    ChatMessage, TextBlock, ImageBlock, ToolActivityBlock = _stub_message_types()
    messages = []
    sessions._append_record(json.dumps({
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"command": "ls"}},
            {"type": "text", "text": "Listing files."},
        ]},
    }), messages, tmp_path, ChatMessage, TextBlock, ImageBlock, ToolActivityBlock)
    sessions._append_record(json.dumps({
        "type": "user",
        "message": {"content": [
            {"type": "tool_result", "tool_use_id": "tu1",
             "content": [{"type": "text", "text": "file1.py  file2.py"}]},
        ]},
    }), messages, tmp_path, ChatMessage, TextBlock, ImageBlock, ToolActivityBlock)

    assert len(messages) == 1
    activity = next(b for b in messages[0].blocks if isinstance(b, _Tool))
    assert activity.result == "file1.py file2.py"
    # the text block after the tool call is preserved too
    assert any(getattr(b, "text", "") == "Listing files." for b in messages[0].blocks)


def _stub_message_types():
    from dataclasses import dataclass as _dc, field as _field

    @_dc
    class _ChatMessage:
        role: str
        blocks: list = _field(default_factory=list)
        done: bool = False

    return _ChatMessage, _Text, _Image, _Tool


def test_decode_keeps_thinking_and_marks_texts_complete(monkeypatch):
    sdk_types = pytest.importorskip("claude_agent_sdk.types")
    from sciqlop_claude import backend as backend_mod

    monkeypatch.setattr(backend_mod, "TextBlock", _Text)
    monkeypatch.setattr(backend_mod, "ThinkingBlock", _Thinking)
    message = sdk_types.AssistantMessage(
        content=[
            sdk_types.ThinkingBlock(thinking="hmm", signature="sig"),
            sdk_types.TextBlock(text="## Results"),
        ],
        model="claude",
    )
    blocks = backend_mod.ClaudeBackend._decode_message(None, message)
    assert blocks == [
        _Thinking(text="hmm", complete=True),
        _Text(text="## Results", complete=True),
    ]
