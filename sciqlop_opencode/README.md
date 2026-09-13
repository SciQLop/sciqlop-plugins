# sciqlop_opencode

Opencode chat dock for SciQLop. Requires the `opencode` CLI (https://opencode.ai) and `opencode auth login` to be run once.

## Finding and installing the CLI

When the chat dock is opened and no `opencode` binary is found, it offers a
one-click install via the npm bundled with SciQLop (same `opencode-ai`
package as `npm i -g`, but into a user-writable folder — no admin rights,
survives SciQLop updates). A WSL-only install is not reachable from native
SciQLop on Windows.

Manual install options per platform:

- macOS: `brew install anomalyco/tap/opencode`
- Linux: `curl -fsSL https://opencode.ai/install | bash`
- Windows: `scoop install opencode`, `choco install opencode`, or `npm i -g opencode-ai`

The plugin looks beyond `PATH` (GUI-launched apps inherit a minimal one):
its own managed install, then `PATH`, then well-known locations such as
`/opt/homebrew/bin` and `~/.opencode/bin`, then a login-shell probe.

## Limitations (opencode-agent-sdk 0.4.x, subprocess ACP)

The opencode SDK exposes a narrower stream than the Claude backend, so some
chat features are intentionally not implemented:

- **Inline tool images / screenshots** — the subprocess stream carries no
  tool-result image, so screenshots taken by tools are sent to the model but
  not rendered in the chat.
- **Thinking** is rendered inline as normal text — the SDK flattens it into the
  same channel as the answer, so it cannot be shown as a separate dimmed block.
- **Mid-turn interrupt**, **live model switching**, and **slash-command listing**
  have no SDK surface; cancelling tears down the connection, model changes apply
  on the next turn, and the slash-command list is empty.
- **User-attached images** are not sent (text-only prompts).
