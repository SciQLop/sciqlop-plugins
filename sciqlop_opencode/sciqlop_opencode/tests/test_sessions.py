"""Tests for opencode session storage walker."""
import json
import os
from pathlib import Path

from sciqlop_opencode import sessions as sess


def _write_session(storage: Path, project_hash: str, sid: str, *, cwd: str, label: str, mtime: float | None = None) -> Path:
    sdir = storage / "session" / project_hash
    sdir.mkdir(parents=True, exist_ok=True)
    p = sdir / f"{sid}.json"
    p.write_text(json.dumps({"id": sid, "cwd": cwd, "label": label}))
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def test_list_sessions_filters_by_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    storage = tmp_path / "storage"
    _write_session(storage, "hashA", "sess-1", cwd="/work/ws-a", label="alpha")
    _write_session(storage, "hashB", "sess-2", cwd="/work/ws-b", label="beta")

    monkeypatch.setattr(sess, "current_workspace_dir", lambda: Path("/work/ws-a"))

    out = sess.list_sessions()
    assert [s.session_id for s in out] == ["sess-1"]
    assert out[0].label == "alpha"


def test_list_sessions_sorted_by_mtime_desc(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    storage = tmp_path / "storage"
    _write_session(storage, "h", "old", cwd="/w", label="old", mtime=100.0)
    _write_session(storage, "h", "new", cwd="/w", label="new", mtime=200.0)

    monkeypatch.setattr(sess, "current_workspace_dir", lambda: Path("/w"))

    out = sess.list_sessions()
    assert [s.session_id for s in out] == ["new", "old"]


def test_list_sessions_returns_empty_when_storage_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path / "does-not-exist"))
    assert sess.list_sessions() == []


def test_list_sessions_tolerates_corrupt_json(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    storage = tmp_path / "storage"
    sdir = storage / "session" / "h"
    sdir.mkdir(parents=True)
    (sdir / "broken.json").write_text("{not json")
    _write_session(storage, "h", "good", cwd="/w", label="ok")

    monkeypatch.setattr(sess, "current_workspace_dir", lambda: Path("/w"))

    out = sess.list_sessions()
    assert [s.session_id for s in out] == ["good"]


def _write_message(storage: Path, sid: str, name: str, payload: dict) -> Path:
    mdir = storage / "message" / sid
    mdir.mkdir(parents=True, exist_ok=True)
    p = mdir / f"{name}.json"
    p.write_text(json.dumps(payload))
    return p


def test_load_session_messages_decodes_text_blocks(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    import sys

    # SciQLop.components.agents.chat is stubbed by conftest; replace ChatMessage / TextBlock
    # with simple namespace-like objects so we can introspect the result.
    fake_chat = MagicMock()

    class _Msg:
        def __init__(self, role, blocks, done=True):
            self.role = role
            self.blocks = list(blocks)
            self.done = done

    class _Text:
        def __init__(self, text):
            self.text = text

    class _Image:
        def __init__(self, path):
            self.path = path

    fake_chat.ChatMessage = _Msg
    fake_chat.TextBlock = _Text
    fake_chat.ImageBlock = _Image
    fake_chat.write_b64_image = lambda data, mime, tempdir, prefix: None
    monkeypatch.setitem(sys.modules, "SciQLop.components.agents.chat", fake_chat)

    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    storage = tmp_path / "storage"
    _write_message(storage, "sid", "msg_001", {"role": "user", "content": [{"type": "text", "text": "hi"}]})
    _write_message(storage, "sid", "msg_002", {"role": "assistant", "content": [{"type": "text", "text": "hello"}]})

    out = sess.load_session_messages("sid", image_tempdir=tmp_path / "imgs")
    assert [(m.role, m.blocks[0].text) for m in out] == [("user", "hi"), ("assistant", "hello")]


def test_load_session_messages_skips_unknown_blocks(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    import sys

    fake_chat = MagicMock()

    class _Msg:
        def __init__(self, role, blocks, done=True):
            self.role = role
            self.blocks = list(blocks)
            self.done = done

    class _Text:
        def __init__(self, text):
            self.text = text

    fake_chat.ChatMessage = _Msg
    fake_chat.TextBlock = _Text
    fake_chat.ImageBlock = MagicMock
    fake_chat.write_b64_image = lambda data, mime, tempdir, prefix: None
    monkeypatch.setitem(sys.modules, "SciQLop.components.agents.chat", fake_chat)

    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    storage = tmp_path / "storage"
    _write_message(storage, "sid", "msg_001", {
        "role": "user",
        "content": [
            {"type": "text", "text": "hi"},
            {"type": "weird_unknown_type", "stuff": 123},
        ],
    })

    out = sess.load_session_messages("sid", image_tempdir=None)
    assert len(out) == 1
    assert out[0].blocks[0].text == "hi"


def test_load_session_messages_missing_session_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    assert sess.load_session_messages("nonexistent", image_tempdir=None) == []
