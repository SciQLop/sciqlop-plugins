"""Session enumeration: complete by default, ordered most-recent-first.

SciQLop keeps sessions the user renamed or grouped however old they are, so the
listing must not silently drop the tail before SciQLop ever sees it.
"""
import json
import os


def _write_session(directory, name, text, mtime):
    path = directory / f"{name}.jsonl"
    path.write_text(json.dumps({
        "type": "user",
        "message": {"role": "user", "content": text},
    }) + "\n")
    os.utime(path, (mtime, mtime))
    return path


def _project_dir(tmp_path, monkeypatch):
    from sciqlop_claude import sessions

    cwd = tmp_path / "workspace"
    cwd.mkdir()
    projects = tmp_path / "projects"
    monkeypatch.setattr(sessions, "_projects_dir", lambda: projects)
    (projects / sessions._mangle_cwd(cwd.resolve())).mkdir(parents=True)
    return cwd, projects / sessions._mangle_cwd(cwd.resolve())


def test_lists_every_session_by_default(tmp_path, monkeypatch):
    from sciqlop_claude import sessions

    cwd, directory = _project_dir(tmp_path, monkeypatch)
    for i in range(45):
        _write_session(directory, f"id{i:02d}", f"question {i}", 1000.0 + i)

    listed = sessions.list_sessions(cwd)
    assert len(listed) == 45
    assert [e.session_id for e in listed[:3]] == ["id44", "id43", "id42"]
    assert listed[0].label == "question 44"


def test_limit_keeps_the_most_recent_only(tmp_path, monkeypatch):
    from sciqlop_claude import sessions

    cwd, directory = _project_dir(tmp_path, monkeypatch)
    for i in range(5):
        _write_session(directory, f"id{i}", f"question {i}", 1000.0 + i)

    listed = sessions.list_sessions(cwd, limit=2)
    assert [e.session_id for e in listed] == ["id4", "id3"]


def test_missing_project_directory_lists_nothing(tmp_path, monkeypatch):
    from sciqlop_claude import sessions

    monkeypatch.setattr(sessions, "_projects_dir", lambda: tmp_path / "nope")
    assert sessions.list_sessions(tmp_path) == []
