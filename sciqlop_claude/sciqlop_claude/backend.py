"""Claude Agent SDK adapter — implements `SciQLop.components.agents.AgentBackend`."""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import AsyncIterator, Callable, List, Optional

from SciQLop.components.agents import BackendContext, SessionEntry
from SciQLop.components.agents.settings import AgentWriteMode
from SciQLop.components.agents.backend import (
    ContextCategory,
    Cost,
    Quota,
    StreamBlock,
    TokenCounts,
    UsageSnapshot,
)
from SciQLop.components.agents.chat import (
    ChatMessage,
    ImageBlock,
    TextBlock,
    ThinkingBlock,
    ToolActivityBlock,
    write_b64_image,
)
from SciQLop.components.agents.model_capabilities import capabilities_for

from . import sessions as _sessions

try:
    from claude_agent_sdk import (
        ClaudeAgentOptions,
        ClaudeSDKClient,
        create_sdk_mcp_server,
        tool as sdk_tool,
    )
    from claude_agent_sdk.types import (
        AssistantMessage,
        PermissionResultAllow,
        PermissionResultDeny,
        ToolResultBlock,
        UserMessage,
    )

    _SDK_AVAILABLE = True
    _SDK_IMPORT_ERROR: Optional[str] = None
except Exception as e:  # pragma: no cover
    _SDK_AVAILABLE = False
    _SDK_IMPORT_ERROR = str(e)


from SciQLop.components.sciqlop_logging import getLogger as _getLogger

_log = _getLogger("sciqlop_claude")


# claude_agent_sdk.types.EffortLevel, in ascending order. This is what the SDK
# will put on the wire; models.dev narrows it per model.
SDK_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")


def remember_session(backend, result) -> None:
    """Record the live session id so a reconnect resumes instead of starting over.

    Needed because effort can only be applied at connect time, so changing it
    forces a reconnect. Also hardens `set_model`'s error path, which drops the
    client on failure.
    """
    session_id = getattr(result, "session_id", None)
    if session_id:
        backend._resume = session_id


_MCP_SERVER_NAME = "sciqlop"

# claude_agent_sdk's stdio transport caps each newline-delimited JSON message at
# _DEFAULT_MAX_BUFFER_SIZE (1 MB). The CLI echoes tool results back over that
# transport, so a sciqlop_screenshot_* result (an inline base64 PNG) overflows it
# and aborts the session ("JSON message exceeded maximum buffer size"). Raise the
# ceiling to comfortably hold a full-window screenshot — bounded, so a single
# message can't grow without limit.
_MAX_BUFFER_SIZE = 64 * 1024 * 1024  # 64 MB

_DEFAULT_MODEL_CHOICES: List[tuple[str, Optional[str]]] = [
    ("Default (Claude Code)", None),
]


def fetch_models(timeout: float = 10.0) -> List[tuple[str, Optional[str]]]:
    """Fetch the live model list from the `claude` CLI.

    The CLI returns `{value, displayName, description}` per model via the
    initialize control request. We map `value == "default"` to `None` so the
    backend keeps its "no override" semantic.
    """
    if not _SDK_AVAILABLE or not claude_cli_available():
        return list(_DEFAULT_MODEL_CHOICES)

    async def _run() -> list:
        async with ClaudeSDKClient(
            options=ClaudeAgentOptions(cli_path=resolve_claude_executable())
        ) as client:
            info = await client.get_server_info() or {}
            return info.get("models") or []

    # Run in a worker thread with its own loop — plugin load happens while
    # SciQLop's qasync loop is already running, so asyncio.run() here would
    # raise "cannot be called from a running event loop".
    def _blocking() -> list:
        return asyncio.run(asyncio.wait_for(_run(), timeout=timeout))

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            raw = pool.submit(_blocking).result(timeout=timeout + 2.0)
    except Exception:
        return list(_DEFAULT_MODEL_CHOICES)

    choices: List[tuple[str, Optional[str]]] = []
    for m in raw:
        value = m.get("value")
        label = m.get("displayName") or value
        if not value or not label:
            continue
        choices.append((label, None if value == "default" else value))
    return choices or list(_DEFAULT_MODEL_CHOICES)


