"""Enumerate prior Claude Code sessions stored on disk.

The CLI persists each session as `~/.claude/projects/<cwd-mangled>/<session-id>.jsonl`.
We list the ones matching the current working directory and extract a short
label (first real user message) so the dock can offer a resume dropdown.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence

from SciQLop.components.agents.chat import ThinkingBlock, write_b64_image


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
    "<task-notification",
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


def _archive_root() -> Path:
    override = os.environ.get("SCIQLOP_AGENT_ARCHIVE_DIR")
    if override:
        return Path(override)
    return Path(
        os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
    ) / "sciqlop" / "agent-sessions" / "claude"


def _archive_dir(cwd: Optional[Path] = None) -> Path:
    """Where transcripts SciQLop was told to keep live, mirroring the CLI layout."""
    resolved = Path(cwd).resolve() if cwd is not None else current_workspace_dir()
    return _archive_root() / _mangle_cwd(resolved)


def _transcripts(directory: Path) -> List[tuple[float, Path]]:
    found: List[tuple[float, Path]] = []
    try:
        with os.scandir(directory) as it:
            for entry in it:
                if not entry.name.endswith(".jsonl") or not entry.is_file():
                    continue
                try:
                    found.append((entry.stat().st_mtime, Path(entry.path)))
                except OSError:
                    continue
    except FileNotFoundError:
        pass
    return found


def list_sessions(cwd: Optional[Path] = None,
                  limit: Optional[int] = None) -> List[SessionEntry]:
    """Every session for `cwd`, most recent first; `limit` truncates the tail.

    Listing is complete by default: SciQLop keeps sessions the user renamed or
    grouped indefinitely, and a truncation here would hide them before it can
    decide. Labelling all of them costs a partial read each — ~0.03s for 200
    sessions, so there is nothing to save by cutting the list short.

    Archived transcripts are listed alongside the live ones, so a session the
    CLI has since pruned stays available; a live copy always wins.
    """
    live = _transcripts(_session_dir(cwd))
    known = {path.stem for _mtime, path in live}
    archived = [(mtime, path) for mtime, path in _transcripts(_archive_dir(cwd))
                if path.stem not in known]
    found = sorted(live + archived, key=lambda t: t[0], reverse=True)
    return [
        SessionEntry(
            session_id=path.stem,
            path=path,
            mtime=mtime,
            label=_extract_label(path),
        )
        for mtime, path in (found[:limit] if limit is not None else found)
    ]


def archive_sessions(session_ids: Sequence[str], cwd: Optional[Path] = None) -> None:
    """Keep these transcripts beyond the CLI's own `cleanupPeriodDays` pruning.

    Idempotent and additive — an id absent from a later call keeps its copy,
    since un-naming a session is not a request to destroy its transcript.
    """
    source_dir, target_dir = _session_dir(cwd), _archive_dir(cwd)
    for session_id in session_ids:
        source = source_dir / f"{session_id}.jsonl"
        if not source.is_file():
            continue
        target = target_dir / source.name
        if _same_content(source, target):
            continue
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        except OSError:
            continue


def _same_content(source: Path, target: Path) -> bool:
    try:
        a, b = source.stat(), target.stat()
    except OSError:
        return False
    return (a.st_size, int(a.st_mtime)) == (b.st_size, int(b.st_mtime))


def _transcript_path(session_id: str, cwd: Optional[Path] = None) -> Path:
    """The live transcript, or the archived copy once the CLI has pruned it."""
    live = _session_dir(cwd) / f"{session_id}.jsonl"
    archived = _archive_dir(cwd) / f"{session_id}.jsonl"
    return live if live.is_file() or not archived.is_file() else archived


def restore_session(session_id: str, cwd: Optional[Path] = None) -> bool:
    """Put an archived transcript back where the CLI expects it, so it resumes.

    A live transcript is never overwritten: it is the newer of the two.
    """
    target = _session_dir(cwd) / f"{session_id}.jsonl"
    if target.is_file():
        return True
    source = _archive_dir(cwd) / f"{session_id}.jsonl"
    if not source.is_file():
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    except OSError:
        return False
    return True


def delete_session(session_id: str, cwd: Optional[Path] = None) -> None:
    """Erase a session for good — live transcript and archived copy alike."""
    for directory in (_session_dir(cwd), _archive_dir(cwd)):
        try:
            (directory / f"{session_id}.jsonl").unlink()
        except OSError:
            pass


def load_session_messages(
    session_id: str,
    cwd: Optional[Path] = None,
    image_tempdir: Optional[Path] = None,
):
    """Replay a session's JSONL into a list of `ChatMessage` matching the live UI."""
    from SciQLop.components.agents.chat import (
        ChatMessage,
        ImageBlock,
        TextBlock,
        ToolActivityBlock,
    )

    path = _transcript_path(session_id, cwd)
    tempdir = Path(image_tempdir) if image_tempdir else None
    if tempdir is not None:
        tempdir.mkdir(parents=True, exist_ok=True)

    messages: list = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                _append_record(line, messages, tempdir, ChatMessage, TextBlock,
                               ImageBlock, ToolActivityBlock)
    except OSError:
        return []
    return [m for m in messages if m.blocks]


