"""`_AcpStream` converts ACP session updates into the StreamBlocks the SciQLop
chat consumer expects: text/thought chunks forwarded as incomplete blocks,
closed on interruption or turn end; tool calls and progress mapped to
ToolActivityBlocks correlated by tool_call_id.

Block classes are monkeypatched to lightweight dataclasses because the real
ones live in SciQLop's chat package, which may be stubbed in this test env.
Update objects come from the `acp` package (skipped if absent).
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
    return bk._AcpStream(tmp_path)


def _text_chunk(text):
    from acp.helpers import update_agent_message_text
    return update_agent_message_text(text)


def _thought_chunk(text):
    from acp.helpers import update_agent_thought_text
    return update_agent_thought_text(text)


def _feed(stream, update):
    return [b for b in stream.feed(update) if b is not None]


def test_text_chunks_forward_and_close_on_flush(monkeypatch, tmp_path):
    pytest.importorskip("acp")
    bk = _patch_blocks(monkeypatch)
    stream = _stream(bk, tmp_path)
    out = _feed(stream, _text_chunk("Hello"))
    out += _feed(stream, _text_chunk(" world"))
    out += [b for b in stream.flush() if b is not None]
    assert out == [
        _Text(text="Hello", complete=False),
        _Text(text=" world", complete=False),
        _Text(text="", complete=True),
    ]


def test_thought_and_text_interleave_close_each_other(monkeypatch, tmp_path):
    pytest.importorskip("acp")
    bk = _patch_blocks(monkeypatch)
    stream = _stream(bk, tmp_path)
    out = _feed(stream, _thought_chunk("hmm"))
    out += _feed(stream, _text_chunk("answer"))
    out += [b for b in stream.flush() if b is not None]
    assert out == [
        _Think(text="hmm", complete=False),
        _Think(text="", complete=True),
        _Text(text="answer", complete=False),
        _Text(text="", complete=True),
    ]


def test_tool_call_start_closes_text_and_emits_activity(monkeypatch, tmp_path):
    helpers = pytest.importorskip("acp.helpers")
    bk = _patch_blocks(monkeypatch)
    stream = _stream(bk, tmp_path)
    out = _feed(stream, _text_chunk("Working"))
    out += _feed(stream, helpers.start_tool_call(
        "tc1", "sciqlop_screenshot_panel", raw_input={"name": "P1"},
    ))
    assert out == [
        _Text(text="Working", complete=False),
        _Text(text="", complete=True),
        _Tool(tool_name="sciqlop_screenshot_panel",
              tool_input={"name": "P1"}, result=None, tool_use_id="tc1"),
    ]


def test_tool_progress_emits_result_only_block(monkeypatch, tmp_path):
    helpers = pytest.importorskip("acp.helpers")
    bk = _patch_blocks(monkeypatch)
    stream = _stream(bk, tmp_path)
    out = _feed(stream, helpers.update_tool_call(
        "tc1", status="completed", raw_output="panel PNG captured",
    ))
    assert out == [_Tool(tool_use_id="tc1", result="panel PNG captured")]


def test_tool_progress_with_image_writes_image_block(monkeypatch, tmp_path):
    helpers = pytest.importorskip("acp.helpers")
    bk = _patch_blocks(monkeypatch)
    monkeypatch.setattr(bk, "write_b64_image", lambda *a, **k: "/tmp/fake.png")
    stream = _stream(bk, tmp_path)
    out = _feed(stream, helpers.update_tool_call(
        "tc1",
        content=[helpers.tool_content(helpers.text_block("screenshot")),
                 helpers.tool_content(helpers.image_block("QUJD", "image/png"))],
    ))
    assert _Image(path="/tmp/fake.png") in out
    assert _Tool(tool_use_id="tc1", result="screenshot") in out


def test_untracked_updates_emit_nothing(monkeypatch, tmp_path):
    helpers = pytest.importorskip("acp.helpers")
    bk = _patch_blocks(monkeypatch)
    stream = _stream(bk, tmp_path)
    assert _feed(stream, helpers.update_current_mode("yolo")) == []
    assert _feed(stream, helpers.update_plan([])) == []


def test_end_to_end_against_consumer_contract(monkeypatch, tmp_path):
    """The translator's deltas, fed through the dock's text append-merge logic,
    reconstruct the final text with no duplication."""
    pytest.importorskip("acp")
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
        for b in _feed(stream, _text_chunk(delta)):
            append_block(rendered, b)
    for b in stream.flush():
        if b is not None:
            append_block(rendered, b)
    text = "".join(b.text for b in rendered if isinstance(b, _Text))
    assert text == "Hello world, plotting now."
    assert sum(1 for b in rendered if isinstance(b, _Text)) == 1
