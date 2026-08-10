# SciQLop OpenCode Plugin — ACP Direct Migration

**Date:** 2026-08-10 (rewrite — supersedes the first draft)
**Status:** Design, capabilities verified against `opencode acp` 1.18.15

## Problem

The plugin drives the unofficial `opencode-agent-sdk`, which:

1. **Flattens thinking and answer text** — `agent_thought_chunk` and
   `agent_message_chunk` both become `AssistantMessage(TextBlock(...))`
   (`_internal/acp.py:356-365` and `:428-437`), so `receive_response()` cannot
   tell reasoning from response and chain-of-thought leaks into the answer.
2. **Yields growing snapshots** — the plugin diffs accumulated text back into
   deltas, then re-buffers it at word boundaries to stop the transcript
   flickering (`_OpencodeStream`, ~110 lines of pure workaround).
3. **Duplicates infrastructure** — subprocess lifecycle, MCP tool bridging,
   permissions and session handling are all reimplemented, and each needs its
   own schema fixups (`_reorder_required_first`, `_normalize_schema_types`)
   to survive the SDK's `inspect.Signature` bridge.

Net: fragmented rendering, visible chain-of-thought, ~400 lines of workaround.

## Goal

Rewrite on SciQLop's shared `AcpAgentBackend` (`SciQLop.components.agents.acp`),
speaking ACP directly to `opencode acp` — the same path `sciqlop_kimi` takes in
51 lines.

## Architecture

```
before                             after
──────                             ─────
AgentChatDock                      AgentChatDock
   │                                  │
OpencodeBackend (AgentBackend)     OpencodeBackend (AcpAgentBackend)
   │                                  │
opencode-agent-sdk (SDKClient)     acp.connect_to_agent + AcpClientHandler
   │                                  │
subprocess `opencode acp`          subprocess `opencode acp`
```

`AgentMessageChunk` and `AgentThoughtChunk` are distinct types in the official
`agent-client-protocol` package, so `AcpStreamTranslator` renders thinking dim
and the answer normally, with no snapshot diffing. Tool serving, permission
gating, session list/resume/replay, slash commands and image prompts are all
inherited.

## What `opencode acp` actually supports

Probed live (opencode 1.18.15) rather than assumed — this corrects three claims
in the first draft.

`initialize` reports:

```json
{"loadSession": true,
 "promptCapabilities": {"image": true, "embeddedContext": true},
 "mcpCapabilities":   {"http": true, "sse": true, "acp": false},
 "sessionCapabilities": {"list": {}, "fork": {}, "resume": {}, "close": {}}}
```

`session/new` returns `configOptions`:

| id | type | contents |
|---|---|---|
| `model` | select | 26 entries here, **already filtered to the providers the user is authenticated for**; values (`opencode-go/glm-5.2`, …) are exactly what `session/set_config_option` accepts |
| `effort` | select | `low` / `medium` / `high` |
| `agent` | select | `build`, `plan`, … |

`session/list` (cwd-scoped) returned 8 sessions with `title` and `updatedAt`;
`session/load` replays them.

A real turn (`prompt` → `end_turn`) produced:

```
AgentThoughtChunk   '\n' / 'The' / ' user wants me' / ' to reply with exactly' …
AgentMessageChunk   'The quick brown fox' / ' jumps over the lazy' / ' dog.'
UsageUpdate         {'used': 14499, 'size': 1000000, 'cost': {'amount': 0.0, 'currency': 'USD'}}
```

So: reasoning arrives on its own channel (the entire premise of this migration),
and **chunks are deltas, not accumulated snapshots** — the accumulation the SDK
exposed was its own `_text_buffer`. `AcpStreamTranslator` therefore applies
unchanged, with no diffing and no word-boundary re-buffering. (The note at
`acp/stream.py:9` claiming opencode streams snapshots was written from the SDK's
behaviour and has been corrected.)

Consequences:

- **Models are exposed over ACP.** The first draft said they were not. The
  models.dev cache + `auth.json` parsing in `sessions.py` reimplements
  filtering opencode already does, and can drift from it.
- **Sessions work over ACP.** No SQLite reading, and the base class's replay
  keeps thinking and tool calls, which the SQLite path deliberately dropped.
- **HTTP MCP is supported**, so `SciqlopToolServer` attaches unchanged.

## Design

### `backend.py` — the whole plugin

```python
from SciQLop.components.agents.acp import AcpAgentBackend

class OpencodeBackend(AcpAgentBackend):
    display_name = "Opencode"
    model_choices: List[tuple[str, Optional[str]]] = [("Default (opencode)", None)]
    supports_sessions = True
    cli_label = "opencode"

    def acp_command(self) -> List[str]:
        return ["opencode", "acp"]
```

`check_prerequisites()` needs no override — the base already does
`shutil.which(acp_command()[0])` and names `cli_label`. Override it only to add
the `opencode auth login` hint to the error message.

`__init__.py` follows Kimi: `fetch_models()` → `OpencodeBackend.model_choices`,
then `register_agent_backend` + `ensure_agent_dock`. No UI is contributed —
the chat dock is owned by SciQLop core.

### Model discovery

The dropdown is built at plugin load, before any session exists, so
`configOptions` is not yet available. Two ways out:

