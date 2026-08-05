"""kimi-agent-sdk adapter — implements `SciQLop.components.agents.AgentBackend`.

kimi-agent-sdk runs the Kimi CLI (Python) runtime in-process. SciQLop tools
are exposed as dynamically created `CallableTool2` subclasses, registered
through a generated agent file (the only tool-registration channel the SDK
exposes); approval gating happens inside the tool call itself, the same way
the Albert backend does it, because custom tools never trigger the runtime's
own approval requests.
"""
from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

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
    from kimi_agent_sdk import (
        ApprovalRequest,
        CallableTool2,
        RunCancelled,
        Session,
        TextPart,
        ThinkPart,
        ToolCall,
        ToolError,
        ToolOk,
        ToolResult,
        TurnEnd,
    )
    from kaos.path import KaosPath
    from kosong.message import ImageURLPart
    from pydantic import Field, create_model

    _SDK_AVAILABLE = True
    _SDK_IMPORT_ERROR: Optional[str] = None
except Exception as e:  # pragma: no cover
    _SDK_AVAILABLE = False
    _SDK_IMPORT_ERROR = str(e)


_DEFAULT_MODEL_CHOICES: List[tuple[str, Optional[str]]] = [
    ("Default (Kimi)", None),
]

# JSON-schema type -> Python type, for building each tool's pydantic params
# model from the SciQLop tool's input_schema.
_JSON_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}

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


def sdk_available() -> tuple[bool, Optional[str]]:
    return _SDK_AVAILABLE, _SDK_IMPORT_ERROR


def _settings_config():
    """A kimi `Config` built from SciQLop settings, or None to fall back to
    the Kimi CLI's own configuration (~/.kimi/config.toml + env vars).

    When the user sets an API key in Settings → Plugins → Kimi it takes
    precedence over the CLI config: the SDK only *augments* an existing
    provider from KIMI_API_KEY, so a bare key without a configured provider
    would still fail — building the whole Config here sidesteps that.
    """
    from .settings import KimiSettings

    settings = KimiSettings()
    if not settings.api_key:
        return None
    from pydantic import SecretStr

    from kimi_cli.config import Config, LLMModel, LLMProvider

    return Config(
        default_model=settings.model,
        providers={
            "kimi": LLMProvider(
                type="kimi",
                base_url=settings.base_url,
                api_key=SecretStr(settings.api_key),
            )
        },
        models={
            settings.model: LLMModel(
                provider="kimi",
                model=settings.model,
                max_context_size=settings.max_context_size,
                capabilities={"image_in", "thinking"},
            )
        },
    )


def fetch_models() -> List[tuple[str, Optional[str]]]:
    """Model dropdown choices from the Kimi CLI config's `models` table.

    kimi-agent-sdk has no API to enumerate provider models, but the user
    already declares every usable model in their Kimi config file (the CLI
    validates `default_model` against it). We surface those alongside a
    "Default (Kimi)" entry that keeps the config's own `default_model`.

    When an API key is set in SciQLop settings, the whole Config is built
    from settings instead, so the only valid choice is the settings model.
    """
    choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    if not _SDK_AVAILABLE:
        return choices
    from .settings import KimiSettings

    settings = KimiSettings()
    if settings.api_key:
        return [(f"{settings.model} (Kimi settings)", None)]
    try:
        from kimi_cli.config import load_config
        cfg = load_config()
    except Exception:
        return choices
    for name in cfg.models:
        if name and name != cfg.default_model:
            choices.append((name, name))
    return choices


def _tool_class_name(tool_name: str) -> str:
    return f"SciqlopTool_{tool_name}"


def _params_model(tool_name: str, schema: dict):
    """Build a pydantic model for a tool's JSON input_schema.

    Only flat typed properties are mapped (that is all SciQLop tools use);
    anything unrecognized degrades to a string, matching how the model
    serializes its arguments anyway.
    """
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    fields: Dict[str, Any] = {}
    for prop, spec in properties.items():
        spec = spec if isinstance(spec, dict) else {}
        py_type = _JSON_TYPE_MAP.get(spec.get("type"), str)
        description = spec.get("description", "")
        if prop in required:
            fields[prop] = (py_type, Field(description=description))
        else:
            fields[prop] = (Optional[py_type], Field(default=None, description=description))
    return create_model(f"{_tool_class_name(tool_name)}_params", **fields)


