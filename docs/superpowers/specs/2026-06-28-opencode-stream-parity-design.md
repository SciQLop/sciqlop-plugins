# sciqlop_opencode — streaming correctness + tool-activity parity

**Date:** 2026-06-28
**Status:** Approved (design)
**Scope:** `sciqlop_opencode` plugin only. No changes to `SciQLop.components.agents`
(the shared backend protocol / chat consumer) and no changes to other backends.

## Problem

The `OpencodeBackend` adapts `opencode-agent-sdk` 0.4.12 (subprocess ACP mode) to
SciQLop's `AgentBackend` protocol. Compared with the reference `ClaudeBackend` it
has two defects, both confirmed by running the real SDK message objects through
the real chat consumer (`AgentChatDock._append_block`):

1. **Streamed assistant text is duplicated.** In subprocess-ACP mode the SDK
   streams the *full accumulated text* on every `agent_message_chunk`
   (replace semantics — `acp.py` comment: *"bot does accumulated_text = text,
   not +="*). The SciQLop consumer merges consecutive incomplete `TextBlock`s by
   **appending** (`last.text += block.text`). The current
   `OpencodeBackend._decode_message` forwards each snapshot as a bare
   `TextBlock(text=snapshot)`, so the snapshots concatenate.

   Reproduced — snapshots `["Hello", "Hello world", "Hello world, plotting now."]`
   render as `'HelloHello worldHello world, plotting now.'` instead of
   `'Hello world, plotting now.'`.

2. **Tool activity is never shown.** `_decode_message` only handles `TextBlock`;
   it drops `ToolUseBlock`. The collapsible tool-activity log is always empty for
   opencode, whereas Claude shows every tool call. Reproduced — a `ToolUseBlock`
   produces zero blocks.

## SDK facts (opencode-agent-sdk 0.4.12, subprocess ACP — `_internal/acp.py`)

The stream SciQLop actually receives:

- `agent_message_chunk` → `AssistantMessage(content=[TextBlock(text=<full buffer>)])`
  — accumulated snapshot, emitted repeatedly as the buffer grows.
- `tool_call_update` with status `completed`/`failed` →
  `AssistantMessage(content=[ToolUseBlock(id, name, input)])` — emitted **once**,
  at completion. There is no separate tool-result message and no tool output in
  subprocess mode.
- `agent_thought_chunk` → `AssistantMessage(content=[TextBlock(text=<delta>)])`
  — thinking is flattened into the *same* channel as the answer; the backend
  cannot distinguish it from response text.
- `plan` → `SystemMessage(subtype="plan", ...)`.
- end of turn → final `AssistantMessage` (flushed buffer) then `ResultMessage`.

No SDK surface exists for: tool-result images, a distinct thinking type, mid-turn
interrupt, live `set_model`, slash-command listing, or user-attached image input.
These remain out of scope (see below).

## Design

Introduce a small **stateful stream translator** that converts a sequence of
opencode SDK messages into SciQLop `StreamBlock`s. It is the single owner of the
snapshot→delta logic and is a pure unit — no SDK client, no Qt, no I/O — so it is
testable in isolation, the same way `test_backend_hook.py` tests the permission
hook today.

### Unit: `_OpencodeStream` (in `sciqlop_opencode/backend.py`)

State: `_acc: str` (text already emitted for the currently open text block) and
`_open: bool` (an incomplete `TextBlock` is open in the consumer).

```
feed(message) -> Iterator[StreamBlock]      # call per received message
flush()       -> Iterator[StreamBlock]      # call once, after the stream ends
```

`feed`:
- `AssistantMessage`: for each content block, in order —
  - `ToolUseBlock` → first `_close_text()` (so the open paragraph ends cleanly),
    then emit `ToolActivityBlock(tool_name=name.split("__")[-1],
    tool_input=input or {}, tool_use_id=id or "")`.
  - `TextBlock` → `_emit_text(snapshot)`.
- `SystemMessage`, `ResultMessage`, anything else → no blocks.

`_emit_text(snapshot)`:
- `snapshot == _acc` → emit nothing (duplicate snapshot).
- `snapshot.startswith(_acc)` → `delta = snapshot[len(_acc):]`; `_acc = snapshot`;
  `_open = True`; emit `TextBlock(text=delta, complete=False)`.
- otherwise (buffer reset, e.g. a new segment after a tool, or a thought delta) →
  `_close_text()`, then `_acc = snapshot`; `_open = True`; emit
  `TextBlock(text=snapshot, complete=False)`.

`_close_text()`:
- if `_open`: emit `TextBlock(text="", complete=True)` to mark the open block
  done; reset `_acc = ""`, `_open = False`. Otherwise emit nothing.

`flush()`: `_close_text()`.

### Wiring: `OpencodeBackend.ask`

Replace the per-message `_decode_message` call (and remove that method) with one
translator per turn:

```
stream = _OpencodeStream()
async for message in client.receive_response():
    for block in stream.feed(message):
        yield block
for block in stream.flush():
    yield block
```

Everything else in `ask` (lock, `_ensure_client`, query) is unchanged.

## Data flow

opencode subprocess → SDK `receive_response()` →
`AssistantMessage`/`SystemMessage`/`ResultMessage` → `_OpencodeStream` →
`TextBlock`(delta) / `ToolActivityBlock` → `AgentChatDock._append_block` →
`ChatMessage.blocks` → `TranscriptView`.

The consumer invariant the translator relies on: while `_open` is true, the
consumer's last block is exactly the `TextBlock` we are extending, because the
only blocks we interleave are (a) more text for the same block, or (b) a
`ToolActivityBlock`, which is always preceded by `_close_text()`.

## Error handling

- The translator never raises on shape: missing/`None` fields default to `""`/`{}`.
- `ask` keeps its existing `asyncio.Lock`; SDK/transport errors propagate to the
  dock, which already renders them as an error message (unchanged).
- A `failed` tool still surfaces as a `ToolActivityBlock` (the call is shown; no
  result text is available in subprocess mode).

## Testing (reproducer-first)

Pure tests against `_OpencodeStream`, no live opencode CLI/SDK required —
construct `AssistantMessage`/`ToolUseBlock`/`TextBlock`/`SystemMessage`/`ResultMessage`
from `opencode_agent_sdk.types` and assert the emitted block sequence:

1. **No duplication (the regression reproducer):** growing snapshots →
   incremental deltas whose concatenation equals the last snapshot.
2. **Duplicate snapshot:** repeating the same snapshot emits nothing the second time.
3. **Tool call:** text snapshot then `ToolUseBlock` → open text closed
   (`complete=True`) then `ToolActivityBlock` with `tool_name` stripped of the
   `mcp__sciqlop__` prefix, correct `tool_input` and `tool_use_id`.
4. **Post-tool text:** a snapshot after a tool starts a fresh `TextBlock`
   (not appended to the pre-tool text).
5. **flush:** a dangling open block is closed by `flush()`.
6. **Non-text messages:** `SystemMessage` and `ResultMessage` yield no blocks.

A coarse end-to-end check (optional, mirrors the design's reproduction) feeds the
sequence through `_OpencodeStream` **and** a copy of `_append_block` to assert the
final `ChatMessage` text and block types — guarding the consumer-contract
assumption, not just the translator in isolation.

## Out of scope (SDK-blocked — documented in code + README)

- Inline tool **images / screenshots**: subprocess ACP carries no tool-result
  image. Deferred by decision; revisit only with an out-of-band tool-handler path.
- **Thinking** as a distinct dimmed block: indistinguishable from answer text in
  this SDK; renders inline as text.
- Mid-turn **interrupt**, live **set_model**, **slash commands**, user-attached
  **image input**: no SDK surface. Existing best-effort behavior is kept.
- The Claude backend's temporary `DESYNC-PROBE` logging is **not** ported.

## Non-goals

No migration to the official `opencode-ai` REST SDK (alpha, HTTP-only — cannot
host SciQLop's in-process tools). Noted as a possible future direction only.
