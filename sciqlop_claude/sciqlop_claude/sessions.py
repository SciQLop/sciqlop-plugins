"""Enumerate prior Claude Code sessions stored on disk.

The CLI persists each session as `~/.claude/projects/<cwd-mangled>/<session-id>.jsonl`.
We list the ones matching the current working directory and extract a short
label (first real user message) so the dock can offer a resume dropdown.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from SciQLop.components.agents.chat import write_b64_image


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


_SKIP_PREFIXES = (
    "<local-command",
    "<command-",
    "<system-reminder",
    "<session-start-hook",
    "<user-prompt-submit-hook",
    "Caveat:",
)

_SKIP_EXACT = {"load memories"}


def _mangle_cwd(cwd: Path) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "-", str(cwd))


def _projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _session_dir(cwd: Optional[Path]) -> Path:
    resolved = Path(cwd).resolve() if cwd is not None else current_workspace_dir()
    return _projects_dir() / _mangle_cwd(resolved)


def list_sessions(cwd: Optional[Path] = None, limit: int = 30) -> List[SessionEntry]:
    stats: List[tuple[float, Path]] = []
    try:
        with os.scandir(_session_dir(cwd)) as it:
            for entry in it:
                if not entry.name.endswith(".jsonl") or not entry.is_file():
                    continue
                try:
                    stats.append((entry.stat().st_mtime, Path(entry.path)))
                except OSError:
                    continue
    except FileNotFoundError:
        return []
    stats.sort(key=lambda t: t[0], reverse=True)
    return [
        SessionEntry(
            session_id=path.stem,
            path=path,
            mtime=mtime,
            label=_extract_label(path),
        )
        for mtime, path in stats[:limit]
    ]


def load_session_messages(
    session_id: str,
    cwd: Optional[Path] = None,
    image_tempdir: Optional[Path] = None,
):
    """Replay a session's JSONL into a list of `ChatMessage` matching the live UI."""
    from SciQLop.components.agents.chat import ChatMessage, ImageBlock, TextBlock

    path = _session_dir(cwd) / f"{session_id}.jsonl"
    tempdir = Path(image_tempdir) if image_tempdir else None
    if tempdir is not None:
        tempdir.mkdir(parents=True, exist_ok=True)

    messages: list = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                _append_record(line, messages, tempdir, ChatMessage, TextBlock, ImageBlock)
    except OSError:
        return []
    return [m for m in messages if m.blocks]


def _append_record(line, messages, tempdir, ChatMessage, TextBlock, ImageBlock):
    try:
        record = json.loads(line)
    except ValueError:
        return
    kind = record.get("type")
    if kind not in ("user", "assistant"):
        return
    if record.get("isSidechain") or record.get("isMeta"):
        return
    content = (record.get("message") or {}).get("content")
    blocks = _render_blocks(content, tempdir, TextBlock, ImageBlock)
    if not blocks:
        return

    if kind == "user" and _is_tool_result_only(content):
        target = _last_assistant(messages)
        if target is not None:
            target.blocks.extend(blocks)
            return
        messages.append(ChatMessage(role="assistant", blocks=blocks, done=True))
        return

    if kind == "user" and _should_skip_user_text(blocks, TextBlock):
        return

    if messages and messages[-1].role == kind:
        messages[-1].blocks.extend(blocks)
        return
    messages.append(ChatMessage(role=kind, blocks=blocks, done=True))


def _render_blocks(content, tempdir, TextBlock, ImageBlock):
    if isinstance(content, str):
        return [TextBlock(text=content)] if content.strip() else []
    if not isinstance(content, list):
        return []
    blocks = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text") or ""
            if text.strip():
                blocks.append(TextBlock(text=text))
        elif btype == "tool_result":
            blocks.extend(_tool_result_images(block, tempdir, ImageBlock))
        elif btype == "image":
            path = _decode_image(block.get("source"), tempdir)
            if path:
                blocks.append(ImageBlock(path=path))
    return blocks


def _is_tool_result_only(content) -> bool:
    if not isinstance(content, list):
        return False
    has_any = False
    for block in content:
        if not isinstance(block, dict):
            continue
        has_any = True
        if block.get("type") != "tool_result":
            return False
    return has_any


def _last_assistant(messages):
    for msg in reversed(messages):
        if msg.role == "assistant":
            return msg
    return None


def _should_skip_user_text(blocks, TextBlock) -> bool:
    if not blocks:
        return True
    first = blocks[0]
    if not isinstance(first, TextBlock):
        return False
    stripped = first.text.strip()
    return stripped in _SKIP_EXACT or stripped.startswith(_SKIP_PREFIXES)


def _tool_result_images(block: dict, tempdir, ImageBlock):
    content = block.get("content")
    if not isinstance(content, list):
        return []
    out = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "image":
            continue
        # Tool results can either wrap the base64 payload under "source" (API
        # shape) or put data/mimeType at the top level (MCP shape). Accept both.
        path = _decode_image(item.get("source") or item, tempdir)
        if path:
            out.append(ImageBlock(path=path))
    return out


def _decode_image(source, tempdir) -> Optional[str]:
    if tempdir is None or not isinstance(source, dict):
        return None
    mime = source.get("media_type") or source.get("mimeType") or "image/png"
    return write_b64_image(source.get("data"), mime, tempdir, prefix="replay")


def _extract_label(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                text = _first_user_text(line)
                if not text:
                    continue
                stripped = text.strip()
                if stripped in _SKIP_EXACT or stripped.startswith(_SKIP_PREFIXES):
                    continue
                return _shorten(text)
    except OSError:
        pass
    return "(empty session)"


def _first_user_text(line: str) -> Optional[str]:
    try:
        record = json.loads(line)
    except ValueError:
        return None
    if record.get("type") != "user":
        return None
    if record.get("isMeta") or record.get("toolUseResult") is not None:
        return None
    if record.get("isSidechain"):
        return None
    message = record.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text") or ""
    return None


def _shorten(text: str, max_len: int = 80) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) > max_len:
        return collapsed[: max_len - 1] + "…"
    return collapsed
