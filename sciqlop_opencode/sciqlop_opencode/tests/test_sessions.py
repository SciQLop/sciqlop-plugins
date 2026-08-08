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
    _insert_session(
        data_dir, sid="sess-a", directory="/work/ws-a", title="alpha", mtime_ms=200_000
    )
    _insert_session(
        data_dir, sid="sess-b", directory="/work/ws-b", title="beta", mtime_ms=300_000
    )
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


def test_list_sessions_lists_everything_by_default(tmp_path, monkeypatch):
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    for i in range(60):
        _insert_session(
            data_dir,
            sid=f"s{i:02d}",
            directory="/w",
            title=f"t{i}",
            mtime_ms=1000 * (i + 1),
        )
    monkeypatch.setattr(sess, "current_workspace_dir", lambda: Path("/w"))

    assert len(sess.list_sessions()) == 60
    assert [s.session_id for s in sess.list_sessions(limit=2)] == ["s59", "s58"]


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
    _insert_part(
        data_dir,
        pid="p1",
        mid="m1",
        sid="sid",
        payload={"type": "text", "text": "hi"},
        time_created=11,
    )
    _insert_message(data_dir, mid="m2", sid="sid", role="assistant", time_created=20)
    _insert_part(
        data_dir,
        pid="p2",
        mid="m2",
        sid="sid",
        payload={"type": "text", "text": "hello"},
        time_created=21,
    )

    out = sess.load_session_messages("sid")
    assert [(m.role, m.blocks[0].text) for m in out] == [
        ("user", "hi"),
        ("assistant", "hello"),
    ]


def test_load_session_messages_skips_internal_part_types(tmp_path, monkeypatch):
    _stub_chat_module(monkeypatch)
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    _insert_session(data_dir, sid="sid", directory="/w", title="t", mtime_ms=1)
    _insert_message(data_dir, mid="m1", sid="sid", role="assistant", time_created=10)
    _insert_part(
        data_dir,
        pid="p1",
        mid="m1",
        sid="sid",
        payload={"type": "reasoning", "text": "thinking..."},
        time_created=11,
    )
    _insert_part(
        data_dir,
        pid="p2",
        mid="m1",
        sid="sid",
        payload={"type": "step-start"},
        time_created=12,
    )
    _insert_part(
        data_dir,
        pid="p3",
        mid="m1",
        sid="sid",
        payload={"type": "tool", "tool": "glob"},
        time_created=13,
    )
    _insert_part(
        data_dir,
        pid="p4",
        mid="m1",
        sid="sid",
        payload={"type": "text", "text": "final answer"},
        time_created=14,
    )

    out = sess.load_session_messages("sid")
    assert len(out) == 1
    assert out[0].role == "assistant"
    assert [b.text for b in out[0].blocks] == ["final answer"]


def test_load_session_messages_missing_session_returns_empty(tmp_path, monkeypatch):
    _stub_chat_module(monkeypatch)
    _make_db(tmp_path / "x")
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path / "x"))
    assert sess.load_session_messages("nonexistent") == []


def test_load_session_messages_coalesces_consecutive_assistant_parts(
    tmp_path, monkeypatch
):
    _stub_chat_module(monkeypatch)
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    _insert_session(data_dir, sid="sid", directory="/w", title="t", mtime_ms=1)
    _insert_message(data_dir, mid="m1", sid="sid", role="assistant", time_created=10)
    _insert_part(
        data_dir,
        pid="p1",
        mid="m1",
        sid="sid",
        payload={"type": "text", "text": "part one"},
        time_created=11,
    )
    _insert_message(data_dir, mid="m2", sid="sid", role="assistant", time_created=20)
    _insert_part(
        data_dir,
        pid="p2",
        mid="m2",
        sid="sid",
        payload={"type": "text", "text": "part two"},
        time_created=21,
    )

    out = sess.load_session_messages("sid")
    assert len(out) == 1
    assert [b.text for b in out[0].blocks] == ["part one", "part two"]


