"""Claude Agent SDK adapter — implements `SciQLop.components.agents.AgentBackend`."""
from __future__ import annotations

import asyncio
import base64
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncIterator, Callable, List, Optional

from SciQLop.components.agents import BackendContext, SessionEntry
from SciQLop.components.agents.backend import StreamBlock
from SciQLop.components.agents.chat import (
    ChatMessage,
    ImageBlock,
    TextBlock,
    ThinkingBlock,
    ToolActivityBlock,
    write_b64_image,
)

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


import logging as _logging  # DESYNC-PROBE (temporary instrumentation)
from SciQLop.components.sciqlop_logging import getLogger as _getLogger  # DESYNC-PROBE
_log = _getLogger("sciqlop_claude")  # DESYNC-PROBE
_log.level = _logging.DEBUG  # DESYNC-PROBE: force-emit probe logs regardless of global level


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
        async with ClaudeSDKClient(options=ClaudeAgentOptions()) as client:
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

SYSTEM_PROMPT = (
    "You are a helper embedded inside SciQLop, a Qt desktop application for "
    "space-physics time-series visualization. You act on the live running "
    "instance through an MCP server called 'sciqlop'.\n\n"
    "Read tools — call these freely, they never mutate state:\n"
    "  • sciqlop_window_state / sciqlop_list_panels / sciqlop_active_panel — "
    "    live session snapshot, panel names, time ranges, plotted products.\n"
    "  • sciqlop_screenshot_panel(name?) / sciqlop_screenshot_plot(name?, "
    "    plot_index) — PNG of a panel or a single subplot, returned inline. "
    "    Always pass `name` when you know which panel you want — omitting it "
    "    falls back to whichever panel is currently focused.\n"
    "  • sciqlop_api_reference(module?) — introspected markdown dump of "
    "    SciQLop.user_api. Call this BEFORE writing code against the user "
    "    API so you use real method names and signatures. Start with the "
    "    empty string to list submodules, then drill into 'plot', 'gui', "
    "    'catalogs', 'virtual_products', 'threading' as needed.\n"
    "  • sciqlop_products_tree(path?) — walk SciQLop's live ProductsModel. "
    "    This is the tree `plot_product` actually resolves against (display "
    "    names, `//`-joined). USE THIS — not sciqlop_speasy_inventory — to "
    "    find real product paths before calling plot_product. Start with an "
    "    empty string to list top-level providers, then drill with e.g. "
    "    'speasy//amda//Parameters//MMS//MMS1'.\n"
    "  • sciqlop_search_literature(query, source?, max_results?) / "
    "sciqlop_fetch_paper(id_or_url) — search arXiv + NASA ADS for papers and "
    "read an arXiv paper's full text. Use these to ground and cite claims.\n"
    "  • WebSearch / WebFetch — general web search and page fetch when the "
    "scholarly tools are not enough.\n"
    "  • sciqlop_speasy_inventory(path?) — browse the speasy inventory for "
    "    spz_uid values used by `speasy.get_data` directly. These paths are "
    "    NOT valid for plot_product — use sciqlop_products_tree instead "
    "    unless you are writing code that calls speasy.get_data yourself.\n"
    "  • sciqlop_wait_for_plot_data(name?, timeout?) — block until every "
    "    plottable on a panel has finished fetching data. Call this after "
    "    plot_product and BEFORE screenshotting, otherwise the screenshot "
    "    captures an empty plot.\n"
    "  • sciqlop_list_notebooks / sciqlop_read_notebook(path) — browse "
    "    Jupyter notebooks in the active workspace directory. Paths are "
    "    workspace-relative. Code cells come back in ```python fences, "
    "    markdown cells verbatim.\n\n"
    "Write tools (only present when the user enabled 'Allow write actions' "
    "and gated by per-call approval):\n"
    "  • sciqlop_create_panel() — create a new empty plot panel; returns "
    "    its name. Use the returned name to target that panel in subsequent "
    "    calls so you never rely on which panel happens to be active.\n"
    "  • sciqlop_set_time_range(start, stop, name?) — set a panel's time "
    "    range (POSIX seconds). Pass `name` to target a specific panel.\n"
    "  • sciqlop_exec_python(code) — run arbitrary Python inside SciQLop's "
    "    embedded IPython kernel. `SciQLop.user_api` (plot, gui, catalogs, "
    "    virtual_products), speasy, numpy and the workspace packages are "
    "    all importable. Prefer this over asking the user to run code. "
    "    Always show the user the code you ran, and always consult "
    "    sciqlop_api_reference first if unsure about signatures.\n"
    "  • sciqlop_install_package(packages) — install Python dependencies into "
    "    the workspace venv and record them in the manifest so they persist. "
    "    Use this to add libraries; never run `pip install` directly (it is not "
    "    recorded and is wiped when the venv is rebuilt).\n"
    "  • sciqlop_create_notebook(path) / sciqlop_write_notebook_cell / "
    "    sciqlop_insert_notebook_cell / sciqlop_delete_notebook_cell — "
    "    edit notebooks on disk in the workspace directory. JupyterLab's "
    "    file watcher will prompt the user to reload. Always read a "
    "    notebook first before editing so indices match.\n\n"
    "Typical plot workflow — follow this every time:\n"
    "  1. sciqlop_products_tree('') → drill down to the target parameter's "
    "     full `//`-joined path.\n"
    "  2. sciqlop_create_panel() → capture the returned panel name.\n"
    "  3. sciqlop_exec_python: "
    "     `plot_panel('<name>').plot_product('<path>', plot_type=PlotType.TimeSeries)`.\n"
    "  4. sciqlop_set_time_range(start, stop, name='<name>') if needed.\n"
    "  5. sciqlop_wait_for_plot_data(name='<name>').\n"
    "  6. sciqlop_screenshot_panel(name='<name>').\n"
    "Always thread the captured panel name through — never assume the active "
    "panel is the one you just made.\n\n"
    "Voice and conduct — you are a research scientist (plasma physics and "
    "astrophysics) and a strong software engineer, not a generic assistant:\n"
    "  • Be direct. Do not open with praise or agreement, do not validate a "
    "claim reflexively, do not soften corrections. If the data or the physics "
    "does not support what the user said, say so and explain why.\n"
    "  • Be quantitative. Give numbers with units and the time/spatial range "
    "or uncertainty they apply to. Name the instrument, mission, or product a "
    "value comes from.\n"
    "  • Ground physical claims in the literature. Attribute an established "
    "result (mission/instrument, or author–year when you know it); distinguish "
    "a published result from your own inference; when a value should be checked "
    "against published work, say so rather than asserting it.\n"
    "  • Never invent data, time ranges, event times, or physical values. If "
    "you don't know, say \"I don't know\" or \"this needs verification\" — read "
    "the live state or the data first.\n"
    "  • Write correct, reproducible code: verify API signatures before "
    "calling, run and check rather than claim something works, keep it simple.\n"
    "  • Write plainly: no filler or marketing words, plain scientific prose, "
    "short sentences. Cite product names and time ranges verbatim. Accuracy and "
    "concision over fluency."
)


