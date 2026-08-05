"""Kimi Code (ACP) adapter — implements `SciQLop.components.agents.AgentBackend`.

Kimi Code is the Node.js CLI (`kimi`); it speaks the Agent Client Protocol
over stdio (`kimi acp`). We spawn it, expose the SciQLop tools through an
in-process MCP HTTP server (see `mcp_server.py`), and translate ACP session
updates into SciQLop chat StreamBlocks. Auth, models and session storage all
belong to the user's own Kimi Code setup — nothing to configure in SciQLop
beyond running `kimi login` once.

Turn correlation comes free from JSON-RPC (one prompt request, one prompt
response): the whole class of stream-desync bugs that per-turn ResultMessage
sniffing invites (see sciqlop_claude) does not exist here.
"""
from __future__ import annotations

import asyncio
import base64
import shutil
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

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
from .mcp_server import SciqlopMcpServer

try:
    import acp
    from acp import helpers as acp_helpers
    from acp.schema import (
        AgentMessageChunk,
        AgentThoughtChunk,
        AvailableCommandsUpdate,
        ClientCapabilities,
        FileSystemCapabilities,
        HttpMcpServer,
        Implementation,
        RequestPermissionResponse,
        ToolCallProgress,
        ToolCallStart,
        UserMessageChunk,
    )

    _ACP_AVAILABLE = True
    _ACP_IMPORT_ERROR: Optional[str] = None
except Exception as e:  # pragma: no cover
    _ACP_AVAILABLE = False
    _ACP_IMPORT_ERROR = str(e)


_DEFAULT_MODEL_CHOICES: List[tuple[str, Optional[str]]] = [
    ("Default (Kimi Code)", None),
]

