"""Tests for the SQLite-backed opencode session reader."""
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

from sciqlop_opencode import sessions as sess


_SCHEMA = """
CREATE TABLE session (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    directory    TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    model        TEXT
);
CREATE TABLE message (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    data         TEXT NOT NULL
);
CREATE TABLE part (
    id           TEXT PRIMARY KEY,
    message_id   TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    data         TEXT NOT NULL
);
"""


def _make_db(tmp_path: Path) -> Path:
    data_dir = tmp_path / "opencode-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "opencode.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    return data_dir


def _insert_session(data_dir: Path, *, sid, directory, title, mtime_ms, model=None):
    db = data_dir / "opencode.db"
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO session (id, title, directory, time_created, time_updated, model)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (sid, title, directory, mtime_ms, mtime_ms, model),
        )


def _insert_message(data_dir: Path, *, mid, sid, role, time_created):
    db = data_dir / "opencode.db"
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO message (id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, ?)",
            (mid, sid, time_created, time_created, json.dumps({"role": role})),
        )


def _insert_part(data_dir: Path, *, pid, mid, sid, payload, time_created):
    db = data_dir / "opencode.db"
    with sqlite3.connect(db) as c:
        c.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (pid, mid, sid, time_created, time_created, json.dumps(payload)),
        )


def test_list_sessions_filters_by_workspace(tmp_path, monkeypatch):
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    _insert_session(data_dir, sid="sess-a", directory="/work/ws-a", title="alpha", mtime_ms=200_000)
    _insert_session(data_dir, sid="sess-b", directory="/work/ws-b", title="beta", mtime_ms=300_000)
    monkeypatch.setattr(sess, "current_workspace_dir", lambda: Path("/work/ws-a"))

    out = sess.list_sessions()
    assert [s.session_id for s in out] == ["sess-a"]
    assert out[0].label == "alpha"
    assert out[0].mtime == 200.0


def test_list_sessions_sorted_by_mtime_desc(tmp_path, monkeypatch):
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    _insert_session(data_dir, sid="old", directory="/w", title="old", mtime_ms=100_000)
    _insert_session(data_dir, sid="new", directory="/w", title="new", mtime_ms=500_000)
    monkeypatch.setattr(sess, "current_workspace_dir", lambda: Path("/w"))

    out = sess.list_sessions()
    assert [s.session_id for s in out] == ["new", "old"]


def test_list_sessions_returns_empty_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path / "does-not-exist"))
    assert sess.list_sessions() == []


def test_list_sessions_falls_back_when_title_blank(tmp_path, monkeypatch):
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    _insert_session(data_dir, sid="sess", directory="/w", title="", mtime_ms=100_000)
    monkeypatch.setattr(sess, "current_workspace_dir", lambda: Path("/w"))

    out = sess.list_sessions()
    assert out[0].label == "(untitled session)"


def _stub_chat_module(monkeypatch):
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
    monkeypatch.setitem(sys.modules, "SciQLop.components.agents.chat", fake_chat)


def test_load_session_messages_replays_text_parts(tmp_path, monkeypatch):
    _stub_chat_module(monkeypatch)
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    _insert_session(data_dir, sid="sid", directory="/w", title="t", mtime_ms=1)
    _insert_message(data_dir, mid="m1", sid="sid", role="user", time_created=10)
    _insert_part(data_dir, pid="p1", mid="m1", sid="sid",
                 payload={"type": "text", "text": "hi"}, time_created=11)
    _insert_message(data_dir, mid="m2", sid="sid", role="assistant", time_created=20)
    _insert_part(data_dir, pid="p2", mid="m2", sid="sid",
                 payload={"type": "text", "text": "hello"}, time_created=21)

    out = sess.load_session_messages("sid")
    assert [(m.role, m.blocks[0].text) for m in out] == [("user", "hi"), ("assistant", "hello")]


def test_load_session_messages_skips_internal_part_types(tmp_path, monkeypatch):
    _stub_chat_module(monkeypatch)
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    _insert_session(data_dir, sid="sid", directory="/w", title="t", mtime_ms=1)
    _insert_message(data_dir, mid="m1", sid="sid", role="assistant", time_created=10)
    _insert_part(data_dir, pid="p1", mid="m1", sid="sid",
                 payload={"type": "reasoning", "text": "thinking..."}, time_created=11)
    _insert_part(data_dir, pid="p2", mid="m1", sid="sid",
                 payload={"type": "step-start"}, time_created=12)
    _insert_part(data_dir, pid="p3", mid="m1", sid="sid",
                 payload={"type": "tool", "tool": "glob"}, time_created=13)
    _insert_part(data_dir, pid="p4", mid="m1", sid="sid",
                 payload={"type": "text", "text": "final answer"}, time_created=14)

    out = sess.load_session_messages("sid")
    assert len(out) == 1
    assert out[0].role == "assistant"
    assert [b.text for b in out[0].blocks] == ["final answer"]


def test_load_session_messages_missing_session_returns_empty(tmp_path, monkeypatch):
    _stub_chat_module(monkeypatch)
    _make_db(tmp_path / "x")
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path / "x"))
    assert sess.load_session_messages("nonexistent") == []


def test_load_session_messages_coalesces_consecutive_assistant_parts(tmp_path, monkeypatch):
    _stub_chat_module(monkeypatch)
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    _insert_session(data_dir, sid="sid", directory="/w", title="t", mtime_ms=1)
    _insert_message(data_dir, mid="m1", sid="sid", role="assistant", time_created=10)
    _insert_part(data_dir, pid="p1", mid="m1", sid="sid",
                 payload={"type": "text", "text": "part one"}, time_created=11)
    _insert_message(data_dir, mid="m2", sid="sid", role="assistant", time_created=20)
    _insert_part(data_dir, pid="p2", mid="m2", sid="sid",
                 payload={"type": "text", "text": "part two"}, time_created=21)

    out = sess.load_session_messages("sid")
    assert len(out) == 1
    assert [b.text for b in out[0].blocks] == ["part one", "part two"]


def test_known_session_models_returns_distinct_specs(tmp_path, monkeypatch):
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    spec_a = json.dumps({"id": "free-model-a", "providerID": "opencode"})
    spec_a_variant = json.dumps({"id": "free-model-a", "providerID": "opencode", "variant": "default"})
    spec_b = json.dumps({"id": "gpt-4o", "providerID": "openai"})
    _insert_session(data_dir, sid="s1", directory="/w", title="a", mtime_ms=1, model=spec_a)
    _insert_session(data_dir, sid="s2", directory="/w", title="b", mtime_ms=2, model=spec_a_variant)
    _insert_session(data_dir, sid="s3", directory="/w", title="c", mtime_ms=3, model=spec_b)

    out = sess.known_session_models()
    keys = sorted((m["providerID"], m["id"]) for m in out)
    assert keys == [("openai", "gpt-4o"), ("opencode", "free-model-a")]


def test_known_session_models_returns_empty_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path / "missing"))
    assert sess.known_session_models() == []
