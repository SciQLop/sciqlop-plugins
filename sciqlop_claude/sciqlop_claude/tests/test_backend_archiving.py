"""The backend exposes the archiving hooks SciQLop probes for, and restores on resume."""
import asyncio


def _backend():
    from sciqlop_claude.backend import ClaudeBackend

    return ClaudeBackend.__new__(ClaudeBackend)


def test_archive_and_delete_reach_the_session_store(monkeypatch):
    from sciqlop_claude import backend as be

    seen = {}
    monkeypatch.setattr(be._sessions, "archive_sessions",
                        lambda ids: seen.setdefault("archived", list(ids)))
    monkeypatch.setattr(be._sessions, "delete_session",
                        lambda sid: seen.setdefault("deleted", sid))

    backend = _backend()
    backend.archive_sessions(["a", "b"])
    backend.delete_session("a")

    assert seen == {"archived": ["a", "b"], "deleted": "a"}


def test_resume_restores_the_archived_transcript_first(monkeypatch):
    from sciqlop_claude import backend as be

    restored = []
    monkeypatch.setattr(be._sessions, "restore_session", restored.append)

    backend = _backend()
    backend._lock = asyncio.Lock()
    backend._client = None
    backend._resume = None
    backend._slash_cache = ["/stale"]
    asyncio.run(backend.resume("kept"))

    assert restored == ["kept"]
    assert backend._resume == "kept"
    assert backend._slash_cache is None
