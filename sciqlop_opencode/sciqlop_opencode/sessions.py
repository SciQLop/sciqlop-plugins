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
    try:
        project_dirs = list(root.iterdir())
    except OSError:
        return []
    for project_dir in project_dirs:
        if not project_dir.is_dir():
            continue
        try:
            paths = list(project_dir.iterdir())
        except OSError:
            continue
        for path in paths:
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


def load_session_messages(
    session_id: str,
    image_tempdir: Optional[Path] = None,
):
    """Replay a session's message files into a list of `ChatMessage`."""
    from SciQLop.components.agents.chat import ChatMessage, ImageBlock, TextBlock, write_b64_image

    msg_dir = _storage_root() / "message" / session_id
    if not msg_dir.is_dir():
        return []

    tempdir = Path(image_tempdir) if image_tempdir else None
    if tempdir is not None:
        tempdir.mkdir(parents=True, exist_ok=True)

    try:
        files = sorted(p for p in msg_dir.iterdir() if p.suffix == ".json" and p.is_file())
    except OSError:
        return []

    messages: list = []
    for path in files:
        record = _read_message_record(path)
        if record is None:
            continue
        role = record.get("role")
        if role not in ("user", "assistant"):
            continue
        blocks = _render_blocks(record.get("content"), tempdir, TextBlock, ImageBlock, write_b64_image)
        if not blocks:
            continue
        if messages and messages[-1].role == role:
            messages[-1].blocks.extend(blocks)
        else:
            messages.append(ChatMessage(role=role, blocks=blocks, done=True))
    return messages


def _read_message_record(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _render_blocks(content, tempdir, TextBlock, ImageBlock, write_b64_image):
    if isinstance(content, str):
        return [TextBlock(text=content)] if content.strip() else []
    if not isinstance(content, list):
        return []
    out = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text") or ""
            if text.strip():
                out.append(TextBlock(text=text))
        elif btype == "image":
            path = _decode_image(block, tempdir, write_b64_image)
            if path:
                out.append(ImageBlock(path=path))
        elif btype == "tool_result":
            inner = block.get("content")
            if isinstance(inner, list):
                for item in inner:
                    if isinstance(item, dict) and item.get("type") == "image":
                        p = _decode_image(item, tempdir, write_b64_image)
                        if p:
                            out.append(ImageBlock(path=p))
    return out


def _decode_image(block: dict, tempdir, write_b64_image) -> Optional[str]:
    if tempdir is None:
        return None
    source = block.get("source") if isinstance(block.get("source"), dict) else block
    mime = source.get("mediaType") or source.get("media_type") or source.get("mimeType") or "image/png"
    return write_b64_image(source.get("data"), mime, tempdir, prefix="replay")
