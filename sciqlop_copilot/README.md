# sciqlop-copilot

GitHub Copilot Chat backend for SciQLop's agent dock.

Uses the same endpoint that `copilot.vim`, `CopilotChat.nvim`, JetBrains and
VS Code's Copilot plugin all use (`api.githubcopilot.com`). Sign-in happens
via the standard GitHub **OAuth device flow** — no API key to paste, no
Copilot Enterprise quirks, no extra proxy.

> ⚠️ This endpoint is not officially documented by GitHub. It has been
> stable for years and is what every major third-party Copilot client
> talks to, but GitHub could change it at any time.

## Requirements

- An active **GitHub Copilot** subscription (Individual or Business — the
  plugin reads the per-account API shard from the token response, so both
  work).
- SciQLop ≥ 0.12.0.

## Install

Inside a SciQLop workspace:

```bash
uv pip install -e /path/to/plugins_sciqlop/sciqlop_copilot
```

## Usage

1. `Tools → GitHub Copilot…` — shows your current sign-in status. If
   you're not signed in, click **Sign in…** — a device-code dialog opens,
   you authorize in your browser, and it closes itself. To disconnect
   later, open the same menu entry and click **Sign out**.
2. `Tools → Agent Chat` — opens the shared Agents dock. Pick
   **GitHub Copilot** from the backend dropdown and any model from
   the model dropdown.

**You only sign in once.** The long-lived GitHub OAuth token is saved in
your system keyring (`sciqlop_copilot / github_token`) and survives
restarts; GitHub device-flow tokens don't auto-expire. On every SciQLop
launch the plugin silently exchanges it for a fresh 30-min Copilot token
— no user action. The only time you re-sign-in is if you explicitly sign
out or GitHub/you revoke the authorization.

## Models

The model dropdown is populated from `GET /models` at sign-in, filtered to
entries with `capabilities.type == "chat"`. Typical subscriptions return
several dozen chat-capable models (Claude, GPT, Gemini families).

## Dev notes

- `auth.py` has no SciQLop/Qt deps — the unit tests mock `httpx` and can
  run in any Python env with `httpx` and `pytest` installed.
- The client ID (`Iv1.b507a08c87ecfe98`) is the public copilot.vim
  identifier, same one used by the Neovim and JetBrains plugins.
- On sign-in, the Copilot token response includes `endpoints.api` — use
  that value rather than hardcoding a base URL. Individual plans return
  `https://api.individual.githubcopilot.com`; business plans return a
  different host.
- Required request headers: `Authorization: Bearer <copilot_token>`,
  `Copilot-Integration-Id: vscode-chat`, `Openai-Intent: conversation-panel`,
  plus the editor-identification headers.

## Running tests

```bash
PYTHONPATH=sciqlop_copilot python -m pytest sciqlop_copilot/sciqlop_copilot/tests/
```

The test conftest stubs `PySide6QtAds` and the `SciQLop.*` modules only if
they aren't importable, so the suite also runs inside a full SciQLop
workspace without clobbering real installs.
