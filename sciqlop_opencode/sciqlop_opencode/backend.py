"""opencode-agent-sdk adapter — implements `SciQLop.components.agents.AgentBackend`."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Callable, List, Optional

from SciQLop.components.agents import BackendContext, SessionEntry
from SciQLop.components.agents.backend import StreamBlock
from SciQLop.components.agents.chat import ChatMessage, TextBlock

from . import sessions as _sessions

try:
    from opencode_agent_sdk import (
        AgentOptions,
        HookMatcher,
        SDKClient,
        create_sdk_mcp_server,
        tool as sdk_tool,
    )
    _SDK_AVAILABLE = True
    _SDK_IMPORT_ERROR: Optional[str] = None
except Exception as e:  # pragma: no cover
    _SDK_AVAILABLE = False
    _SDK_IMPORT_ERROR = str(e)

try:
    from opencode_agent_sdk import AssistantMessage
except ImportError:
    AssistantMessage = None  # SDK not installed; class won't be instantiable anyway


_MCP_SERVER_NAME = "sciqlop"

_DEFAULT_MODEL_CHOICES: List[tuple[str, Optional[str]]] = [
    ("Default (opencode)", None),
]


def opencode_cli_available() -> bool:
    return shutil.which("opencode") is not None


def sdk_available() -> tuple[bool, Optional[str]]:
    return _SDK_AVAILABLE, _SDK_IMPORT_ERROR


SYSTEM_PROMPT = (
    "You are a helper embedded inside SciQLop, a Qt desktop application for "
    "space-physics time-series visualization. You act on the live running "
    "instance through a set of in-process tools.\n\n"
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
    "Style: concise, cite product names / time ranges verbatim, prefer "
    "reading live state over guessing."
)


def _wrap_tool(tool: dict):
    """Wrap a SciQLop tool dict as an in-process opencode SDK tool."""
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


def fetch_models(timeout: float = 10.0) -> List[tuple[str, Optional[str]]]:
    """Return the model dropdown choices for the SciQLop chat dock.

    opencode-agent-sdk 0.4.x has no API to enumerate available models —
    `SDKClient` exposes only `connect`/`disconnect`/`query`/`receive_response`,
    and `ModelRegistry` is user-populated (empty by default). The opencode CLI
    selects the model based on its own config (`~/.config/opencode/config.json`
    and `opencode auth login` state). So we ship "Default (opencode)" only;
    `AgentOptions.model=""` lets opencode pick whichever model the user
    configured.
    """
    return list(_DEFAULT_MODEL_CHOICES)


class OpencodeBackend:
    display_name = "Opencode"
    model_choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    supports_sessions = True

    def __init__(self, ctx: BackendContext):
        if not _SDK_AVAILABLE:
            raise RuntimeError(f"opencode-agent-sdk not importable: {_SDK_IMPORT_ERROR}")
        if not opencode_cli_available():
            raise RuntimeError(
                "opencode CLI not found on PATH — install from https://opencode.ai "
                "and run `opencode auth login`."
            )
        self._main_window = ctx.main_window
        self._tools = ctx.tools
        self._gated_names = {t["name"] for t in ctx.tools if t.get("gated")}
        self._tempdir = Path(ctx.tempdir)
        self._tempdir.mkdir(parents=True, exist_ok=True)
        self._confirm_cb = ctx.confirm_cb
        self._model: Optional[str] = None
        self._allow_writes = ctx.allow_writes
        self._resume: Optional[str] = None
        self._client: Optional[SDKClient] = None
        self._lock = asyncio.Lock()

    async def _ensure_client(self) -> SDKClient:
        if self._client is not None:
            return self._client
        sdk_tools = [_wrap_tool(t) for t in self._tools]
        server = create_sdk_mcp_server(name=_MCP_SERVER_NAME, tools=sdk_tools)
        allowed = [f"mcp__{_MCP_SERVER_NAME}__{t['name']}" for t in self._tools]
        hooks_cfg = {
            "PreToolUse": [
                HookMatcher(matcher=None, hooks=[self._pre_tool_use_hook]),
            ],
        } if self._confirm_cb else {}
        options = AgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={_MCP_SERVER_NAME: server},
            allowed_tools=allowed,
            hooks=hooks_cfg,
            model=self._model or "",
            provider_id="",  # let opencode pick the provider from its auth state
            resume=self._resume,
            cwd=str(_sessions.current_workspace_dir()),
            # server_url left empty -> subprocess mode (spawns `opencode acp`)
        )
        self._client = SDKClient(options=options)
        await self._client.connect()
        return self._client

    async def ask(self, prompt: str, image_paths: Optional[List[str]] = None):
        # image_paths is accepted for API parity with other backends but
        # not yet plumbed through opencode-agent-sdk's query format. Text-only
        # for now; tool-generated images flow through tool handlers, not
        # user-attached files.
        async with self._lock:
            client = await self._ensure_client()
            await client.query(prompt)
            async for message in client.receive_response():
                for block in self._decode_message(message):
                    yield block

    async def reset(self) -> None:
        async with self._lock:
            await self._disconnect()
            self._resume = None

    async def cancel(self) -> None:
        # opencode-agent-sdk's SDKClient has no interrupt method; just tear
        # down the connection so the next ask() starts fresh.
        async with self._lock:
            await self._disconnect()

    async def resume(self, session_id: str) -> None:
        async with self._lock:
            await self._disconnect()
            self._resume = session_id

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
            # SDK has no live set_model; reconnect on next ask.
            await self._disconnect()

    def set_allow_writes(self, allow: bool) -> None:
        self._allow_writes = allow

    async def list_slash_commands(self) -> List[str]:
        # opencode-agent-sdk has no API for the slash-command list (no
        # get_server_info equivalent). Could parse opencode's config in
        # a future iteration; empty list is fine for now.
        return []

    def list_sessions(self) -> List[SessionEntry]:
        return [
            SessionEntry(id=s.session_id, label=s.label, mtime=s.mtime)
            for s in _sessions.list_sessions()
        ]

    def load_session(self, session_id: str, image_tempdir: Path) -> List[ChatMessage]:
        return _sessions.load_session_messages(session_id, image_tempdir=image_tempdir)

    async def _pre_tool_use_hook(self, input_data, tool_use_id, context):
        """Decide whether to allow a tool call.

        Returns:
          - None to allow (no opinion)
          - {"permissionDecision": "deny", "permissionDecisionReason": ...} to deny
          - {"permissionDecision": "allow", "permissionDecisionReason": ...} to allow explicitly
        """
        tool_name = input_data.get("tool_name", "")
        short = tool_name.split("__")[-1]
        if short not in self._gated_names:
            return None
        if not self._allow_writes:
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "write actions are disabled — toggle 'Allow write actions' "
                    "in the SciQLop chat dock"
                ),
            }
        tool_input = input_data.get("tool_input") or {}
        try:
            allowed = await self._confirm_cb(short, tool_input)
        except Exception as e:
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": f"approval callback failed: {e}",
            }
        return {
            "permissionDecision": "allow" if allowed else "deny",
            "permissionDecisionReason": "user approval" if allowed else "user denied",
        }

    def _decode_message(self, message) -> List[StreamBlock]:
        blocks: List[StreamBlock] = []
        if AssistantMessage is not None and isinstance(message, AssistantMessage):
            for block in getattr(message, "content", []) or []:
                text = getattr(block, "text", None)
                if text:
                    blocks.append(TextBlock(text=text))
        return blocks
