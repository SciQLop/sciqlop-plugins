# sciqlop-claude

Embedded Claude chat dock for SciQLop.

Uses the [Claude Agent SDK](https://docs.claude.com/en/api/agent-sdk/overview),
which spawns the `claude` CLI as a subprocess. Credentials come from the user's
existing Claude Code OAuth login — **no API key required**.

## Requirements

- A SciQLop workspace with `claude-agent-sdk` installed (handled by this
  plugin's dependencies).
- The `claude` CLI installed on PATH and logged in:
  ```bash
  # one-time
  uv tool install claude-code
  claude login
  ```

## Install

Inside a SciQLop workspace:

```bash
uv pip install -e /path/to/plugins_sciqlop/sciqlop_claude
```

Or via the SciQLop app store once this plugin is bundled in the registry.

## Usage

`Tools → Claude Chat` opens the dock (or use the toolbar toggle). The plugin
exposes three read-only tools to the model by default:

- `sciqlop_window_state` — high-level snapshot of the main window
- `sciqlop_list_panels` — all open plot panels with time ranges
- `sciqlop_active_panel` — the currently active panel's products + time range

Flip **Allow write actions** in the dock header to unlock write tools
(`sciqlop_set_time_range` for now). Writes stay off by default.

## Development notes

- `agent.py` runs on the qasync event loop; don't wrap it in a `QThread`.
- All tool handlers use `@on_main_thread` from `SciQLop.user_api.threading`.
- Conversation state lives on the dock widget. Closing the dock keeps the
  session; "New session" resets it explicitly.
