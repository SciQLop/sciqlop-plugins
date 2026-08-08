"""opencode-agent-sdk adapter — implements `SciQLop.components.agents.AgentBackend`."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Callable, Iterator, List, Optional

from SciQLop.components.agents import BackendContext, SessionEntry
from SciQLop.components.agents.backend import StreamBlock
from SciQLop.components.agents.chat import ChatMessage, TextBlock, ToolActivityBlock
from SciQLop.components.agents.settings import AgentWriteMode

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
    "Write tools (only present when write mode is 'confirm' or 'yolo'; "
    "gated by per-call approval in 'confirm' mode):\n"
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
    'you don\'t know, say "I don\'t know" or "this needs verification" — read '
    "the live state or the data first.\n"
    "  • Write correct, reproducible code: verify API signatures before "
    "calling, run and check rather than claim something works, keep it simple.\n"
    "  • Write plainly: no filler or marketing words, plain scientific prose, "
    "short sentences. Cite product names and time ranges verbatim. Accuracy and "
    "concision over fluency."
)


def _normalize_schema_types(schema):
    """Recursively normalize a JSON schema so opencode-agent-sdk can consume it.

    The SDK's ``_json_type_to_python`` only handles scalar type strings; it
    crashes with ``TypeError: unhashable type: 'list'`` on union types like
    ``{"type": ["string", "number"]}``. We collapse a union to its first
    non-"null" member — sufficient for signature generation; runtime values
    still flow through as-is.
    """
    if not isinstance(schema, dict):
        return schema
    normalized = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, list):
            non_null = [t for t in value if t != "null"]
            normalized[key] = non_null[0] if non_null else value[0]
        elif isinstance(value, dict):
            normalized[key] = _normalize_schema_types(value)
        elif isinstance(value, list):
            normalized[key] = [
                _normalize_schema_types(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            normalized[key] = value
    return normalized


def _wrap_tool(tool: dict):
    """Wrap a SciQLop tool dict as an in-process opencode SDK tool."""
    name = tool["name"]
    description = tool["description"]
    schema = _normalize_schema_types(_reorder_required_first(tool["input_schema"]))
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


def _reorder_required_first(schema: dict) -> dict:
    """Reorder a JSON-schema's ``properties`` so required ones come first.

    opencode-agent-sdk's MCP bridge (``_mcp_bridge._make_wrapper``) iterates
    properties in insertion order to build an ``inspect.Signature``. Required
    properties become positional parameters with no default; optional ones get
    a default. If a required property appears after an optional one, Python
    raises ``ValueError: non-default argument follows default argument`` when
    the signature is constructed. We sort properties so all required keys
    precede the rest, preserving the relative order within each group.
    """
    if not isinstance(schema, dict):
        return schema
    properties = schema.get("properties")
    required = schema.get("required") or []
    if not isinstance(properties, dict) or not required:
        return schema
    required_set = set(required)
    ordered = {k: properties[k] for k in properties if k in required_set}
    ordered.update({k: properties[k] for k in properties if k not in required_set})
    return {**schema, "properties": ordered}


def fetch_models(timeout: float = 10.0) -> List[tuple[str, Optional[str]]]:
    """Return the model dropdown choices for the SciQLop chat dock.

    Sources, merged in order:
    1. ``"Default (opencode)"`` — falls back to opencode's own config.
    2. Models from the opencode config (``model``, ``small_model``,
       ``agent.<name>.model``) — everything the user has access to.
    3. Models seen in prior session history — anything run before that
       might not appear in the current config.

    The dropdown value is the fully-qualified ``"<provider>/<model>"`` string;
    ``_ensure_client`` splits it back into ``provider_id`` and ``model`` for
    ``AgentOptions``.
    """
    from . import sessions as _sessions

    choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    seen: set = set()
    configs: List[dict] = []
    try:
        configs = _sessions.configured_models()
    except Exception:
        pass
    try:
        configs.extend(_sessions.known_session_models())
    except Exception:
        pass
    for spec in configs:
        provider = spec.get("providerID")
        model_id = spec.get("id")
        if not provider or not model_id or not isinstance(model_id, str):
            continue
        key = (provider, model_id)
        if key in seen:
            continue
        seen.add(key)
        label = f"{_pretty_model(model_id)} ({provider})"
        value = f"{provider}/{model_id}"
        choices.append((label, value))
    return choices


def _pretty_model(model_id: str) -> str:
    """Turn a kebab/snake model id into a Title Cased display label."""
    return " ".join(part.capitalize() for part in model_id.replace("_", "-").split("-"))


def _split_provider_model(value: Optional[str]) -> tuple[str, str]:
    """Split a dropdown value back into (provider_id, model_id) for AgentOptions.

    The dropdown encodes selections as ``"<provider>/<model>"``. The "Default
    (opencode)" entry has value None — empty strings make opencode-agent-sdk
    fall through to opencode's own defaults.
    """
    if not value:
        return "", ""
    provider, _, model_id = value.partition("/")
    return provider, model_id


class _OpencodeStream:
    """Translate opencode-agent-sdk messages into SciQLop chat StreamBlocks.

    opencode's subprocess-ACP stream sends assistant text as a *growing
    accumulated snapshot* (each AssistantMessage carries the full text so far),
    while the SciQLop chat consumer appends incremental deltas. We diff snapshots
    into deltas and close the open text block when a tool call interrupts it or
    the turn ends. Tool calls arrive as ToolUseBlock at completion -> one
    ToolActivityBlock each. Thinking is not separable here: the SDK flattens
    agent_thought_chunk into the same AssistantMessage/TextBlock channel as the
    answer, so it renders inline as text.
    """

    def __init__(self):
        self._acc = ""  # text already emitted for the open text block
        self._open = False  # an incomplete TextBlock is open in the consumer

    def feed(self, message) -> Iterator[StreamBlock]:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            return
        for block in content:
            if getattr(block, "name", None) is not None:  # ToolUseBlock
                yield from self._close_text()
                yield ToolActivityBlock(
                    tool_name=str(block.name).split("__")[-1],
                    tool_input=getattr(block, "input", None) or {},
                    tool_use_id=getattr(block, "id", "") or "",
                )
            else:
                text = getattr(block, "text", None)
                if text is not None:
                    yield from self._emit_text(text)

    def flush(self) -> Iterator[StreamBlock]:
        yield from self._close_text()

    def _emit_text(self, snapshot: str) -> Iterator[StreamBlock]:
        if snapshot == self._acc:
            return
        if not snapshot.startswith(self._acc):
            yield from self._close_text()  # buffer reset -> new block
        delta = snapshot[len(self._acc) :]
        self._acc = snapshot
        self._open = True
        yield TextBlock(text=delta, complete=False)

    def _close_text(self) -> Iterator[StreamBlock]:
        if self._open:
            self._open = False
            self._acc = ""
            yield TextBlock(text="", complete=True)


class OpencodeBackend:
    display_name = "Opencode"
    model_choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    supports_sessions = True

    def __init__(self, ctx: BackendContext):
        if not _SDK_AVAILABLE:
            raise RuntimeError(
                f"opencode-agent-sdk not importable: {_SDK_IMPORT_ERROR}"
            )
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
        self._write_mode = ctx.write_mode
        self._resume: Optional[str] = None
        self._client: Optional[SDKClient] = None
        self._lock = asyncio.Lock()

    async def _ensure_client(self) -> SDKClient:
        if self._client is not None:
            return self._client
        sdk_tools = [_wrap_tool(t) for t in self._tools]
        server = create_sdk_mcp_server(name=_MCP_SERVER_NAME, tools=sdk_tools)
        allowed = [f"mcp__{_MCP_SERVER_NAME}__{t['name']}" for t in self._tools]
        hooks_cfg = (
            {
                "PreToolUse": [
                    HookMatcher(matcher=None, hooks=[self._pre_tool_use_hook]),
                ],
            }
            if self._gated_names
            else {}
        )
        provider_id, model_id = _split_provider_model(self._model)
        options = AgentOptions(
            system_prompt=SYSTEM_PROMPT,
            mcp_servers={_MCP_SERVER_NAME: server},
            allowed_tools=allowed,
            hooks=hooks_cfg,
            model=model_id,
            provider_id=provider_id,
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
            stream = _OpencodeStream()
            async for message in client.receive_response():
                for block in stream.feed(message):
                    yield block
            for block in stream.flush():
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

    def set_write_mode(self, mode: str) -> None:
        self._write_mode = mode

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
        if self._write_mode == AgentWriteMode.NONE:
            return {
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "write actions are disabled — set write mode to 'confirm' or "
                    "'yolo' in the SciQLop chat dock"
                ),
            }
        if self._write_mode == AgentWriteMode.YOLO:
            return {
                "permissionDecision": "allow",
                "permissionDecisionReason": "auto-approved (yolo mode)",
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