def _register_tool_class(backend: "KimiBackend", tool: dict) -> None:
    """Create a CallableTool2 subclass for a SciQLop tool and publish it as a
    module attribute, so kimi-cli's tool loader (`importlib.import_module` +
    `getattr`) can resolve its `module:ClassName` path from the agent file.

    The class must not override `__init__`: kimi-cli's loader treats an
    overridden constructor as a request for dependency injection and fails on
    annotations it does not know. Class attributes carry name/description/
    params instead, which `CallableTool2.__init__` picks up.
    """
    name = tool["name"]

    async def __call__(self, params):
        return await backend._run_tool(tool, params)

    cls = type(_tool_class_name(name), (CallableTool2,), {
        "name": name,
        "description": tool["description"],
        "params": _params_model(name, tool.get("input_schema") or {}),
        "__call__": __call__,
        "__module__": __name__,
    })
    setattr(sys.modules[__name__], _tool_class_name(name), cls)


def _to_output(result: Any):
    """Convert a SciQLop tool result into a kimi ToolOk output.

    Handlers return MCP-style dicts: {"content": [{"type": "text", ...},
    {"type": "image", "data": <b64>, "mimeType": ...}]}. Images become
    data-URI ImageURLParts so the model actually sees the screenshot.
    """
    if isinstance(result, dict) and "content" in result:
        parts = []
        for item in result["content"]:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                parts.append(TextPart(text=item.get("text", "")))
            elif item.get("type") == "image":
                data = item.get("data")
                if data:
                    mime = item.get("mimeType", "image/png")
                    parts.append(ImageURLPart(
                        image_url=ImageURLPart.ImageURL(url=f"data:{mime};base64,{data}")
                    ))
        if parts:
            if len(parts) == 1 and isinstance(parts[0], TextPart):
                return parts[0].text
            return parts
        return "OK"
    return result if isinstance(result, str) else str(result)


def _mime_for(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "image/png")


def _build_user_input(prompt: str, image_paths: Optional[List[str]]):
    if not image_paths:
        return prompt
    parts = [TextPart(text=prompt)]
    for path in image_paths:
        try:
            data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        except OSError:
            continue
        parts.append(ImageURLPart(
            image_url=ImageURLPart.ImageURL(url=f"data:{_mime_for(path)};base64,{data}")
        ))
    return parts if len(parts) > 1 else prompt


class _KimiStream:
    """Translate kimi-agent-sdk wire messages into SciQLop chat StreamBlocks.

    The wire stream already emits incremental TextPart/ThinkPart deltas
    (unlike opencode's accumulated snapshots), so deltas forward directly as
    incomplete blocks. A block is closed when the other kind interrupts it,
    a tool call arrives, or the turn ends. ToolCall yields the activity
    block; ToolResult yields a result-only activity block that the dock
    merges into the matching call by tool_use_id, plus ImageBlocks for any
    inline screenshots.
    """

    def __init__(self, tempdir: Path):
        self._tempdir = tempdir
        self._open: Optional[type] = None  # TextBlock | ThinkingBlock | None

    def feed(self, msg) -> Iterator[StreamBlock]:
        if isinstance(msg, TextPart):
            yield from self._switch(TextBlock)
            yield TextBlock(text=msg.text, complete=False)
        elif isinstance(msg, ThinkPart):
            yield from self._switch(ThinkingBlock)
            yield ThinkingBlock(text=msg.think, complete=False)
        elif isinstance(msg, ToolCall):
            yield from self._close()
            fn = msg.function
            yield ToolActivityBlock(
                tool_name=getattr(fn, "name", "") or "",
                tool_input=_sessions.parse_tool_args(getattr(fn, "arguments", None)),
                tool_use_id=msg.id or "",
            )
        elif isinstance(msg, ToolResult):
            text, images = _sessions.split_tool_output(msg.return_value)
            for url in images:
                mime, data = _sessions.parse_data_uri(url)
                if not data:
                    continue
                path = write_b64_image(data, mime or "image/png", self._tempdir, prefix="tool")
                if path:
                    yield ImageBlock(path=path)
            yield ToolActivityBlock(tool_use_id=msg.tool_call_id or "", result=text)
        elif isinstance(msg, TurnEnd):
            yield from self._close()

    def flush(self) -> Iterator[StreamBlock]:
        yield from self._close()

    def _switch(self, kind: type) -> Iterator[StreamBlock]:
        if self._open is not None and self._open is not kind:
            yield from self._close()
        self._open = kind

    def _close(self) -> Iterator[StreamBlock]:
        if self._open is not None:
            yield self._open(text="", complete=True)
            self._open = None


