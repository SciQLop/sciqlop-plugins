import asyncio
from types import SimpleNamespace

import pytest

from sciqlop_albert import backend


def _ctx(tmp_path):
    return SimpleNamespace(tools=[], confirm_cb=None, write_mode=None, guidance="", tempdir=tmp_path)


def _run(agen):
    async def consume():
        return [block async for block in agen]
    return asyncio.run(consume())


def test_backend_without_key_builds_so_the_agent_dock_still_opens(monkeypatch, tmp_path):
    """Raising here escaped the dock's construction and broke every other agent plugin's load()."""
    monkeypatch.setattr(backend, "_api_key", lambda: "")

    backend.AlbertBackend(_ctx(tmp_path))


def test_asking_without_key_says_how_to_set_it(monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "_api_key", lambda: "")
    albert = backend.AlbertBackend(_ctx(tmp_path))

    with pytest.raises(RuntimeError, match="Albert API key not configured"):
        _run(albert.ask("hello"))


def test_a_key_set_after_startup_is_used_without_restart(monkeypatch, tmp_path):
    key = {"value": ""}
    monkeypatch.setattr(backend, "_api_key", lambda: key["value"])
    sent = []

    async def fake_stream(url, headers, body, text_parts, tool_calls):
        sent.append(headers)
        return
        yield

    monkeypatch.setattr(backend, "_stream_sse", fake_stream)
    albert = backend.AlbertBackend(_ctx(tmp_path))
    asyncio.run(albert.set_model("some-model"))
    key["value"] = "the-key"

    _run(albert.ask("hello"))

    assert sent[0]["Authorization"] == "Bearer the-key"
