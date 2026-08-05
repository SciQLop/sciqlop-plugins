"""Kimi session discovery and transcript loading (workspace-scoped).

kimi-cli persists one directory per session under its share dir, keyed by
work directory: ``context.jsonl`` (model history) and ``wire.jsonl`` (the
UI-level event log). We rebuild chat transcripts from ``wire.jsonl`` since it
carries exactly what the user saw: turns, text/think deltas, tool calls and
tool results.

Also hosts the small pure helpers shared with the backend (tool-argument
parsing, tool-result splitting) so `backend.py` can import them from here —
the reverse import would be circular.
"""
from __future__ import annotations

import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, List, Optional, Tuple

from SciQLop.components.agents import SessionEntry
from SciQLop.components.agents.chat import (
    ChatMessage,
    ImageBlock,
    TextBlock,
    ThinkingBlock,
    ToolActivityBlock,
    write_b64_image,
)


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


def parse_tool_args(arguments: Any) -> dict:
    """ToolCall.function.arguments is a JSON string (or already a dict)."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str) and arguments.strip():
        try:
            parsed = json.loads(arguments)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def parse_data_uri(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Split a ``data:<mime>;base64,<data>`` URI into (mime, data)."""
    if not isinstance(url, str) or not url.startswith("data:"):
        return None, None
    header, _, data = url.partition(",")
    if not data:
        return None, None
    mime = header[len("data:"):].split(";")[0] or "image/png"
    return mime, data


def split_tool_output(return_value: Any) -> Tuple[str, List[str]]:
    """Extract (text, image data-URIs) from a ToolOk/ToolError return value."""
    output = getattr(return_value, "output", "")
    is_error = getattr(return_value, "is_error", False)
    message = getattr(return_value, "message", "") or ""
    texts: List[str] = []
    images: List[str] = []
    if isinstance(output, str):
        if output:
            texts.append(output)
    elif isinstance(output, list):
        for part in output:
            text = getattr(part, "text", None)
            if text is not None:
                texts.append(text)
                continue
            image_url = getattr(part, "image_url", None)
            url = getattr(image_url, "url", None) if image_url is not None else None
            if url:
                images.append(url)
    if is_error and message:
        texts.append(message)
    return "\n".join(t for t in texts if t), images


def _run_async(coro_factory, timeout: float = 10.0):
    """Run a coroutine from sync code while qasync's loop is already running.

    Plugin entry points are called on SciQLop's GUI thread, so asyncio.run()
    here would raise "cannot be called from a running event loop" — use a
    worker thread with its own loop instead.
    """
    def _blocking():
        return asyncio.run(asyncio.wait_for(coro_factory(), timeout=timeout))

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_blocking).result(timeout=timeout + 2.0)


def _find_session(session_id: str):
    from kaos.path import KaosPath
    from kimi_cli.session import Session as CliSession

    work_dir = KaosPath(str(current_workspace_dir()))

    async def _find():
        return await CliSession.find(work_dir, session_id)

    try:
        return _run_async(_find)
    except Exception:
        return None


def list_sessions() -> List[SessionEntry]:
    from kaos.path import KaosPath
    from kimi_cli.session import Session as CliSession

    work_dir = KaosPath(str(current_workspace_dir()))

    async def _list():
        return await CliSession.list(work_dir)

    try:
        sessions = _run_async(_list)
    except Exception:
        return []
    return [
        SessionEntry(id=s.id, label=s.title or s.id, mtime=s.updated_at)
        for s in sessions
    ]


def _user_text(user_input: Any) -> str:
    if isinstance(user_input, str):
        return user_input
    if isinstance(user_input, list):
        return " ".join(
            part.text for part in user_input
            if getattr(part, "text", None) is not None
        )
    return str(user_input)


def load_session_messages(session_id: str, image_tempdir: Path) -> List[ChatMessage]:
    from kimi_agent_sdk import TextPart, ThinkPart, ToolCall, ToolResult, TurnBegin, TurnEnd
    from kimi_cli.wire.file import WireMessageRecord

    session = _find_session(session_id)
    if session is None:
        return []
    wire_path = session.wire_file.path
    if not wire_path.exists():
        return []

    messages: List[ChatMessage] = []
    current: Optional[ChatMessage] = None  # assistant message being built

    def assistant() -> ChatMessage:
        nonlocal current
        if current is None:
            current = ChatMessage(role="assistant", blocks=[], done=False)
            messages.append(current)
        return current

    def close_current() -> None:
        nonlocal current
        if current is not None:
            for block in current.blocks:
                if isinstance(block, (TextBlock, ThinkingBlock)):
                    block.complete = True
            current.done = True
        current = None

    def append_delta(cls, text: str) -> None:
        msg = assistant()
        last = msg.blocks[-1] if msg.blocks else None
        if type(last) is cls and not last.complete:
            last.text += text
        else:
            msg.blocks.append(cls(text=text, complete=False))

    with open(wire_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                wire_msg = WireMessageRecord.model_validate_json(line).to_wire_message()
            except Exception:
                continue  # metadata header line, or a record from a newer protocol
            if isinstance(wire_msg, TurnBegin):
                close_current()
                messages.append(ChatMessage(
                    role="user",
                    blocks=[TextBlock(text=_user_text(wire_msg.user_input), complete=True)],
                    done=True,
                ))
            elif isinstance(wire_msg, TextPart):
                append_delta(TextBlock, wire_msg.text)
            elif isinstance(wire_msg, ThinkPart):
                append_delta(ThinkingBlock, wire_msg.think)
            elif isinstance(wire_msg, ToolCall):
                fn = wire_msg.function
                assistant().blocks.append(ToolActivityBlock(
                    tool_name=getattr(fn, "name", "") or "",
                    tool_input=parse_tool_args(getattr(fn, "arguments", None)),
                    tool_use_id=wire_msg.id or "",
                ))
            elif isinstance(wire_msg, ToolResult):
                text, images = split_tool_output(wire_msg.return_value)
                for msg in reversed(messages):
                    match = next(
                        (b for b in msg.blocks
                         if isinstance(b, ToolActivityBlock)
                         and b.tool_use_id == wire_msg.tool_call_id),
                        None,
                    )
                    if match is not None:
                        match.result = text
                        break
                for url in images:
                    mime, data = parse_data_uri(url)
                    if not data:
                        continue
                    path = write_b64_image(data, mime or "image/png", Path(image_tempdir), prefix="tool")
                    if path:
                        assistant().blocks.append(ImageBlock(path=path))
            elif isinstance(wire_msg, TurnEnd):
                close_current()
    close_current()
    return messages