def _well_known_candidates() -> List[str]:
    """Install locations invisible to GUI-launched processes.

    macOS apps started from Finder/Dock inherit a minimal PATH without
    /opt/homebrew/bin or ~/.local/bin.
    """
    candidates = ["/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
    home = Path.home()
    for sub in (".local/bin/claude", "bin/claude"):
        candidates.append(str(home / sub))
    return candidates


def _shell_probe() -> Optional[str]:
    """Ask a login shell where claude is, for dotfile-only PATH entries.

    Bounded and last-resort: plugin load must never hang on this.
    """
    if os.name == "nt":
        return None
    for shell in ("/bin/zsh", "/bin/bash", "/bin/sh"):
        if not os.path.isfile(shell):
            continue
        try:
            proc = subprocess.run(
                [shell, "-lc", "which claude"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except Exception:
            continue
        for line in proc.stdout.splitlines():
            path = line.strip()
            if path and os.path.isfile(path):
                return path
    return None


def resolve_claude_executable() -> Optional[str]:
    """Absolute path to the claude binary, or None when not installed."""
    on_path = shutil.which("claude")
    if on_path is not None:
        return on_path
    for candidate in _well_known_candidates():
        if os.path.isfile(candidate) and (
            os.name == "nt" or os.access(candidate, os.X_OK)
        ):
            return candidate
    return _shell_probe()


def claude_cli_available() -> bool:
    return resolve_claude_executable() is not None


def sdk_available() -> tuple[bool, Optional[str]]:
    return _SDK_AVAILABLE, _SDK_IMPORT_ERROR


_INTERRUPT_DRAIN_TIMEOUT_S = 15.0
_CONTEXT_USAGE_TIMEOUT_S = 10.0

# Task statuses that mean a background task has finished. Mirrors the SDK's
# `TERMINAL_TASK_STATUSES`, kept local because the dependency pin still admits
# 0.1.x, which does not export it. Spans both lifecycle vocabularies:
# task_notification says "stopped" where task_updated says the raw "killed".
_TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "stopped", "killed"})


def _update_active_tasks(active: set, message) -> None:
    """Track background-task lifecycle so a turn knows when its tasks are done.

    A background ``Task``'s continuation is emitted on the shared message stream
    *after* the foreground ``ResultMessage``. Ending the turn at that first
    ResultMessage orphans the continuation into the next turn (a one-turn chat
    desync). We instead keep the turn open until every task it started reports a
    terminal status — which the SDK documents can arrive on *either* a
    TaskNotificationMessage or a TaskUpdatedMessage (whose status may sit inside
    `patch`). https://code.claude.com/docs/en/agent-sdk/python
    """
    name = type(message).__name__
    if name == "TaskStartedMessage":
        task_id = getattr(message, "task_id", None)
        if task_id:
            active.add(task_id)
    elif name in ("TaskUpdatedMessage", "TaskNotificationMessage"):
        status = getattr(message, "status", None)
        if status is None:  # TaskUpdatedMessage carries status inside `patch`
            patch = getattr(message, "patch", None)
            if isinstance(patch, dict):
                status = patch.get("status")
        if status in _TERMINAL_TASK_STATUSES:
            active.discard(getattr(message, "task_id", None))


class ClaudeBackend:
    display_name = "Claude"
    model_choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    supports_sessions = True
    # workspace AGENTS.md; class default keeps partially-built
    # instances (tests, __new__) renderable
    _guidance: str = ""

    def __init__(self, ctx: BackendContext):
        if not _SDK_AVAILABLE:
            raise RuntimeError(f"claude-agent-sdk not importable: {_SDK_IMPORT_ERROR}")
        self._main_window = ctx.main_window
        self._tools = ctx.tools
        self._gated_names = {t["name"] for t in ctx.tools if t.get("gated")}
        self._tempdir = Path(ctx.tempdir)
        self._tempdir.mkdir(parents=True, exist_ok=True)
        self._confirm_cb = ctx.confirm_cb
        self._ask_question_cb = getattr(ctx, "ask_question_cb", None)
        self._model: Optional[str] = None
        self._effort: Optional[str] = None
        self._write_mode = ctx.write_mode
        # tolerated missing: BackendContext gained `guidance` in SciQLop 0.13
        self._guidance = getattr(ctx, "guidance", "")
        self._resume: Optional[str] = None
        self._client: Optional[ClaudeSDKClient] = None
        self._lock = asyncio.Lock()
        self._slash_cache: Optional[List[str]] = None
        self._last_result = None
        # keyed by rate_limit_type so the 5-hour and weekly windows do not
        # overwrite each other. Deliberately NOT cleared by reset(): these
        # windows are account-wide, and starting a new chat does not refill them.
        self._rate_limits: dict = {}
        self._effort_dirty = False

    async def _ensure_client(self) -> ClaudeSDKClient:
        if self._client is not None:
            return self._client
        sdk_tools = [_wrap_tool(t) for t in self._tools]
        server = create_sdk_mcp_server(name=_MCP_SERVER_NAME, tools=sdk_tools)
        permission_gate_active = bool(self._confirm_cb or self._ask_question_cb)
        # allowed_tools auto-approves before can_use_tool is ever consulted, so
        # gated tools must stay out of it whenever the gate is actually wired —
        # otherwise _permission_check's write-action gate never runs for them.
        allowed = [
            f"mcp__{_MCP_SERVER_NAME}__{t['name']}"
            for t in self._tools
            if not (permission_gate_active and t.get("gated"))
        ]
        allowed += [
            "WebSearch",
            "WebFetch",
        ]  # built-in web search + page fetch (ungated)
        options = ClaudeAgentOptions(
            system_prompt=self._system_prompt(),
            mcp_servers={_MCP_SERVER_NAME: server},
            allowed_tools=allowed,
            can_use_tool=self._permission_check if permission_gate_active else None,
            model=self._model,
            effort=self._effort,
            resume=self._resume,
            cwd=str(_sessions.current_workspace_dir()),
            setting_sources=["user", "project"],
            max_buffer_size=_MAX_BUFFER_SIZE,
            cli_path=resolve_claude_executable(),
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        return self._client

    async def ask(
        self, prompt: str, image_paths: Optional[List[str]] = None
    ) -> AsyncIterator[StreamBlock]:
        async with self._lock:
            if self._effort_dirty:
                # a pending effort change only takes effect on a fresh client
                await self._disconnect()
                self._effort_dirty = False
            client = await self._ensure_client()
            await client.query(_build_user_stream(prompt, image_paths or []))
            async for message in self._receive_turn(client):
                _mtype = type(message).__name__
                if _mtype == "ResultMessage":
                    self._last_result = message
                    remember_session(self, message)
                elif _mtype == "RateLimitEvent":
                    info = getattr(message, "rate_limit_info", None)
                    kind = getattr(info, "rate_limit_type", None)
                    if kind:
                        self._rate_limits[kind] = info
                for block in self._decode_message(message):
                    yield block

    async def _receive_turn(self, client) -> AsyncIterator:
        """Yield one turn's messages, keeping the turn open until every
        background ``Task`` it spawned has finished.

        ``receive_response()`` stops at the first ``ResultMessage``, but a
        background task's continuation arrives on the shared stream *after* that
        result. Reading straight from ``receive_messages()`` and ending only on
        a ``ResultMessage`` reached with no task still active keeps that
        continuation in its own turn instead of leaking it into the next one.

        This must wait unconditionally, however long a background task takes:
        giving up doesn't stop the SDK subprocess, so an abandoned task's
        messages (including its own ``ResultMessage``) still land on the shared
        stream later, unread — and get misattributed to whichever turn happens
        to be listening next when they finally arrive, an even worse desync
        than the one this loop exists to prevent. A stuck task is instead the
        user's job to interrupt via Stop / ``cancel()``, which works
        independently of this wait (it does not take ``self._lock``).

        A second, subtler leak source: a fresh client that resumes a session
        with a *stale* background task (the previous client was killed while it
        ran) first reconciles that task on the stream — a
        ``TaskNotificationMessage`` followed by a bookkeeping CLI turn: ``init``
        then a ``ResultMessage`` with ``num_turns=0``, no cost and, crucially,
        no ``AssistantMessage``. Ending our turn at that phantom result shows an
        empty answer and pushes the real answer into the next turn — from then
        on every turn shows the previous turn's answer. Verified against the
        real CLI that legitimate content-free turns (slash commands such as
        /clear, /cost, /context) always carry an AssistantMessage, so a
        ``success`` result with no AssistantMessage since the last ``init`` is
        never the answer to the user's prompt: keep reading.
        """
        active_tasks: set = set()
        messages = client.receive_messages()
        assistant_seen = False  # since the last init (CLI turn boundary)
        while True:
            try:
                message = await messages.__anext__()
            except StopAsyncIteration:
                return
            _update_active_tasks(active_tasks, message)
            mtype = type(message).__name__
            if mtype == "AssistantMessage":
                assistant_seen = True
            elif (
                mtype == "SystemMessage" and getattr(message, "subtype", None) == "init"
            ):
                assistant_seen = False
            yield message
            if mtype == "ResultMessage" and not active_tasks:
                if getattr(message, "subtype", None) != "success" or assistant_seen:
                    return
                # phantom bookkeeping result — the real answer is still coming

    async def reset(self) -> None:
        async with self._lock:
            await self._disconnect()
            self._resume = None
            self._slash_cache = None
            self._last_result = None

    async def cancel(self) -> None:
        """Interrupt the in-flight turn.

        ``interrupt()`` must NOT wait on ``self._lock``: ``ask()`` holds that lock
        for the whole streamed turn, so acquiring it here would defer the interrupt
        until the turn ends on its own — Stop would do nothing mid-turn.
        """
        client = self._client
        if client is None:
            return
        interrupt = getattr(client, "interrupt", None)
        if interrupt is None:
            async with self._lock:
                await self._disconnect()
            return
        try:
            await interrupt()
        except Exception:
            async with self._lock:
                await self._disconnect()
            return
        # The interrupted turn drains its own error_during_execution ResultMessage
        # through its receive_response(). Only when nothing is consuming the stream
        # (no turn in flight) do we drain here, so the leftover can't leak into the
        # next query. https://code.claude.com/docs/en/agent-sdk/python
        if not self._lock.locked():
            async with self._lock:
                if self._client is client:
                    await self._drain_after_interrupt(client)

    async def _drain_after_interrupt(self, client) -> None:
        """Consume the interrupted task's leftover messages before the next query.

        ``interrupt()`` does not clear the message buffer: the interrupted task's
        messages — including its ResultMessage (subtype ``error_during_execution``)
        — stay in the stream and would otherwise be read as the *next* query's
        response, desyncing the chat. The bounded wait guards against an interrupt
        that left nothing to drain; on any failure we drop the client so the next
        turn reconnects clean. https://code.claude.com/docs/en/agent-sdk/python
        """

        async def _consume() -> None:
            async for _message in client.receive_response():
                pass

        try:
            await asyncio.wait_for(_consume(), timeout=_INTERRUPT_DRAIN_TIMEOUT_S)
        except Exception:
            await self._disconnect()

    async def resume(self, session_id: str) -> None:
        async with self._lock:
            await self._disconnect()
            # The CLI resumes from its own projects dir, so an archived
            # transcript has to be put back there before it can be reached.
            _sessions.restore_session(session_id)
            self._resume = session_id
            self._slash_cache = None

    async def _disconnect(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.disconnect()
        except Exception:
            pass
        self._client = None

    async def set_model(self, model: Optional[str]) -> None:
        async with self._lock:
            self._model = model
            if self._client is not None:
                try:
                    await self._client.set_model(model)
                except Exception:
                    await self._disconnect()

    def effort_values(self) -> tuple:
        """SDK-accepted levels, narrowed to what the selected model supports."""
        caps = capabilities_for("anthropic", self._model or "")
        if caps is None or not caps.effort_values:
            return SDK_EFFORT_LEVELS
        allowed = set(caps.effort_values)
        return tuple(level for level in SDK_EFFORT_LEVELS if level in allowed)

    async def set_effort(self, effort: Optional[str]) -> None:
        """Store and force a reconnect — the SDK has no live effort setter, so
        effort can only be applied through ClaudeAgentOptions at connect time.

        A no-op when `effort` already matches the stored value: without this
        guard, every backend switch or model change that restores a persisted
        effort would tear down and reconnect the client even though nothing
        actually changed.
        """
        async with self._lock:
            if effort == self._effort:
                return
            self._effort = effort
            # Deliberately does NOT drop a live client. Effort is only read when
            # ClaudeAgentOptions is built, so a client already up cannot honour
            # the new value anyway — and tearing it down here killed the very
            # connection the session-info strip reads context from, on every
            # bind that restored a persisted effort. Recreate lazily instead,
            # at the next turn, which is the first moment it can matter.
            self._effort_dirty = self._client is not None

    def set_write_mode(self, mode: str) -> None:
        self._write_mode = mode

    def _system_prompt(self) -> str:
        """Workspace guidance plus a write-mode header.

        `guidance` is the workspace `AGENTS.md` (SciQLop's managed block plus
        the user's own sections). The `claude` CLI also discovers that file
        from its cwd on its own, so this injection is belt-and-braces: it is
        unverified whether project-memory discovery still runs when the SDK
        passes an explicit `system_prompt=`. Drop it once that is confirmed —
        the cost of keeping it is one duplicated block, the cost of removing
        it blind is a silent loss of every rule the user wrote.
        """
        if self._write_mode == AgentWriteMode.NONE:
            write_intro = (
                "Write tools are currently disabled. Do not attempt to create "
                "panels, set time ranges, run Python, install packages, or edit "
                "notebooks."
            )
        elif self._write_mode == AgentWriteMode.YOLO:
            write_intro = (
                "Write tools are available and auto-approved (no per-call "
                "confirmation)."
            )
        else:
            write_intro = "Write tools are available and gated by per-call approval."
        return f"{self._guidance.strip()}\n\n{write_intro}".strip()

    async def list_slash_commands(self) -> List[str]:
        if self._slash_cache is not None:
            return self._slash_cache
        async with self._lock:
            if self._slash_cache is not None:
                return self._slash_cache
            client = await self._ensure_client()
            try:
                info = await client.get_server_info()
            except Exception:
                return []
            if not isinstance(info, dict):
                return []
            commands = info.get("commands") or []
            names: List[str] = []
            for c in commands:
                if isinstance(c, dict):
                    name = c.get("name")
                    if isinstance(name, str):
                        names.append("/" + name.lstrip("/"))
                elif isinstance(c, str):
                    names.append("/" + c.lstrip("/"))
            self._slash_cache = names
            return names

    def list_sessions(self) -> List[SessionEntry]:
        return [
            SessionEntry(id=s.session_id, label=s.label, mtime=s.mtime)
            for s in _sessions.list_sessions()
        ]

    def load_session(self, session_id: str, image_tempdir: Path) -> List[ChatMessage]:
        return _sessions.load_session_messages(session_id, image_tempdir=image_tempdir)

    def current_session_id(self) -> Optional[str]:
        """The id the CLI reported for the live session, recorded so a
        reconnect resumes it — which also makes it the one being written to."""
        return self._resume

    def archive_sessions(self, session_ids) -> None:
        _sessions.archive_sessions(session_ids)

    def delete_session(self, session_id: str) -> None:
        _sessions.delete_session(session_id)

    async def usage_snapshot(self) -> Optional[UsageSnapshot]:
        """Describe the session as it stands, not merely the last turn.

        Context is meaningful from the moment the client connects — the system
        prompt, the MCP tool schemas and CLAUDE.md files already occupy real
        budget before the user types anything, which is why Claude Code can show
        /context immediately. Returning None until a ResultMessage arrived kept
        the strip blank through the whole first turn.
        """
        snapshot = (
            result_to_usage(self._last_result)
            if self._last_result is not None
            else UsageSnapshot()
        )
        snapshot = replace(snapshot, quotas=rate_limits_to_quotas(self._rate_limits))
        client = self._client
        if client is None:
            return _reportable(snapshot)
        try:
            # bounded: this is a control request over the CLI's stdio
            # transport, and a client torn down mid-flight never answers. An
            # unbounded await wedges UsageRefresher, whose in-flight guard then
            # drops every later refresh — the strip stays blank permanently.
            payload = await asyncio.wait_for(
                client.get_context_usage(), timeout=_CONTEXT_USAGE_TIMEOUT_S
            )
            tokens, maximum, categories, model = context_to_breakdown(payload)
            if tokens is None:
                # The CLI answers this on a fresh connection (verified: ~38k of
                # 967k before any query), so an empty reply means something
                # about *this* connection, not a CLI limitation.
                _log.debug(
                    "context usage reply carried no totals: %r",
                    sorted(payload) if isinstance(payload, dict) else payload,
                )
        except Exception as error:
            # Expected before the first query on some CLI versions; log so a
            # persistently empty strip can be told apart from an empty session.
            _log.debug("context usage unavailable: %r", error)
            return _reportable(snapshot)
        return _reportable(
            replace(
                snapshot,
                context_tokens=tokens,
                context_max=maximum,
                context_categories=categories,
                # the resolved canonical name wins: /context reports whatever alias
                # the request carried, which is exactly what canonicalModel exists
                # to normalise away.
                model=snapshot.model or model,
            )
        )

    async def _answer_question(self, tool_input: dict):
        """Render the model's AskUserQuestion and return the user's answers.

        The SDK delivers AskUserQuestion through can_use_tool; the answers go
        back as updated_input. Without a wired UI callback we fall back to the
        default allow (the model then proceeds with its own defaults)."""
        questions = tool_input.get("questions", [])
        try:
            answers = await self._ask_question_cb(questions)
        except Exception as e:  # noqa: BLE001
            return PermissionResultDeny(message=f"question callback failed: {e}")
        return PermissionResultAllow(updated_input={**tool_input, "answers": answers})

    async def _permission_check(self, tool_name: str, tool_input: dict, context):
        short = tool_name.split("__")[-1]
        if short == "AskUserQuestion" and self._ask_question_cb is not None:
            return await self._answer_question(tool_input)
        if short not in self._gated_names:
            return PermissionResultAllow(updated_input=tool_input)
        if self._write_mode == AgentWriteMode.NONE:
            return PermissionResultDeny(
                message=(
                    "write actions are currently disabled — ask the user to "
                    "enable write mode in the SciQLop chat dock"
                )
            )
        if self._write_mode == AgentWriteMode.YOLO:
            return PermissionResultAllow(updated_input=tool_input)
        try:
            allowed = await self._confirm_cb(short, tool_input)
        except Exception as e:
            return PermissionResultDeny(message=f"approval callback failed: {e}")
        if allowed:
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message="user denied the tool call")

    def _decode_message(self, message) -> List[StreamBlock]:
        blocks: List[StreamBlock] = []
        if isinstance(message, AssistantMessage):
            for block in getattr(message, "content", []) or []:
                thinking = getattr(block, "thinking", None)
                if thinking:
                    blocks.append(ThinkingBlock(text=thinking, complete=True))
                    continue
                text = getattr(block, "text", None)
                if text:
                    blocks.append(TextBlock(text=text, complete=True))
                    continue
                name = getattr(block, "name", None)
                if name is not None:  # ToolUseBlock
                    blocks.append(
                        ToolActivityBlock(
                            tool_name=str(name).split("__")[-1],
                            tool_input=getattr(block, "input", {}) or {},
                            tool_use_id=getattr(block, "id", "") or "",
                        )
                    )
            return blocks
        if isinstance(message, UserMessage):
            for block in _iter_tool_results(message):
                blocks.extend(self._tool_result_blocks(block))
                summary = _result_summary(block)
                if summary:
                    blocks.append(
                        ToolActivityBlock(
                            tool_use_id=getattr(block, "tool_use_id", "") or "",
                            result=summary,
                        )
                    )
        return blocks

    def _tool_result_blocks(self, block) -> List[StreamBlock]:
        out: List[StreamBlock] = []
        content = getattr(block, "content", None)
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "image":
                    path = write_b64_image(
                        item.get("data"),
                        item.get("mimeType", "image/png"),
                        self._tempdir,
                        prefix="tool",
                    )
                    if path:
                        out.append(ImageBlock(path=path))
        return out


def _iter_tool_results(message) -> list:
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, ToolResultBlock)]


