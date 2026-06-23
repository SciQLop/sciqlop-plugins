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
    )
    assert blocks == [_Thinking(text="pondering"), _Text(text="Answer")]


def test_replay_skips_blank_thinking(monkeypatch):
    from sciqlop_claude import sessions

    monkeypatch.setattr(sessions, "ThinkingBlock", _Thinking)
    blocks = sessions._render_blocks(
        [{"type": "thinking", "thinking": "  \n"}], None, _Text, _Image
    )
    assert blocks == []


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