- **(chosen) Spawn a throwaway `opencode acp`**, `session/new`, read the `model`
  option list, kill it. Costs ~1 s and one subprocess at plugin load, and is
  authoritative — it inherits opencode's own provider filtering and never
  drifts. `acp/sessions.py::_spawn_agent` already does exactly this shape for
  `list_sessions`; add a shared `acp_config_options(command)` helper next to it
  so Kimi can drop its `config.toml` parsing later too.
- Keep parsing `~/.cache/opencode/models.json` + `auth.json` (~200 lines,
  duplicated filtering logic, drifts).

Fallback on any failure: the single `("Default (opencode)", None)` entry, which
lets opencode pick its own default.

`set_model` needs no work — the base issues
`set_config_option(config_id="model", value=…)`, and the dropdown values are
already the accepted ones. Values not in the enumerated list are rejected
(`-32602 Invalid params: model not found`), so the dropdown must come from the
agent, never be hand-built.

### Guidance (replaces `SYSTEM_PROMPT`)

Deleting `SYSTEM_PROMPT` is a behaviour loss, not a cleanup: ACP has no
system-prompt channel. The replacement is the workspace `AGENTS.md` published
by SciQLop core (`SciQLop/components/agents/guidance.py`) — opencode loads the
project `AGENTS.md` from its cwd, which is the SciQLop workspace directory. See
`SciQLop/docs/design-workspace-agents-md.md`; that wiring is a core-side
prerequisite for this migration landing without a regression in behaviour.

### Files

**Delete:** `_OpencodeStream`, `_wrap_tool`, `_reorder_required_first`,
`_normalize_schema_types`, `SYSTEM_PROMPT`, `_split_provider_model`, all SDK
imports and availability checks, and **all of `sessions.py`** (SQLite listing,
replay, `configured_providers`, `configured_models`, `known_session_models`,
the duplicated `current_workspace_dir`).

**Keep:** `plugin.json`, `README.md`, a `fetch_models()` reduced to the
config-options query.

### Tests

- Remove `test_stream.py`, `test_ask_streaming.py`, `test_backend_hook.py` —
  all three test SDK-shaped behaviour that no longer exists.
- Replace `test_sessions.py` / `test_backend_models.py` with a `fetch_models()`
  test (mocked config-options response: label formatting, default entry,
  graceful empty on failure).
- Add `test_opencode_acp.py`: `acp_command()` is `["opencode", "acp"]`,
  `check_prerequisites()` raises with an actionable message when the CLI is
  absent, class attributes satisfy the `AgentBackend` protocol.
- Keep `test_plugin_metadata.py`.
- `sciqlop_kimi/sciqlop_kimi/tests/` is the template for the whole layout.

### Dependencies

The first draft's `acp>=0.1.0` is wrong twice: the distribution is
`agent-client-protocol`, and SciQLop already depends on it. Mirror Kimi in both
`pyproject.toml` and `plugin.json`:

```toml
dependencies = [
    "SciQLop>=0.13.0,<0.14.0",          # the acp layer ships in 0.13
    "agent-client-protocol>=0.12.0",
    "mcp>=1.19.0,<2",                   # <1.19 mangles CallToolResult; 2.0 drops the low-level decorators
    "uvicorn>=0.30.0",                  # SciqlopToolServer is HTTP MCP
]
```

**Remove:** `opencode-agent-sdk`. Note the SciQLop floor moves 0.12 → 0.13.

## Migration steps

1. Core prerequisite: wire `sync_agents_md` + `BackendContext.guidance`
   (`design-workspace-agents-md.md`), otherwise the persona is lost.
2. Add `acp_config_options(command)` to `SciQLop/components/agents/acp/sessions.py`.
3. Rewrite `backend.py` on `AcpAgentBackend`; rewrite `fetch_models()`.
4. Delete `sessions.py` and the SDK-era tests; update `__init__.py`.
5. Update `pyproject.toml` + `plugin.json` deps and the SciQLop floor.
6. Run the plugin suite, then the SciQLop agent suites.
7. Manual: one real turn — tool call through the HTTP MCP server, a gated tool
   in `confirm` mode, Stop mid-turn, model switch, session resume.

## Risks

| Risk | Status |
|---|---|
| Models not discoverable | **Resolved** — enumerated in `session/new` config options |
| Session list/replay | **Resolved** — `list`/`resume`/`loadSession` all advertised and working |
| HTTP MCP tool server rejected | **Resolved** — `mcpCapabilities.http: true` |
| Streaming shape (snapshots vs deltas) | **Resolved** — deltas, thinking on its own channel; base translator applies as-is |
| Protocol version mismatch | Handled by the `acp` package's negotiation |
| **Tool calls + permission prompts over a real turn** | **Untested** — needs one live turn; the only unverified path |
| Persona lost with `SYSTEM_PROMPT` | Mitigated by workspace `AGENTS.md`, which is weaker than a system prompt (agents frame it as reference data, not instruction) |

## Inherited for free, once the base class grows it

Both belong on `AcpAgentBackend`, not here — each serves every ACP backend:

- **Usage reporting.** The turn above ends with a `UsageUpdate` carrying context
  used/window size and cost, which `_on_update` currently drops on the floor.
  See `SciQLop/docs/design-agent-usage-reporting.md`.
- **`effort` and `agent` config options.** opencode exposes both alongside
  `model`; `effort` lines up with the per-model effort selector from the agent
  session-info work, `agent` (build/plan) has no SciQLop equivalent yet.