def _result_summary(block) -> str:
    """A short one-line summary of a tool result, for the activity log."""
    content = getattr(block, "content", None)
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
            else:
                t = getattr(item, "text", None)
                if t:
                    parts.append(str(t))
        text = " ".join(parts)
    else:
        text = ""
    text = " ".join(str(text).split())
    if getattr(block, "is_error", False) and text:
        text = f"error: {text}"
    return text[:200]


def result_to_usage(result) -> "UsageSnapshot":
    """Map a ResultMessage into a UsageSnapshot. Pure — no client needed."""
    raw = getattr(result, "usage", None) or {}
    tokens = TokenCounts(
        input=raw.get("input_tokens"),
        output=raw.get("output_tokens"),
        cache_read=raw.get("cache_read_input_tokens"),
        cache_write=raw.get("cache_creation_input_tokens"),
    )
    cost_usd = getattr(result, "total_cost_usd", None)
    return UsageSnapshot(
        model=_display_model(result),
        tokens=tokens,
        cost=Cost(amount=cost_usd) if cost_usd is not None else None,
        num_turns=getattr(result, "num_turns", None),
        duration_api_ms=getattr(result, "duration_api_ms", None),
        session_id=getattr(result, "session_id", None),
    )


def _display_model(result) -> Optional[str]:
    """Prefer `model_usage[...].canonicalModel` — a stable resolved name that
    survives provider-specific aliases (claude-agent-sdk >= 0.2.126)."""
    model_usage = getattr(result, "model_usage", None) or {}
    for entry in model_usage.values():
        if isinstance(entry, dict) and entry.get("canonicalModel"):
            return entry["canonicalModel"]
    # a multi-model turn (a subagent on another model) can carry the canonical
    # name on any entry, so the raw key is only a last resort.
    return next(iter(model_usage), None)


