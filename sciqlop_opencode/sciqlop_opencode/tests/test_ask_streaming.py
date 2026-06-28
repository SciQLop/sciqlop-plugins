"""OpencodeBackend.ask drives one _OpencodeStream per turn and flushes at the end.

Uses a fake SDK client (no opencode CLL/process) and monkeypatched block classes.
"""
import asyncio
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


class _FakeClient:
    def __init__(self, messages):
        self._messages = messages

    async def query(self, prompt):
        return None

    async def receive_response(self):
        for m in self._messages:
            yield m


def test_ask_streams_translated_blocks_and_flushes(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "TextBlock", _Text)
    monkeypatch.setattr(bk, "ToolActivityBlock", _Tool)

    inst = bk.OpencodeBackend.__new__(bk.OpencodeBackend)
    inst._lock = asyncio.Lock()
    fake = _FakeClient([
        sdk.AssistantMessage(content=[sdk.TextBlock(text="Hi")]),
        sdk.AssistantMessage(content=[sdk.TextBlock(text="Hi there")]),
        sdk.ResultMessage(),
    ])

    async def _fake_ensure():
        return fake

    monkeypatch.setattr(inst, "_ensure_client", _fake_ensure)

    async def _collect():
        return [b async for b in inst.ask("hi")]

    blocks = asyncio.run(_collect())
    texts = [b.text for b in blocks if isinstance(b, _Text)]
    assert "".join(texts) == "Hi there"
    assert blocks[-1] == _Text(text="", complete=True)
