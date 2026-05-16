# sciqlop_opencode plugin — design

**Date:** 2026-05-16
**Branch:** feat/sciqlop-radio (will branch off main as `feat/sciqlop-opencode`)

## Goal

Add a fourth AI-agent backend to the SciQLop plugin bundle: **opencode**, the open-source coding agent (sst/opencode). Feature-parity with `sciqlop_claude` — live tool calls into SciQLop's Qt main process, gated write actions, session resume, model dropdown — but routed through opencode's agent loop instead of Claude Code's.

## Integration path

Use `opencode-agent-sdk` (community Python package, drop-in for `claude_agent_sdk`). It exports the same primitives we already rely on:

- `SDKClient` ↔ `ClaudeSDKClient`
- `AgentOptions` ↔ `ClaudeAgentOptions`
- `create_sdk_mcp_server` — in-process MCP server registration
- `@tool` decorator — Python functions exposed as MCP tools

Subprocess mode (default): the SDK spawns `opencode acp` over stdio JSON-RPC. No HTTP server lifecycle in our process. Tool handlers run **in-process** in SciQLop's Python interpreter, so live Qt state is reachable without IPC.

Other paths considered and rejected:
- **ACP via `agent-client-protocol` Python SDK** — cleaner protocol semantics but no in-process tool dispatch; would require a separate-process MCP server with a loopback channel into SciQLop. Kept as fallback if opencode-agent-sdk's permission hooks turn out to be unworkable.
- **HTTP `opencode serve` + stdio MCP bridge** — same in-process-tool problem as ACP, less elegant protocol.
- **Plain HTTP, no custom tools** — agent can't see panels/products/screenshots; unusable.

## Auth & runtime requirements

The plugin delegates auth entirely to the opencode CLI. The user runs `opencode auth login` once (or sets provider env vars opencode reads); the plugin contributes no API-key field of its own. This mirrors `sciqlop_claude` trusting the `claude` CLI for OAuth.

Hard requirements at plugin load:
1. `opencode` CLI on `PATH` — checked via `shutil.which("opencode")`. If absent, backend raises with a clear "install opencode CLI" message, and the dock shows it as unavailable.
2. `opencode-agent-sdk` importable — pinned in `plugin.json` `python_dependencies`. If import fails, same shape as `sdk_available()` in the Claude plugin.

Provider auth (Anthropic/OpenAI/etc.) failures only surface at first `ask()`; the streaming loop catches and emits a `TextBlock` hinting "run `opencode auth login`".

## Plugin layout

New sibling plugin alongside `sciqlop_claude/`, `sciqlop_copilot/`, `sciqlop_albert/`:

```
sciqlop_opencode/
├── pyproject.toml              # sciqlop.plugins entry point
└── sciqlop_opencode/
    ├── __init__.py             # PluginInfo, agents-registry registration
    ├── plugin.json             # SciQLop folder-based discovery manifest
    ├── backend.py              # OpencodeBackend (~AgentBackend impl)
    ├── sessions.py             # opencode session/message JSON parsing
    └── resources/              # icon
```

Follows the existing per-plugin layout convention (independent pyproject + plugin.json, no shared base class across backends).

## Backend class

`OpencodeBackend` is a clone of `ClaudeBackend` (sciqlop_claude/backend.py) with three substantive adaptations.

### 1. SDK imports and class init

```python
from opencode_agent_sdk import (
    AgentOptions, SDKClient, create_sdk_mcp_server, tool as sdk_tool,
)
```

`display_name = "Opencode"`, `supports_sessions = True`, `model_choices` starts with `[("Default (opencode)", None)]` and is replaced at module load by `fetch_models()`.

`__init__(ctx: BackendContext)` stores the usual fields: tools, gated names, tempdir, `confirm_cb`, `allow_writes`, main window. Sets `_client=None`, `_model=None`, `_resume=None`, `_slash_cache=None`, an `asyncio.Lock` for serializing client lifecycle.

### 2. `_ensure_client` — MCP server, hooks, AgentOptions

```python
async def _ensure_client(self) -> SDKClient:
    if self._client is not None:
        return self._client
    sdk_tools = [_wrap_tool(t) for t in self._tools]
    server = create_sdk_mcp_server(name=_MCP_SERVER_NAME, tools=sdk_tools)
    allowed = [f"mcp__{_MCP_SERVER_NAME}__{t['name']}" for t in self._tools]
    options = AgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={_MCP_SERVER_NAME: server},
        allowed_tools=allowed,
        hooks={"PreToolUse": [self._pre_tool_use_hook]},
        model=self._model,
        resume=self._resume,
        cwd=str(_sessions.current_workspace_dir()),
        # server_url unset -> subprocess mode (spawns `opencode acp`)
    )
    self._client = SDKClient(options=options)
    await self._client.connect()
    return self._client
```