_WINDOW_LABELS = {
    "five_hour": "5h",
    "seven_day": "week",
    "seven_day_opus": "week (opus)",
    "seven_day_sonnet": "week (sonnet)",
    "overage": "overage",
}
# 5-hour first, then the weekly windows: the tighter window is the one a user
# is usually about to hit.
_WINDOW_ORDER = (
    "five_hour",
    "seven_day",
    "seven_day_opus",
    "seven_day_sonnet",
    "overage",
)


def _reportable(snapshot: UsageSnapshot) -> Optional[UsageSnapshot]:
    """None unless the snapshot actually says something.

    `info_segments` renders any non-None snapshot, so returning an empty one
    leaves the strip showing the effort segment on its own — a model-less,
    context-less "high" — which reads as a bug rather than as "nothing known".
    """
    if any(
        (
            snapshot.model,
            snapshot.tokens,
            snapshot.cost,
            snapshot.quotas,
            snapshot.context_tokens,
            snapshot.num_turns,
        )
    ):
        return snapshot
    return None


def rate_limits_to_quotas(rate_limits: dict) -> tuple:
    """Map the CLI's rate-limit windows into Quotas, tightest window first.

    `utilization` is a fraction of the window consumed, so it becomes
    `percent_remaining` inverted — a window the CLI reported without a
    utilization figure is dropped rather than displayed as an unearned 0%.
    """
    quotas = []
    for kind in _WINDOW_ORDER:
        info = rate_limits.get(kind)
        utilization = getattr(info, "utilization", None) if info else None
        if utilization is None:
            continue
        quotas.append(
            Quota(
                label=_WINDOW_LABELS.get(kind, kind),
                percent_remaining=100.0 - utilization * 100.0,
                resets_at=getattr(info, "resets_at", None),
            )
        )
    return tuple(quotas)