def test_known_session_models_returns_distinct_specs(tmp_path, monkeypatch):
    data_dir = _make_db(tmp_path)
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(data_dir))
    spec_a = json.dumps({"id": "free-model-a", "providerID": "opencode"})
    spec_a_variant = json.dumps(
        {"id": "free-model-a", "providerID": "opencode", "variant": "default"}
    )
    spec_b = json.dumps({"id": "gpt-4o", "providerID": "openai"})
    _insert_session(
        data_dir, sid="s1", directory="/w", title="a", mtime_ms=1, model=spec_a
    )
    _insert_session(
        data_dir, sid="s2", directory="/w", title="b", mtime_ms=2, model=spec_a_variant
    )
    _insert_session(
        data_dir, sid="s3", directory="/w", title="c", mtime_ms=3, model=spec_b
    )

    out = sess.known_session_models()
    keys = sorted((m["providerID"], m["id"]) for m in out)
    assert keys == [("openai", "gpt-4o"), ("opencode", "free-model-a")]


def test_known_session_models_returns_empty_when_db_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path / "missing"))
    assert sess.known_session_models() == []


def _fake_models_cache(tmp_path: Path, data: dict) -> Path:
    """Write a fake models.json cache and return its path."""
    cache = tmp_path / "models.json"
    cache.write_text(json.dumps(data), encoding="utf-8")
    return cache


def test_configured_models_reads_cache(tmp_path, monkeypatch):
    """configured_models() reads opencode's cached models.json."""
    fake_data = {
        "opencode": {
            "name": "OpenCode",
            "models": {
                "big-pickle": {
                    "id": "big-pickle",
                    "providerID": "opencode",
                    "name": "Big Pickle",
                },
                "longcat-2.0-free": {
                    "id": "longcat-2.0-free",
                    "providerID": "opencode",
                    "name": "Longcat",
                },
            },
        },
        "opencode-go": {
            "name": "OpenCode Go",
            "models": {
                "qwen3.8-max": {
                    "id": "qwen3.8-max",
                    "providerID": "opencode-go",
                    "name": "Qwen",
                },
            },
        },
    }
    cache_path = _fake_models_cache(tmp_path, fake_data)
    monkeypatch.setenv("OPENCODE_MODELS_PATH", str(cache_path))

    out = sess.configured_models()
    assert len(out) == 3
    # All three have no cost field (defaults to 0), so all are "free"
    # Free tier sorts first; within same tier, opencode* providers come first
    # opencode has 2 models, opencode-go has 1
    providers = [m["providerID"] for m in out]
    assert providers == ["opencode", "opencode", "opencode-go"]
    # All should have cost fields added by the parser
    for m in out:
        assert "cost_input" in m
        assert "cost_output" in m
        assert m["cost_input"] == 0
        assert m["cost_output"] == 0


def test_configured_models_filters_to_configured_providers(tmp_path, monkeypatch):
    """Only shows models from providers the user has configured."""
    fake_data = {
        "openai": {
            "models": {"gpt-4o": {"id": "gpt-4o", "providerID": "openai"}},
        },
        "opencode": {
            "models": {"longcat": {"id": "longcat", "providerID": "opencode"}},
        },
        "anthropic": {
            "models": {"claude": {"id": "claude", "providerID": "anthropic"}},
        },
    }
    cache_path = _fake_models_cache(tmp_path, fake_data)
    monkeypatch.setenv("OPENCODE_MODELS_PATH", str(cache_path))
    # Only opencode and anthropic are configured (opencode is always included)
    monkeypatch.setattr(sess, "configured_providers", lambda: {"opencode", "anthropic"})

    out = sess.configured_models()
    providers = [m["providerID"] for m in out]
    # opencode first (starts with "opencode"), then anthropic alphabetically
    assert providers == ["opencode", "anthropic"]
    assert len(out) == 2


def test_configured_models_shows_nothing_when_only_unconfigured(tmp_path, monkeypatch):
    """Returns [] when cache only has unconfigured providers."""
    fake_data = {
        "openai": {
            "models": {"gpt-4o": {"id": "gpt-4o", "providerID": "openai"}},
        },
        "anthropic": {
            "models": {"claude": {"id": "claude", "providerID": "anthropic"}},
        },
    }
    cache_path = _fake_models_cache(tmp_path, fake_data)
    monkeypatch.setenv("OPENCODE_MODELS_PATH", str(cache_path))
    # Neither provider is configured
    monkeypatch.setattr(sess, "configured_providers", lambda: {"opencode"})

    out = sess.configured_models()
    assert out == []