`_wrap_tool` is a near-verbatim copy of `sciqlop_claude`'s helper, using the opencode SDK's `@tool` decorator.

### 3. Permission gating via `PreToolUse` hook

Replaces `can_use_tool` from claude-agent-sdk. Same three-branch logic:

```python
def _pre_tool_use_hook(self, input_data, tool_use_id, context):
    tool_name = input_data["tool_name"]
    short = tool_name.split("__")[-1]
    if short not in self._gated_names:
        return None  # allow (no decision = proceed)
    if not self._allow_writes:
        return {"hookSpecificOutput": {
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "write actions disabled — toggle 'Allow write actions' in the SciQLop chat dock"
            ),
        }}
    # gated + writes allowed: ask the user
    allowed = self._call_confirm_cb_sync(short, input_data["tool_input"])
    return {"hookSpecificOutput": {
        "permissionDecision": "allow" if allowed else "deny",
        "permissionDecisionReason": "user approval" if allowed else "user denied",
    }}
```

#### Open risk: sync hook vs async confirm_cb

`confirm_cb` is an async coroutine — it shows a modal dialog and yields while the user decides. Public opencode-agent-sdk examples show the hook as a sync function. Two outcomes when we read the SDK source at implementation time:

- **If hooks accept async functions:** make the hook `async def`, `await self._confirm_cb(...)` directly. Same shape as Claude plugin.
- **If hooks are strictly sync:** the hook runs on the SDK's reader thread, the GUI lives on qasync's loop. Bridge via `asyncio.run_coroutine_threadsafe(self._confirm_cb(...), self._qasync_loop).result()`. The hook thread blocks while the Qt modal runs on the main loop. Need to verify this doesn't deadlock (it shouldn't — qasync loop is live and independent of the SDK reader thread).

If neither works, fall back to the ACP path (`agent-client-protocol` + `opencode acp`). This is the one risk that could derail the clone-and-adapt effort estimate.

### 4. Streaming, lifecycle, slash commands

`ask`, `reset`, `cancel`, `resume`, `set_model`, `set_allow_writes`, `list_slash_commands`, `_decode_message`, `_tool_result_blocks`, `_build_user_stream` — all clone verbatim from `sciqlop_claude/backend.py`. The SDK's `client.receive_response()` is documented to yield the same `AssistantMessage`/`UserMessage` shapes (drop-in promise), so `_decode_message` works unchanged. Verify at implementation; if shapes differ, adapt the field accesses.

`list_slash_commands()` calls `client.get_server_info()`. If opencode exposes commands, surface them; otherwise return `[]`.

`cancel()` tries `client.interrupt()` first, falls back to `_disconnect()` — same pattern as Claude.

### 5. System prompt

Clone `SYSTEM_PROMPT` from Claude plugin. Two tweaks:
- Drop "MCP server called 'sciqlop'" phrasing — opencode users see tools as plain tools, not as "MCP".
- Adjust the tool naming hint (the `mcp__sciqlop__` prefix may or may not surface to the model depending on SDK behavior; verify and adapt).

Keep the worked plot workflow, the read-vs-write tool table, and the panel-naming discipline — those are SciQLop-domain instructions, not Claude-specific.

## sessions.py

Walks the opencode storage tree under `${OPENCODE_DATA_DIR:-~/.local/share/opencode}/storage/`:

```
session/<projectHash>/<sessionID>.json   # session metadata
message/<sessionID>/msg_*.json           # per-message content
```

### `current_workspace_dir()`

Returns SciQLop's active workspace path. Reuse or duplicate the helper from `sciqlop_claude.sessions` — they share semantics.

### `list_sessions() -> list[SessionEntry]`

Strategy: list all session JSON files, parse each for `(label, mtime, cwd)`, **filter to those whose cwd matches the current workspace**. Avoids depending on opencode's projectHash hashing scheme, which is undocumented and could change. If a session JSON omits cwd, fall back to including it ungated rather than dropping it.

Sort by mtime descending. Cap at ~50 entries to keep the menu sane.

### `load_session_messages(session_id, image_tempdir) -> list[ChatMessage]`