class KimiBackend:
    display_name = "Kimi"
    model_choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    supports_sessions = True

    def __init__(self, ctx: BackendContext):
        if not _SDK_AVAILABLE:
            raise RuntimeError(f"kimi-agent-sdk not importable: {_SDK_IMPORT_ERROR}")
        self._main_window = ctx.main_window
        self._tools = list(ctx.tools)
        self._gated_names = {t["name"] for t in ctx.tools if t.get("gated")}
        self._tempdir = Path(ctx.tempdir)
        self._tempdir.mkdir(parents=True, exist_ok=True)
        self._confirm_cb = ctx.confirm_cb
        self._allow_writes = ctx.allow_writes
        self._model: Optional[str] = None
        self._resume: Optional[str] = None
        self._session: Optional[Session] = None
        self._lock = asyncio.Lock()

    def _check_config(self) -> None:
        """Fail with an actionable message when no provider is set up.

        Called lazily from `_ensure_session` (not `__init__`) so the plugin
        still loads and the dock stays usable when auth is missing — the
        error then surfaces as a chat error message on the first prompt,
        which the dock renders, instead of a plugin-load failure.

        The SDK reads the Python Kimi CLI config (~/.kimi/config.toml), not
        the TypeScript Kimi Code one (~/.kimi-code) — a user logged into the
        latter still needs credentials here, either from SciQLop settings or
        from the CLI config.
        """
        import os

        from .settings import KimiSettings

        if KimiSettings().api_key:
            return
        try:
            from kimi_cli.config import load_config
            cfg = load_config()
        except Exception:
            return  # let Session.create surface config problems verbatim
        if not cfg.providers and not os.environ.get("KIMI_API_KEY"):
            raise RuntimeError(
                "No Kimi API key configured — set it in "
                "Settings → Plugins → Kimi, or via the KIMI_API_KEY env var, "
                "or add a provider to ~/.kimi/config.toml."
            )

    async def _ensure_session(self) -> Session:
        if self._session is not None:
            return self._session
        self._check_config()
        config = _settings_config()
        for tool in self._tools:
            _register_tool_class(self, tool)
        agent_file = self._write_agent_files()
        work_dir = KaosPath(str(_sessions.current_workspace_dir()))
        session = None
        if self._resume:
            session = await Session.resume(
                work_dir, self._resume,
                config=config,
                agent_file=agent_file,
                model=self._model or None,
            )
        if session is None:
            session = await Session.create(
                work_dir,
                config=config,
                agent_file=agent_file,
                model=self._model or None,
            )
        self._session = session
        return session

    def _write_agent_files(self) -> Path:
        """Generate the agent spec the SDK loads: only SciQLop tools, with the
        SciQLop system prompt. kimi-cli renders system prompts as Jinja
        templates; SYSTEM_PROMPT carries no template syntax, so it renders
        verbatim."""
        system_md = self._tempdir / "kimi_agent_system.md"
        system_md.write_text(SYSTEM_PROMPT, encoding="utf-8")
        tool_lines = "\n".join(
            f'    - "{__name__}:{_tool_class_name(t["name"])}"' for t in self._tools
        )
        agent_yaml = self._tempdir / "kimi_agent.yaml"
        agent_yaml.write_text(
            "version: 1\n"
            "agent:\n"
            '  name: "sciqlop"\n'
            "  system_prompt_path: ./kimi_agent_system.md\n"
            "  tools:\n"
            f"{tool_lines}\n",
            encoding="utf-8",
        )
        return agent_yaml

    async def ask(
        self, prompt: str, image_paths: Optional[List[str]] = None
    ):
        async with self._lock:
            session = await self._ensure_session()
            stream = _KimiStream(self._tempdir)
            try:
                async for msg in session.prompt(_build_user_input(prompt, image_paths)):
                    if isinstance(msg, ApprovalRequest):
                        # Custom tools never emit these (approval is a tool's
                        # own decision in kimi-cli), but resolve any stray one
                        # so the turn can never block on it.
                        msg.resolve(await self._decide_approval(msg))
                        continue
                    for block in stream.feed(msg):
                        yield block
            except RunCancelled:
                pass
            for block in stream.flush():
                yield block

    async def _decide_approval(self, req) -> str:
        sender = req.sender or ""
        if sender not in self._gated_names:
            return "approve"
        if not self._allow_writes or self._confirm_cb is None:
            return "reject"
        try:
            allowed = await self._confirm_cb(
                sender, {"action": req.action, "description": req.description}
            )
        except Exception:
            return "reject"
        return "approve" if allowed else "reject"

    async def _run_tool(self, tool: dict, params):
        """Tool body invoked by the kimi runtime for a dynamic CallableTool2.

        Gating lives here (Albert pattern): write tools are refused outright
        when writes are disabled, and otherwise confirmed per call with the
        user through the dock's confirm callback.
        """
        name = tool["name"]
        args = params.model_dump(exclude_none=True)
        if name in self._gated_names:
            if not self._allow_writes:
                return ToolError(
                    output="",
                    message=(
                        "write actions are disabled — toggle 'Allow write "
                        "actions' in the SciQLop chat dock"
                    ),
                    brief="Writes disabled",
                )
            if self._confirm_cb is not None:
                try:
                    allowed = await self._confirm_cb(name, args)
                except Exception as e:
                    return ToolError(output="", message=f"approval callback failed: {e}",
                                     brief="Approval failed")
                if not allowed:
                    return ToolError(output="", message="user denied the tool call",
                                     brief="Denied by user")
        try:
            result = tool["handler"](args)
            if asyncio.iscoroutine(result):
                result = await result
            return ToolOk(output=_to_output(result))
        except Exception as e:
            return ToolError(output="", message=f"{type(e).__name__}: {e}",
                             brief="Tool call failed")

    async def reset(self) -> None:
        async with self._lock:
            await self._close_session()
            self._resume = None

    async def cancel(self) -> None:
        # Session.cancel is a synchronous signal; the prompt stream then
        # raises RunCancelled, which ask() swallows after flushing.
        session = self._session
        if session is not None:
            session.cancel()

    async def resume(self, session_id: str) -> None:
        async with self._lock:
            await self._close_session()
            self._resume = session_id

    async def _close_session(self) -> None:
        if self._session is None:
            return
        try:
            await self._session.close()
        except Exception:
            pass
        self._session = None

    async def set_model(self, model: Optional[str]) -> None:
        async with self._lock:
            self._model = model
            # The SDK binds the model at session creation; reconnect on next ask.
            await self._close_session()

    def set_allow_writes(self, allow: bool) -> None:
        self._allow_writes = allow

    async def list_slash_commands(self) -> List[str]:
        # kimi-agent-sdk has no API to enumerate slash commands.
        return []

    def list_sessions(self) -> List[SessionEntry]:
        return _sessions.list_sessions()

    def load_session(self, session_id: str, image_tempdir: Path) -> List[ChatMessage]:
        return _sessions.load_session_messages(session_id, image_tempdir=image_tempdir)
