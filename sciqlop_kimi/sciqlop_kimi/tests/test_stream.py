"""`_KimiStream` converts kimi-agent-sdk wire messages into the StreamBlocks
the SciQLop chat consumer expects: text/think deltas forwarded as incomplete
blocks, closed on interruption or turn end; tool calls and results mapped to
ToolActivityBlocks correlated by tool_use_id.

Block classes are monkeypatched to lightweight dataclasses because the real
ones live in SciQLop's chat package, which may be stubbed in this test env.
Wire message constructors come from kimi_agent_sdk (skipped if absent).
"""
from dataclasses import dataclass, field

import pytest


@dataclass
class _Text:
    text: str = ""
    complete: bool = False


@dataclass
class _Think:
    text: str = ""
    complete: bool = False


@dataclass
class _Image:
    path: str = ""


@dataclass
class _Tool:
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    result: object = None
    tool_use_id: str = ""


def _patch_blocks(monkeypatch):
    from sciqlop_kimi import backend as bk

    monkeypatch.setattr(bk, "TextBlock", _Text)
    monkeypatch.setattr(bk, "ThinkingBlock", _Think)
    monkeypatch.setattr(bk, "ImageBlock", _Image)
    monkeypatch.setattr(bk, "ToolActivityBlock", _Tool)
    monkeypatch.setattr(bk, "write_b64_image", lambda *a, **k: None)
    return bk


def _stream(bk, tmp_path):
    return bk._KimiStream(tmp_path)


def test_text_deltas_forward_and_close_on_turn_end(monkeypatch, tmp_path):
    sdk = pytest.importorskip("kimi_agent_sdk")
    bk = _patch_blocks(monkeypatch)
    stream = _stream(bk, tmp_path)
    out = []
    for delta in ["Hello", " world"]:
        out.extend(stream.feed(sdk.TextPart(text=delta)))
    out.extend(stream.feed(sdk.TurnEnd()))
    assert out == [
        _Text(text="Hello", complete=False),
        _Text(text=" world", complete=False),
        _Text(text="", complete=True),
    ]


def test_think_and_text_interleave_close_each_other(monkeypatch, tmp_path):
    sdk = pytest.importorskip("kimi_agent_sdk")
    bk = _patch_blocks(monkeypatch)
    stream = _stream(bk, tmp_path)
    out = list(stream.feed(sdk.ThinkPart(think="hmm")))
    out += list(stream.feed(sdk.TextPart(text="answer")))
    out += list(stream.flush())
    assert out == [
        _Think(text="hmm", complete=False),
        _Think(text="", complete=True),
        _Text(text="answer", complete=False),
        _Text(text="", complete=True),
    ]


def test_tool_call_closes_text_and_emits_activity(monkeypatch, tmp_path):
    sdk = pytest.importorskip("kimi_agent_sdk")
    bk = _patch_blocks(monkeypatch)
    stream = _stream(bk, tmp_path)
    out = list(stream.feed(sdk.TextPart(text="Working")))
    out += list(stream.feed(sdk.ToolCall(
        id="t1",
        function=sdk.ToolCall.FunctionBody(
            name="sciqlop_screenshot_panel", arguments='{"name": "P1"}'
        ),
    )))
    assert out == [
        _Text(text="Working", complete=False),
        _Text(text="", complete=True),
        _Tool(tool_name="sciqlop_screenshot_panel",
              tool_input={"name": "P1"}, result=None, tool_use_id="t1"),
    ]


def test_tool_result_emits_result_only_block(monkeypatch, tmp_path):
    sdk = pytest.importorskip("kimi_agent_sdk")
    bk = _patch_blocks(monkeypatch)
    stream = _stream(bk, tmp_path)
    out = list(stream.feed(sdk.ToolResult(
        tool_call_id="t1",
        return_value=sdk.ToolOk(output="panel PNG captured"),
    )))
    assert out == [_Tool(tool_use_id="t1", result="panel PNG captured")]


def test_tool_result_with_image_writes_image_block(monkeypatch, tmp_path):
    sdk = pytest.importorskip("kimi_agent_sdk")
    from kosong.message import ImageURLPart
    bk = _patch_blocks(monkeypatch)
    monkeypatch.setattr(bk, "write_b64_image", lambda *a, **k: "/tmp/fake.png")
    stream = _stream(bk, tmp_path)
    out = list(stream.feed(sdk.ToolResult(
        tool_call_id="t1",
        return_value=sdk.ToolOk(output=[
            sdk.TextPart(text="screenshot"),
            ImageURLPart(image_url=ImageURLPart.ImageURL(url="data:image/png;base64,AAAA")),
        ]),
    )))
    assert _Image(path="/tmp/fake.png") in out
    assert _Tool(tool_use_id="t1", result="screenshot") in out


def test_flush_is_idempotent(monkeypatch, tmp_path):
    sdk = pytest.importorskip("kimi_agent_sdk")
    bk = _patch_blocks(monkeypatch)
    stream = _stream(bk, tmp_path)
    list(stream.feed(sdk.TextPart(text="partial")))
    assert list(stream.flush()) == [_Text(text="", complete=True)]
    assert list(stream.flush()) == []


def test_end_to_end_against_consumer_contract(monkeypatch, tmp_path):
    """The translator's deltas, fed through the dock's text append-merge logic,
    reconstruct the final text with no duplication."""
    sdk = pytest.importorskip("kimi_agent_sdk")
    bk = _patch_blocks(monkeypatch)

    def append_block(blocks, block):  # mirrors AgentChatDock._append_block (text path)
        if isinstance(block, _Text):
            last = blocks[-1] if blocks else None
            if type(last) is _Text and not last.complete:
                last.text += block.text
                last.complete = block.complete
                return
        blocks.append(block)

    stream = _stream(bk, tmp_path)
    rendered = []
    for delta in ["Hello", " world", ", plotting now."]:
        for b in stream.feed(sdk.TextPart(text=delta)):
            append_block(rendered, b)
    for b in stream.feed(sdk.TurnEnd()):
        append_block(rendered, b)
    text = "".join(b.text for b in rendered if isinstance(b, _Text))
    assert text == "Hello world, plotting now."
    assert sum(1 for b in rendered if isinstance(b, _Text)) == 1