Reads `message/<sessionID>/msg_*.json` in lexicographic order (filenames carry monotonic message IDs). Decodes each message's content blocks into `ChatMessage`:
- text blocks → `TextBlock(text=...)`
- image blocks → `write_b64_image(..., image_tempdir, prefix="session")` → `ImageBlock(path=...)`
- tool-call / tool-result blocks → either fold into the assistant turn as text annotations, or skip — matches whatever sciqlop_claude.sessions does for tool results (verify and mirror)

Errors during a single message file → log warning, skip that message, continue. Don't fail the whole session load on one corrupt file.

## Model discovery

`fetch_models(timeout=10.0)` runs at module import (same as Claude plugin):

```python
def fetch_models(timeout=10.0) -> list[tuple[str, Optional[str]]]:
    if not _SDK_AVAILABLE or not opencode_cli_available():
        return [("Default (opencode)", None)]

    async def _run():
        async with SDKClient(options=AgentOptions()) as client:
            info = await client.get_server_info() or {}
            return info.get("models") or []

    def _blocking():
        return asyncio.run(asyncio.wait_for(_run(), timeout=timeout))

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            raw = pool.submit(_blocking).result(timeout=timeout + 2.0)
    except Exception:
        return [("Default (opencode)", None)]

    # turn raw entries into (label, model_id) tuples; default -> None
    ...
```

Worker thread mandatory: qasync's loop is already running when the plugin loads, so a top-level `asyncio.run` would raise.

If `get_server_info()` doesn't return models (depends on SDK surface), fall back to a static list of opencode's documented providers. Decide at implementation.

## Error handling

| Failure | Behavior |
|---|---|
| `opencode` CLI missing | `OpencodeBackend.__init__` raises `RuntimeError("opencode CLI not found — install from opencode.ai")`; backend marked unavailable in the dock |
| `opencode-agent-sdk` not importable | Raise in `__init__`; `sdk_available()` exposed for the dock to query at registration |
| Provider auth missing | SDK error propagates out of `ask()`; dock surface renders it as a chat-visible error (same shape as Claude plugin). User reads the message and runs `opencode auth login` |
| Subprocess crash mid-stream | Exception propagates from `ask()`; on next call `_ensure_client` rebuilds the connection |
| `resume=<id>` references stale/missing session | Catch in `_ensure_client`, log warning, clear `_resume`, start fresh |
| Permission hook deadlock (sync hook + async confirm_cb) | Caught at design time — see Open Risk above |
| Tool handler raises | Same shape as other backends: error string returned to the model as the tool result, no crash |

## Testing

Mirror `sciqlop_albert/tests/`:

- `test_sessions.py` — fixture session+message JSON files in tmpdir; assert `list_sessions()` returns the right entries sorted by mtime, filters by workspace cwd; assert `load_session_messages()` reconstructs text/image blocks correctly; assert corrupt-file tolerance.
- `test_backend.py` — instantiate `OpencodeBackend` with a fake `SDKClient` (monkeypatch the constructor). Drive `ask()` with canned message sequences, assert correct `StreamBlock` emission. Assert `_pre_tool_use_hook` returns deny for gated tools when `allow_writes=False`, deny when `confirm_cb` returns False, allow when both are True. Assert ungated tools always allowed.
- `test_plugin_metadata.py` — `plugin.json` parses, entry point resolves, `python_dependencies` lists the SDK with a version pin.

No integration tests against a real `opencode` binary — manual smoke testing during development.

## Out of scope (deferred)

- Sharing code between Claude/opencode backends — clone-and-adapt now, extract later if a third SDK-shaped backend lands ("rule of three").
- HTTP-mode operation (talking to a pre-existing `opencode serve`). Subprocess mode is enough for the embedded dock use case.
- Custom opencode plugins / per-project agent files (`.opencode/` config). Users configure opencode globally; SciQLop respects whatever they set.
- API-key field in the SciQLop settings panel. opencode CLI auth only.

## Effort estimate

~1–1.5 days of mostly-mechanical clone work, plus ~half a day buffer for the permission-hook risk. If that risk realizes as "neither sync nor async hook can call into Qt", pivot to ACP path is another ~2–3 days.

## Success criteria

- Backend appears in the dock dropdown alongside Claude/Copilot/Albert when `opencode` CLI + SDK are present.
- User can ask a question and get a streamed reply.
- Tool calls (`sciqlop_products_tree`, `sciqlop_screenshot_panel`, etc.) execute against live SciQLop state.
- Gated tools (`sciqlop_exec_python`, write tools) prompt the user via the existing confirm modal when `allow_writes=True`, refused otherwise.
- Past sessions appear in the session menu, can be resumed.
- Model dropdown shows live models or a sensible default.
- Unit tests pass; manual smoke test against a real opencode install succeeds.
