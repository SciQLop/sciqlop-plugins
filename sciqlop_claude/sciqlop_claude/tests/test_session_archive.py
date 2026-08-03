"""Archived sessions outlive the CLI's own 30-day transcript cleanup."""
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


def _setup(tmp_path, monkeypatch):
    from sciqlop_claude import sessions

    cwd = tmp_path / "workspace"
    cwd.mkdir()
    projects = tmp_path / "projects"
    archive = tmp_path / "archive"
    monkeypatch.setattr(sessions, "_projects_dir", lambda: projects)
    monkeypatch.setattr(sessions, "_archive_root", lambda: archive)
    live = projects / sessions._mangle_cwd(cwd.resolve())
    live.mkdir(parents=True)
    return sessions, cwd, live


def test_archiving_copies_the_transcript_aside(tmp_path, monkeypatch):
    sessions, cwd, live = _setup(tmp_path, monkeypatch)
    _write_session(live, "kept", "hello", 1000.0)

    sessions.archive_sessions(["kept"], cwd)

    assert (sessions._archive_dir(cwd) / "kept.jsonl").is_file()


def test_an_archived_session_survives_cli_cleanup(tmp_path, monkeypatch):
    sessions, cwd, live = _setup(tmp_path, monkeypatch)
    path = _write_session(live, "kept", "magnetopause crossings", 1000.0)
    sessions.archive_sessions(["kept"], cwd)
    path.unlink()  # what `cleanupPeriodDays` does after 30 days

    listed = sessions.list_sessions(cwd)
    assert [e.session_id for e in listed] == ["kept"]
    assert listed[0].label == "magnetopause crossings"
    assert listed[0].mtime == 1000.0


def test_a_live_session_is_listed_once(tmp_path, monkeypatch):
    sessions, cwd, live = _setup(tmp_path, monkeypatch)
    _write_session(live, "kept", "hello", 1000.0)
    sessions.archive_sessions(["kept"], cwd)

    assert [e.session_id for e in sessions.list_sessions(cwd)] == ["kept"]


def test_archiving_refreshes_a_stale_copy(tmp_path, monkeypatch):
    sessions, cwd, live = _setup(tmp_path, monkeypatch)
    _write_session(live, "kept", "first", 1000.0)
    sessions.archive_sessions(["kept"], cwd)
    _write_session(live, "kept", "second turn", 2000.0)
    sessions.archive_sessions(["kept"], cwd)

    archived = sessions._archive_dir(cwd) / "kept.jsonl"
    assert "second turn" in archived.read_text()


def test_archiving_leaves_earlier_copies_alone(tmp_path, monkeypatch):
    """Un-naming a session is not a request to destroy its transcript."""
    sessions, cwd, live = _setup(tmp_path, monkeypatch)
    _write_session(live, "one", "a", 1000.0)
    _write_session(live, "two", "b", 2000.0)
    sessions.archive_sessions(["one", "two"], cwd)

    sessions.archive_sessions(["two"], cwd)

    assert (sessions._archive_dir(cwd) / "one.jsonl").is_file()


def test_archiving_an_unknown_session_is_a_no_op(tmp_path, monkeypatch):
    sessions, cwd, _live = _setup(tmp_path, monkeypatch)
    sessions.archive_sessions(["ghost"], cwd)
    assert sessions.list_sessions(cwd) == []


def test_delete_erases_live_and_archived_copies(tmp_path, monkeypatch):
    sessions, cwd, live = _setup(tmp_path, monkeypatch)
    _write_session(live, "kept", "hello", 1000.0)
    sessions.archive_sessions(["kept"], cwd)

    sessions.delete_session("kept", cwd)

    assert not (live / "kept.jsonl").exists()
    assert not (sessions._archive_dir(cwd) / "kept.jsonl").exists()
    assert sessions.list_sessions(cwd) == []


def test_restore_puts_an_archived_session_back_for_the_cli(tmp_path, monkeypatch):
    sessions, cwd, live = _setup(tmp_path, monkeypatch)
    path = _write_session(live, "kept", "hello", 1000.0)
    sessions.archive_sessions(["kept"], cwd)
    path.unlink()

    assert sessions.restore_session("kept", cwd) is True
    assert (live / "kept.jsonl").is_file()


def test_restore_never_overwrites_a_live_transcript(tmp_path, monkeypatch):
    sessions, cwd, live = _setup(tmp_path, monkeypatch)
    _write_session(live, "kept", "archived turn", 1000.0)
    sessions.archive_sessions(["kept"], cwd)
    _write_session(live, "kept", "newer live turn", 2000.0)

    sessions.restore_session("kept", cwd)

    assert "newer live turn" in (live / "kept.jsonl").read_text()


def test_restoring_an_unknown_session_reports_failure(tmp_path, monkeypatch):
    sessions, cwd, _live = _setup(tmp_path, monkeypatch)
    assert sessions.restore_session("ghost", cwd) is False
