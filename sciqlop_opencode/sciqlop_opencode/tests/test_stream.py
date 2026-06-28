"""`_OpencodeStream` converts opencode's accumulated-snapshot stream into the
incremental TextBlock/ToolActivityBlock deltas the SciQLop chat consumer expects.

Block classes are monkeypatched to lightweight dataclasses because the real ones
live in SciQLop's chat package, which may be stubbed in this test env. SDK message
constructors come from opencode_agent_sdk.types (skipped if absent).
"""
from dataclasses import dataclass, field

import pytest


@dataclass
class _Text:
    text: str = ""
    complete: bool = False


@dataclass
class _Tool:
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    result: object = None
    tool_use_id: str = ""


def _patch_blocks(monkeypatch):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "TextBlock", _Text)
    monkeypatch.setattr(bk, "ToolActivityBlock", _Tool)
    return bk


def _assistant(sdk, *blocks):
    return sdk.AssistantMessage(content=list(blocks))


def test_growing_snapshots_become_deltas_without_duplication(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    snaps = ["Hello", "Hello world", "Hello world, plotting now."]
    out = []
    for s in snaps:
        out.extend(stream.feed(_assistant(sdk, sdk.TextBlock(text=s))))
    out.extend(stream.flush())
    texts = [b.text for b in out if isinstance(b, _Text)]
    assert "".join(texts) == "Hello world, plotting now."
    assert out[-1] == _Text(text="", complete=True)


def test_duplicate_snapshot_emits_nothing(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    out = []
    for _ in range(2):
        out.extend(stream.feed(_assistant(sdk, sdk.TextBlock(text="Hi"))))
    assert out == [_Text(text="Hi", complete=False)]


def test_tool_call_closes_text_then_emits_activity(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    out = list(stream.feed(_assistant(sdk, sdk.TextBlock(text="Working"))))
    out += list(stream.feed(_assistant(sdk, sdk.ToolUseBlock(
        id="t1", name="mcp__sciqlop__sciqlop_screenshot_panel",
        input={"name": "P1"}))))
    assert out == [
        _Text(text="Working", complete=False),
        _Text(text="", complete=True),
        _Tool(tool_name="sciqlop_screenshot_panel",
              tool_input={"name": "P1"}, result=None, tool_use_id="t1"),
    ]


def test_text_after_tool_starts_fresh_block(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    out = list(stream.feed(_assistant(sdk, sdk.TextBlock(text="Working"))))
    out += list(stream.feed(_assistant(sdk, sdk.ToolUseBlock(
        id="t1", name="sciqlop_create_panel", input={}))))
    out += list(stream.feed(_assistant(sdk, sdk.TextBlock(text="Done"))))
    assert _Text(text="Done", complete=False) in out
    # "Done" is its own delta, never appended onto "Working"
    assert _Text(text="WorkingDone", complete=False) not in out


def test_flush_closes_dangling_block_and_is_idempotent(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    list(stream.feed(_assistant(sdk, sdk.TextBlock(text="partial"))))
    assert list(stream.flush()) == [_Text(text="", complete=True)]
    assert list(stream.flush()) == []


def test_system_and_result_messages_emit_no_blocks(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    out = list(stream.feed(sdk.SystemMessage(subtype="init", data={})))
    out += list(stream.feed(sdk.ResultMessage()))
    assert out == []


def test_end_to_end_against_consumer_contract(monkeypatch):
    """The translator's deltas, fed through the dock's text append-merge logic,
    reconstruct the final text with no duplication (the original bug)."""
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)

    def append_block(blocks, block):  # mirrors AgentChatDock._append_block (text path)
        if isinstance(block, _Text):
            last = blocks[-1] if blocks else None
            if type(last) is _Text and not last.complete:
                last.text += block.text
                last.complete = block.complete
                return
        blocks.append(block)

    stream = bk._OpencodeStream()
    rendered = []
    for s in ["Hello", "Hello world", "Hello world, plotting now."]:
        for b in stream.feed(_assistant(sdk, sdk.TextBlock(text=s))):
            append_block(rendered, b)
    for b in stream.flush():
        append_block(rendered, b)
    text = "".join(b.text for b in rendered if isinstance(b, _Text))
    assert text == "Hello world, plotting now."
    assert sum(1 for b in rendered if isinstance(b, _Text)) == 1