def context_to_breakdown(payload):
    """Map a get_context_usage() payload into (tokens, max, categories, model)."""
    if not isinstance(payload, dict):
        return None, None, (), None
    categories = tuple(
        ContextCategory(
            name=str(item.get("name", "")), tokens=int(item.get("tokens", 0))
        )
        for item in (payload.get("categories") or [])
        if isinstance(item, dict)
    )
    return (
        payload.get("totalTokens"),
        payload.get("maxTokens"),
        categories,
        payload.get("model"),
    )


def _build_user_stream(text: str, image_paths: List[str]):
    async def _gen():
        content: list = [{"type": "text", "text": text or ""}]
        for path in image_paths:
            try:
                data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
            except OSError:
                continue
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": data,
                    },
                }
            )
        yield {
            "type": "user",
            "message": {"role": "user", "content": content},
            "parent_tool_use_id": None,
        }

    return _gen()


def _wrap_tool(tool: dict):
    name = tool["name"]
    description = tool["description"]
    schema = tool["input_schema"]
    handler: Callable = tool["handler"]

    @sdk_tool(name, description, schema)
    async def _impl(args: dict):
        result = handler(args)
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, dict) and "content" in result:
            return result
        return {"content": [{"type": "text", "text": str(result)}]}

    return _impl
