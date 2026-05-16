"""Enumerate prior opencode sessions stored on disk.

opencode persists each session as
`${OPENCODE_DATA_DIR:-~/.local/share/opencode}/storage/session/<projectHash>/<sessionID>.json`
and per-message content under `storage/message/<sessionID>/msg_*.json`.

We list sessions whose `cwd` matches the current SciQLop workspace and
extract a short label for the resume dropdown.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def current_workspace_dir() -> Path:
    try:
        from SciQLop.components.workspaces import workspaces_manager_instance
        mgr = workspaces_manager_instance()
        ws = getattr(mgr, "workspace", None)
        wdir = getattr(ws, "workspace_dir", None) if ws is not None else None
        if wdir:
            return Path(wdir).resolve()
    except Exception:
        pass
    env = os.environ.get("SCIQLOP_WORKSPACE_DIR")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


@dataclass
class SessionEntry:
    session_id: str
    path: Path
    mtime: float
    label: str


def _storage_root() -> Path:
    env = os.environ.get("OPENCODE_DATA_DIR")
    if env:
        return Path(env).expanduser() / "storage"
    return Path.home() / ".local" / "share" / "opencode" / "storage"


def _session_root() -> Path:
    return _storage_root() / "session"


def list_sessions(limit: int = 50) -> List[SessionEntry]:
    workspace = str(current_workspace_dir())
    root = _session_root()
    if not root.is_dir():
        return []

    entries: List[SessionEntry] = []
    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        for path in project_dir.iterdir():
            if path.suffix != ".json" or not path.is_file():
                continue
            entry = _read_session_entry(path, workspace)
            if entry is not None:
                entries.append(entry)
    entries.sort(key=lambda e: e.mtime, reverse=True)
    return entries[:limit]


def _read_session_entry(path: Path, workspace: str) -> Optional[SessionEntry]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd != workspace:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    label = _label_from_session(data) or "(empty session)"
    return SessionEntry(session_id=path.stem, path=path, mtime=mtime, label=label)


def _label_from_session(data: dict) -> Optional[str]:
    for key in ("label", "title", "name"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return _shorten(v.strip())
    return None


def _shorten(text: str, max_len: int = 80) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) > max_len:
        return collapsed[: max_len - 1] + "…"
    return collapsed