def claude_cli_available() -> bool:
    return shutil.which("claude") is not None


def sdk_available() -> tuple[bool, Optional[str]]:
    return _SDK_AVAILABLE, _SDK_IMPORT_ERROR


_INTERRUPT_DRAIN_TIMEOUT_S = 15.0


class ClaudeBackend:
    display_name = "Claude"
    model_choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    supports_sessions = True

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
        self._allow_writes = ctx.allow_writes
        self._resume: Optional[str] = None
        self._client: Optional[ClaudeSDKClient] = None
        self._lock = asyncio.Lock()
        self._slash_cache: Optional[List[str]] = None

    async def _ensure_client(self) -> ClaudeSDKClient:
        if self._client is not None:
            return self._client
        sdk_tools = [_wrap_tool(t) for t in self._tools]
        server = create_sdk_mcp_server(name=_MCP_SERVER_NAME, tools=sdk_tools)
        allowed = [f"mcp__{_MCP_SERVER_NAME}__{t['name']}" for t in self._tools]
        allowed += ["WebSearch", "WebFetch"]  # built-in web search + page fetch (ungated)
        options = ClaudeAgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={_MCP_SERVER_NAME: server},
            allowed_tools=allowed,
            can_use_tool=(
                self._permission_check
                if (self._confirm_cb or self._ask_question_cb) else None
            ),
            model=self._model,
            resume=self._resume,
            cwd=str(_sessions.current_workspace_dir()),
            setting_sources=["user", "project"],
            max_buffer_size=_MAX_BUFFER_SIZE,
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        return self._client

    async def ask(
        self, prompt: str, image_paths: Optional[List[str]] = None
    ) -> AsyncIterator[StreamBlock]:
        async with self._lock:
            client = await self._ensure_client()
            await client.query(_build_user_stream(prompt, image_paths or []))
            self._probe_seq = getattr(self, "_probe_seq", 0) + 1  # DESYNC-PROBE
            _seq = self._probe_seq  # DESYNC-PROBE
            _log.warning(  # DESYNC-PROBE
                f"DESYNC-PROBE turn={_seq} START prompt={(prompt or '')[:80]!r}")
            _consumed = 0  # DESYNC-PROBE
            async for message in client.receive_response():
                _consumed += 1  # DESYNC-PROBE
                _mtype = type(message).__name__  # DESYNC-PROBE
                if _mtype == "ResultMessage":  # DESYNC-PROBE
                    _log.warning(  # DESYNC-PROBE
                        f"DESYNC-PROBE turn={_seq} msg#{_consumed} ResultMessage "
                        f"subtype={getattr(message, 'subtype', None)!r} "
                        f"is_error={getattr(message, 'is_error', None)!r} "
                        f"num_turns={getattr(message, 'num_turns', None)!r} "
                        f"session={getattr(message, 'session_id', None)!r} "
                        f"-> receive_response() TERMINATES here")  # DESYNC-PROBE
                else:  # DESYNC-PROBE
                    _content = getattr(message, "content", None)  # DESYNC-PROBE
                    _kinds = ([type(b).__name__ for b in _content]  # DESYNC-PROBE
                              if isinstance(_content, list) else None)  # DESYNC-PROBE
                    _log.warning(  # DESYNC-PROBE
                        f"DESYNC-PROBE turn={_seq} msg#{_consumed} {_mtype} blocks={_kinds}")
                for block in self._decode_message(message):
                    yield block
            _log.warning(  # DESYNC-PROBE
                f"DESYNC-PROBE turn={_seq} END consumed={_consumed}")

    async def reset(self) -> None:
        async with self._lock:
            await self._disconnect()
            self._resume = None
            self._slash_cache = None

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

    def set_allow_writes(self, allow: bool) -> None:
        self._allow_writes = allow

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
        if not self._allow_writes:
            return PermissionResultDeny(
                message=(
                    "write actions are currently disabled — ask the user to "
                    "toggle 'Allow write actions' in the SciQLop chat dock"
                )
            )
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
                    blocks.append(ToolActivityBlock(
                        tool_name=str(name).split("__")[-1],
                        tool_input=getattr(block, "input", {}) or {},
                        tool_use_id=getattr(block, "id", "") or "",
                    ))
            return blocks
        if isinstance(message, UserMessage):
            for block in _iter_tool_results(message):
                blocks.extend(self._tool_result_blocks(block))
                summary = _result_summary(block)
                if summary:
                    blocks.append(ToolActivityBlock(
                        tool_use_id=getattr(block, "tool_use_id", "") or "",
                        result=summary,
                    ))
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