SYSTEM_PROMPT = (
    "You are a helper embedded inside SciQLop, a Qt desktop application for "
    "space-physics time-series visualization. You act on the live running "
    "instance through a set of tools from the 'sciqlop' MCP server.\n\n"
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


def kimi_cli_available() -> bool:
    return shutil.which("kimi") is not None


def sdk_available() -> tuple[bool, Optional[str]]:
    return _ACP_AVAILABLE, _ACP_IMPORT_ERROR


def fetch_models() -> List[tuple[str, Optional[str]]]:
    """Model dropdown choices from the user's Kimi Code config file.

    The ACP server reports the same list per session, but the dropdown is
    built before any session exists; parsing the config TOML directly avoids
    spawning a throwaway agent at plugin load.
    """
    choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    config = Path.home() / ".kimi-code" / "config.toml"
    try:
        import tomllib
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except Exception:
        return choices
    default = data.get("default_model") or ""
    for name, spec in (data.get("models") or {}).items():
        if not name or name == default:
            continue
        label = spec.get("display_name") or name if isinstance(spec, dict) else name
        choices.append((label, name))
    return choices


class _AcpStream:
    """Translate ACP session updates into SciQLop chat StreamBlocks.

    Chunks are already incremental deltas; they forward as incomplete blocks,
    closed when the other kind interrupts or the turn ends. ToolCallStart
    yields the activity block; ToolCallProgress with content yields a
    result-only activity block the dock merges by tool_call_id, plus
    ImageBlocks for inline screenshots.
    """

    def __init__(self, tempdir: Path):
        self._tempdir = tempdir
        self._open: Optional[type] = None  # TextBlock | ThinkingBlock | None

    def feed(self, update) -> List[StreamBlock]:
        if isinstance(update, AgentMessageChunk):
            return [self._switch(TextBlock),
                    TextBlock(text=update.content.text, complete=False)]
        if isinstance(update, AgentThoughtChunk):
            return [self._switch(ThinkingBlock),
                    ThinkingBlock(text=update.content.text, complete=False)]
        if isinstance(update, ToolCallStart):
            return [self._close(),
                    ToolActivityBlock(
                        tool_name=str(update.title or "").split("__")[-1],
                        tool_input=_raw_input_dict(update.raw_input),
                        tool_use_id=update.tool_call_id or "",
                    )]
        if isinstance(update, ToolCallProgress):
            blocks: List[StreamBlock] = []
            text, images = _tool_output(update)
            for data, mime in images:
                path = write_b64_image(data, mime, self._tempdir, prefix="tool")
                if path:
                    blocks.append(ImageBlock(path=path))
            if text:
                blocks.append(ToolActivityBlock(
                    tool_use_id=update.tool_call_id or "", result=text))
            return blocks
        return []

    def flush(self) -> List[StreamBlock]:
        return [self._close()]

    def _switch(self, kind: type) -> Optional[StreamBlock]:
        closing = None
        if self._open is not None and self._open is not kind:
            closing = self._close()
        self._open = kind
        return closing

    def _close(self) -> Optional[StreamBlock]:
        if self._open is not None:
            cls = self._open
            self._open = None
            return cls(text="", complete=True)
        return None


def _raw_input_dict(raw_input: Any) -> dict:
    return raw_input if isinstance(raw_input, dict) else {}


def _tool_output(update) -> tuple[str, List[tuple[str, str]]]:
    """Extract (text, [(b64 data, mime)]) from a ToolCallProgress update."""
    texts: List[str] = []
    images: List[tuple[str, str]] = []
    for content in update.content or []:
        inner = getattr(content, "content", None)
        items = inner if isinstance(inner, list) else [inner]
        for item in items:
            if item is None:
                continue
            text = getattr(item, "text", None)
            if text is not None:
                texts.append(text)
                continue
            data = getattr(item, "data", None)
            if data is not None:
                images.append((data, getattr(item, "mime_type", None) or "image/png"))
    raw = update.raw_output
    if not texts and isinstance(raw, str):
        texts.append(raw)
    return "\n".join(t for t in texts if t), images


class _SciqlopAcpClient:
    """The ACP client face Kimi Code talks to (duck-types acp.Client).

    Only session_update and request_permission are meaningful for us: we
    advertise no fs/terminal capabilities, so the agent has no reason to call
    those — the stubs below exist purely to answer cleanly if it ever does.
    """

    def __init__(self, backend: "KimiBackend"):
        self._backend = backend

    async def session_update(self, session_id: str, update, **kwargs) -> None:
        self._backend._on_update(update)

    async def request_permission(self, options, session_id: str, tool_call, **kwargs):
        return await self._backend._decide_permission(options, tool_call)

    def on_connect(self, conn) -> None:
        pass

    async def read_text_file(self, **kwargs):
        raise acp.RequestError.method_not_found("fs/read_text_file")

    async def write_text_file(self, **kwargs):
        raise acp.RequestError.method_not_found("fs/write_text_file")

    async def create_terminal(self, **kwargs):
        raise acp.RequestError.method_not_found("terminal/create")

    async def terminal_output(self, **kwargs):
        raise acp.RequestError.method_not_found("terminal/output")

    async def release_terminal(self, **kwargs):
        raise acp.RequestError.method_not_found("terminal/release")

    async def wait_for_terminal_exit(self, **kwargs):
        raise acp.RequestError.method_not_found("terminal/wait_for_exit")

    async def kill_terminal(self, **kwargs):
        raise acp.RequestError.method_not_found("terminal/kill")


class KimiBackend:
    display_name = "Kimi"
    model_choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    supports_sessions = True

    def __init__(self, ctx: BackendContext):
        if not _ACP_AVAILABLE:
            raise RuntimeError(f"agent-client-protocol not importable: {_ACP_IMPORT_ERROR}")
        if not kimi_cli_available():
            raise RuntimeError(
                "kimi CLI not found on PATH — install Kimi Code "
                "(https://www.kimi.com/code) and run `kimi login` once."
            )
        self._main_window = ctx.main_window
        self._tools = list(ctx.tools)
        self._tool_names = {t["name"] for t in ctx.tools}
        self._gated_names = {t["name"] for t in ctx.tools if t.get("gated")}
        self._tempdir = Path(ctx.tempdir)
        self._tempdir.mkdir(parents=True, exist_ok=True)
        self._confirm_cb = ctx.confirm_cb
        self._allow_writes = ctx.allow_writes
        self._model: Optional[str] = None
        self._resume: Optional[str] = None
        self._lock = asyncio.Lock()
        self._mcp = SciqlopMcpServer(
            self._tools, self._gated_names,
            is_write_allowed=lambda: self._allow_writes,
            confirm_cb=self._confirm_cb,
        )
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._conn = None
        self._session_id: Optional[str] = None
        self._updates: Optional[asyncio.Queue] = None
        self._slash_commands: List[str] = []

    # ------------------------------------------------------------------ ACP

    async def _ensure_connection(self):
        if self._conn is not None:
            return
        mcp_url = await self._mcp.start()
        self._mcp_servers = [HttpMcpServer(
            name="sciqlop", url=mcp_url, type="http", headers=[],
        )]
        self._proc = await asyncio.create_subprocess_exec(
            "kimi", "acp",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._conn = acp.connect_to_agent(
            _SciqlopAcpClient(self), self._proc.stdin, self._proc.stdout,
        )
        await self._conn.initialize(
            protocol_version=acp.PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(
                fs=FileSystemCapabilities(read_text_file=False, write_text_file=False),
                terminal=False,
            ),
            client_info=Implementation(name="sciqlop", title="SciQLop", version="1.0"),
        )

    async def _apply_model(self) -> None:
        if (self._model and self._conn is not None
                and self._session_id is not None):
            await self._conn.set_config_option(
                session_id=self._session_id, config_id="model", value=self._model,
            )

    async def _ensure_session(self):
        if self._session_id is not None:
            return
        await self._ensure_connection()
        if self._resume:
            await self._conn.resume_session(
                cwd=str(_sessions.current_workspace_dir()),
                session_id=self._resume,
                mcp_servers=self._mcp_servers,
            )
            self._session_id = self._resume
            self._resume = None
        else:
            resp = await self._conn.new_session(
                cwd=str(_sessions.current_workspace_dir()),
                mcp_servers=self._mcp_servers,
            )
            self._session_id = resp.session_id
        await self._apply_model()

    def _on_update(self, update) -> None:
        if isinstance(update, AvailableCommandsUpdate):
            self._slash_commands = [
                "/" + c.name.lstrip("/") for c in update.available_commands
            ]
            return
        queue = self._updates
        if queue is not None:
            queue.put_nowait(update)

    async def _decide_permission(self, options, tool_call):
        """Answer Kimi's permission prompts.

        Our MCP tools: non-gated ones auto-approve; gated ones defer to the
        dock's confirm dialog when writes are enabled, else reject (the same
        gate also runs inside the tool handler — this layer just stops the
        call earlier). Kimi's own built-in tools (shell, file edits, …) are
        always rejected: the embedded chat acts on SciQLop only.
        """
        short = str(getattr(tool_call, "title", "") or "").split("__")[-1]
        if short in self._tool_names:
            if short not in self._gated_names:
                return _permission_answer(options, allow=True)
            if not self._allow_writes or self._confirm_cb is None:
                return _permission_answer(options, allow=False)
            try:
                allowed = await self._confirm_cb(
                    short, _raw_input_dict(getattr(tool_call, "raw_input", None)))
            except Exception:
                allowed = False
            return _permission_answer(options, allow=allowed)
        return _permission_answer(options, allow=False)

    # ------------------------------------------------------------- protocol

    async def ask(
        self, prompt: str, image_paths: Optional[List[str]] = None
    ) -> AsyncIterator[StreamBlock]:
        async with self._lock:
            await self._ensure_session()
            queue: asyncio.Queue = asyncio.Queue()
            self._updates = queue
            blocks = [acp_helpers.text_block(prompt or "")]
            for path in image_paths or []:
                try:
                    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
                except OSError:
                    continue
                blocks.append(acp_helpers.image_block(data, _mime_for(path)))
            prompt_task = asyncio.create_task(self._conn.prompt(
                session_id=self._session_id, prompt=blocks,
            ))
            prompt_task.add_done_callback(lambda _t: queue.put_nowait(None))
            stream = _AcpStream(self._tempdir)
            try:
                while True:
                    update = await queue.get()
                    if update is None:  # prompt response arrived; turn is over
                        break
                    for block in stream.feed(update):
                        if block is not None:
                            yield block
                for block in stream.flush():
                    if block is not None:
                        yield block
                # propagate a protocol-level failure as an exception the dock
                # renders as an error message
                await prompt_task
            finally:
                self._updates = None

    async def reset(self) -> None:
        async with self._lock:
            if self._conn is not None:
                resp = await self._conn.new_session(
                    cwd=str(_sessions.current_workspace_dir()),
                    mcp_servers=self._mcp_servers,
                )
                self._session_id = resp.session_id
            self._resume = None

    async def cancel(self) -> None:
        # session/cancel is a notification; the in-flight prompt request then
        # resolves with stopReason 'cancelled', ending ask()'s stream.
        conn = self._conn
        if conn is not None and self._session_id is not None:
            await conn.cancel(session_id=self._session_id)

    async def resume(self, session_id: str) -> None:
        async with self._lock:
            self._session_id = None
            self._resume = session_id

    async def set_model(self, model: Optional[str]) -> None:
        async with self._lock:
            self._model = model
            await self._apply_model()

    def set_allow_writes(self, allow: bool) -> None:
        self._allow_writes = allow

    async def list_slash_commands(self) -> List[str]:
        return list(self._slash_commands)

    def list_sessions(self) -> List[SessionEntry]:
        return _sessions.list_sessions()

    def load_session(self, session_id: str, image_tempdir: Path) -> List[ChatMessage]:
        return _sessions.load_session_messages(session_id, image_tempdir=image_tempdir)

    def current_session_id(self) -> Optional[str]:
        return self._session_id

    # -------------------------------------------------------------- teardown

    async def _disconnect(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._session_id = None
        if self._proc is not None:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                pass
            self._proc = None
        await self._mcp.stop()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._disconnect()


def _permission_answer(options, allow: bool) -> "RequestPermissionResponse":
    """Pick the best-matching option id (once over always) for an allow/deny."""
    from acp.schema import AllowedOutcome, DeniedOutcome

    wanted = ("allow_once", "allow_always") if allow else ("reject_once", "reject_always")
    ids = {getattr(o, "kind", None): getattr(o, "option_id", None) for o in options or []}
    for kind in wanted:
        if ids.get(kind):
            return RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id=ids[kind]))
    if ids:
        return RequestPermissionResponse(
            outcome=AllowedOutcome(
                outcome="selected", option_id=next(iter(ids.values()))))
    # No options to pick from: cancel the request (agent treats it as denied).
    return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


def _mime_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
