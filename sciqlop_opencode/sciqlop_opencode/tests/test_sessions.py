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