def _append_record(line, messages, tempdir, ChatMessage, TextBlock, ImageBlock,
                   ToolActivityBlock):
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
    if kind == "user" and _is_tool_result_only(content):
        # Handled before the empty-blocks early return: a text-only tool
        # result renders no blocks of its own but still fills the matching
        # activity block's result summary.
        target = _last_assistant(messages)
        if target is not None:
            target.blocks.extend(
                _render_blocks(content, tempdir, TextBlock, ImageBlock,
                               ToolActivityBlock))
            _attach_tool_results(content, target, ToolActivityBlock)
            return
    blocks = _render_blocks(content, tempdir, TextBlock, ImageBlock, ToolActivityBlock)
    if not blocks:
        return

    if kind == "user" and _is_tool_result_only(content):
        messages.append(ChatMessage(role="assistant", blocks=blocks, done=True))
        return

    if kind == "user" and _should_skip_user_text(blocks, TextBlock):
        return

    if messages and messages[-1].role == kind:
        messages[-1].blocks.extend(blocks)
        return
    messages.append(ChatMessage(role=kind, blocks=blocks, done=True))


def _render_blocks(content, tempdir, TextBlock, ImageBlock, ToolActivityBlock):
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
        elif btype == "thinking":
            text = block.get("thinking") or ""
            if text.strip():
                blocks.append(ThinkingBlock(text=text))
        elif btype == "tool_use":
            blocks.append(ToolActivityBlock(
                tool_name=str(block.get("name") or "").split("__")[-1],
                tool_input=block.get("input") or {},
                tool_use_id=block.get("id") or "",
            ))
        elif btype == "tool_result":
            blocks.extend(_tool_result_images(block, tempdir, ImageBlock))
        elif btype == "image":
            path = _decode_image(block.get("source"), tempdir)
            if path:
                blocks.append(ImageBlock(path=path))
    return blocks


def _attach_tool_results(content, message, ToolActivityBlock) -> None:
    """Fill in each rendered tool call's result summary, correlated by id —
    the replay counterpart of the dock's live result-only block merge."""
    for block in content:
        tool_use_id = block.get("tool_use_id") or ""
        if not tool_use_id:
            continue
        summary = _tool_result_summary(block)
        if not summary:
            continue
        match = next(
            (b for b in message.blocks
             if isinstance(b, ToolActivityBlock) and b.tool_use_id == tool_use_id),
            None,
        )
        if match is not None:
            match.result = summary


def _tool_result_summary(block: dict) -> str:
    """A short one-line summary of a transcript tool_result, for the activity log."""
    content = block.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                elif item.get("type") == "image":
                    parts.append("[image]")
            elif isinstance(item, str):
                parts.append(item)
        text = " ".join(parts)
    else:
        text = ""
    text = " ".join(text.split())
    if block.get("is_error") and text:
        text = f"error: {text}"
    return text[:200]


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
                text = _strip_legacy_alignment(_first_user_text(line) or "")
                if not text:
                    continue
                stripped = text.strip()
                if stripped in _SKIP_EXACT or stripped.startswith(_SKIP_PREFIXES):
                    continue
                return _shorten(text)
    except OSError:
        pass
    return "(empty session)"


# Sessions from before SciQLop 0.13.1 carry SciQLop's old persona preamble as
# the user's first words. Matched by its first and last lines rather than
# imported from SciQLop: importing the agents package needs a QApplication.
_LEGACY_ALIGNMENT_HEAD = "You are an astrophysicist and expert Python developer assisting inside SciQLop.\n"
_LEGACY_ALIGNMENT_TAIL = "- Do not guess method names or internal module paths.\n"


def _strip_legacy_alignment(text: str) -> str:
    if not text.startswith(_LEGACY_ALIGNMENT_HEAD):
        return text
    end = text.find(_LEGACY_ALIGNMENT_TAIL)
    if end < 0:
        return text
    return text[end + len(_LEGACY_ALIGNMENT_TAIL):].lstrip("\n")


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