def test_configured_providers_reads_auth_json(tmp_path, monkeypatch):
    """configured_providers() reads provider IDs from auth.json."""
    auth_data = {
        "opencode-go": {"type": "api_key", "key": "fake123"},
        "openai": {"type": "oauth"},
    }
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps(auth_data), encoding="utf-8")
    monkeypatch.setattr(sess, "_auth_path", lambda: auth_file)

    providers = sess.configured_providers()
    assert providers == {"opencode", "opencode-go", "openai"}


def test_configured_providers_default_opencode_only(tmp_path, monkeypatch):
    """Always includes opencode even with no auth.json."""
    monkeypatch.setattr(sess, "_auth_path", lambda: None)

    providers = sess.configured_providers()
    assert providers == {"opencode"}


def test_configured_models_returns_empty_when_cache_missing(tmp_path, monkeypatch):
    """Returns [] if the cache file doesn't exist."""
    monkeypatch.setenv(
        "OPENCODE_MODELS_PATH", str(tmp_path / "nonexistent" / "models.json")
    )
    assert sess.configured_models() == []


def test_configured_models_returns_empty_on_bad_json(tmp_path, monkeypatch):
    """Returns [] if the cache file contains invalid JSON."""
    cache = tmp_path / "models.json"
    cache.write_text("not valid json {{{", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_MODELS_PATH", str(cache))
    assert sess.configured_models() == []


def test_configured_models_handles_entry_without_id_field(tmp_path, monkeypatch):
    """An entry missing 'id' falls back to the dict key as the model id."""
    fake_data = {
        "opencode": {
            "models": {
                "good": {"id": "good", "providerID": "opencode", "name": "Good"},
                "weird-entry": {"providerID": "opencode", "name": "No explicit id"},
            },
        },
    }
    cache_path = _fake_models_cache(tmp_path, fake_data)
    monkeypatch.setenv("OPENCODE_MODELS_PATH", str(cache_path))

    out = sess.configured_models()
    ids = {m["id"] for m in out}
    assert "good" in ids
    # Missing "id" field falls back to the dict key
    assert "weird-entry" in ids


def test_models_cache_path_uses_platformdirs(tmp_path, monkeypatch):
    """_models_cache_path() resolves via platformdirs when env var unset."""
    monkeypatch.delenv("OPENCODE_MODELS_PATH", raising=False)
    # Override XDG_CACHE_HOME so we don't pollute the real user cache
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    from platformdirs import user_cache_path

    platform_cache = user_cache_path("opencode", ensure_exists=True)
    models_file = Path(platform_cache) / "models.json"
    models_file.write_text(
        '{"opencode": {"models": {"m": {"id": "m", "providerID": "opencode"}}}}'
    )

    result = sess._models_cache_path()
    assert result == models_file
    assert result.is_file()


def test_models_cache_path_fallback_without_platformdirs(tmp_path, monkeypatch):
    """Falls back to XDG ~/.cache/opencode/ when platformdirs unavailable."""
    monkeypatch.delenv("OPENCODE_MODELS_PATH", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    cache_file = tmp_path / "opencode" / "models.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{}")

    # Simulate platformdirs not installed
    import sys as _sys

    real_import = (
        __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
    )

    def mock_import(name, *args, **kwargs):
        if name == "platformdirs":
            raise ImportError("No module named 'platformdirs'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setitem(sys.modules, "platformdirs", None)
    monkeypatch.setattr("builtins.__import__", mock_import)
    try:
        result = sess._models_cache_path()
        assert result == cache_file
    finally:
        monkeypatch.undo()


def test_models_cache_path_env_override(tmp_path, monkeypatch):
    """$OPENCODE_MODELS_PATH takes precedence over platform detection."""
    custom = tmp_path / "custom_models.json"
    custom.write_text(
        '{"opencode": {"models": {"x": {"id": "x", "providerID": "opencode"}}}}'
    )
    monkeypatch.setenv("OPENCODE_MODELS_PATH", str(custom))

    result = sess._models_cache_path()
    assert result == custom
