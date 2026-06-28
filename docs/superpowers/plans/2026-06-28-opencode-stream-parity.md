# Opencode Streaming-Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix accumulated-snapshot text duplication and surface tool calls as
activity in the `sciqlop_opencode` backend, via a pure, stateful stream translator.

**Architecture:** A new `_OpencodeStream` class converts the opencode SDK's
message stream (accumulated-text snapshots + `ToolUseBlock`s) into the incremental
`TextBlock`/`ToolActivityBlock` deltas the SciQLop chat consumer expects.
`OpencodeBackend.ask` drives one translator per turn; `_decode_message` is removed.

**Tech Stack:** Python 3.10+, `opencode-agent-sdk` 0.4.12 (subprocess ACP mode),
pytest. Block classes come from `SciQLop.components.agents.chat`.

## Global Constraints

- Changes confined to the `sciqlop_opencode` package — **do not** modify
  `SciQLop.components.agents` (shared protocol/consumer) or any other backend.
- Do **not** touch `sciqlop_claude/sciqlop_claude/backend.py` (uncommitted WIP).
- Do **not** port the Claude backend's `DESYNC-PROBE` logging.
- The translator is duck-typed on SDK messages/blocks — it must **not** import or
  `isinstance`-check `opencode_agent_sdk` types. It references only the SciQLop
  block classes (`TextBlock`, `ToolActivityBlock`) as module globals, so tests can
  monkeypatch them.
- Tests run from the plugins repo root with:
  `uv run --project /var/home/jeandet/Documents/prog/SciQLop pytest <path> -v`
- Branch: stay on the current `fix/ask-user-question`. Stage only the opencode
  files listed per task — never `git add -A`.

---

## File Structure

- `sciqlop_opencode/sciqlop_opencode/backend.py` — add `_OpencodeStream`; add
  `ToolActivityBlock` to the chat import; rewire `ask`; delete `_decode_message`.
- `sciqlop_opencode/sciqlop_opencode/tests/conftest.py` — add a `QApplication`
  bootstrap so the package imports against real SciQLop classes in a dev venv
  (mirrors `sciqlop_claude/.../tests/conftest.py`).
- `sciqlop_opencode/sciqlop_opencode/tests/test_stream.py` — new; translator unit
  tests + one consumer-contract end-to-end test.
- `sciqlop_opencode/sciqlop_opencode/tests/test_ask_streaming.py` — new;
  `ask()` integration test against a fake SDK client.
- `sciqlop_opencode/README.md` — append a short "Limitations" note.

---

### Task 1: `_OpencodeStream` translator + unit tests

**Files:**
- Modify: `sciqlop_opencode/sciqlop_opencode/tests/conftest.py`
- Create: `sciqlop_opencode/sciqlop_opencode/tests/test_stream.py`
- Modify: `sciqlop_opencode/sciqlop_opencode/backend.py` (imports + new class)

**Interfaces:**
- Produces:
  - `class _OpencodeStream` with:
    - `feed(message) -> Iterator[StreamBlock]` — call per received SDK message.
    - `flush() -> Iterator[StreamBlock]` — call once after the stream ends.
  - Emits `TextBlock(text=<delta>, complete=False)` for streaming text,
    `TextBlock(text="", complete=True)` to close an open text run, and
    `ToolActivityBlock(tool_name=<stripped>, tool_input=<dict>, tool_use_id=<id>)`
    for each completed tool call.

- [ ] **Step 1: Add the QApplication bootstrap to the test conftest**

Prepend this block to `sciqlop_opencode/sciqlop_opencode/tests/conftest.py`,
above the existing `_OPTIONAL` loop (keep the rest of the file unchanged):

```python
try:
    from PySide6.QtWidgets import QApplication

    if isinstance(QApplication, type) and QApplication.instance() is None:
        QApplication([])
except Exception:
    pass
```

Rationale: in a dev venv with real PySide6, importing SciQLop's agents package
needs a live `QApplication`; without this the import aborts (Qt static assert).
In Qt-less CI the import still fails cleanly and gets stubbed as before.

- [ ] **Step 2: Write the failing translator tests**

Create `sciqlop_opencode/sciqlop_opencode/tests/test_stream.py`:

```python
"""`_OpencodeStream` converts opencode's accumulated-snapshot stream into the
incremental TextBlock/ToolActivityBlock deltas the SciQLop chat consumer expects.

Block classes are monkeypatched to lightweight dataclasses because the real ones
live in SciQLop's chat package, which may be stubbed in this test env. SDK message
constructors come from opencode_agent_sdk.types (skipped if absent).
"""
from dataclasses import dataclass, field, is_dataclass

import pytest


@dataclass
class _Text:
    text: str = ""
    complete: bool = False


@dataclass
class _Tool:
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    result: object = None
    tool_use_id: str = ""


def _patch_blocks(monkeypatch):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "TextBlock", _Text)
    monkeypatch.setattr(bk, "ToolActivityBlock", _Tool)
    return bk


def _assistant(sdk, *blocks):
    return sdk.AssistantMessage(content=list(blocks))


def test_growing_snapshots_become_deltas_without_duplication(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    snaps = ["Hello", "Hello world", "Hello world, plotting now."]
    out = []
    for s in snaps:
        out.extend(stream.feed(_assistant(sdk, sdk.TextBlock(text=s))))
    out.extend(stream.flush())
    texts = [b.text for b in out if isinstance(b, _Text)]
    assert "".join(texts) == "Hello world, plotting now."
    assert out[-1] == _Text(text="", complete=True)


def test_duplicate_snapshot_emits_nothing(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    out = []
    for _ in range(2):
        out.extend(stream.feed(_assistant(sdk, sdk.TextBlock(text="Hi"))))
    assert out == [_Text(text="Hi", complete=False)]


def test_tool_call_closes_text_then_emits_activity(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    out = list(stream.feed(_assistant(sdk, sdk.TextBlock(text="Working"))))
    out += list(stream.feed(_assistant(sdk, sdk.ToolUseBlock(
        id="t1", name="mcp__sciqlop__sciqlop_screenshot_panel",
        input={"name": "P1"}))))
    assert out == [
        _Text(text="Working", complete=False),
        _Text(text="", complete=True),
        _Tool(tool_name="sciqlop_screenshot_panel",
              tool_input={"name": "P1"}, result=None, tool_use_id="t1"),
    ]


def test_text_after_tool_starts_fresh_block(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    out = list(stream.feed(_assistant(sdk, sdk.TextBlock(text="Working"))))
    out += list(stream.feed(_assistant(sdk, sdk.ToolUseBlock(
        id="t1", name="sciqlop_create_panel", input={}))))
    out += list(stream.feed(_assistant(sdk, sdk.TextBlock(text="Done"))))
    assert _Text(text="Done", complete=False) in out
    # "Done" is its own delta, never appended onto "Working"
    assert _Text(text="WorkingDone", complete=False) not in out


def test_flush_closes_dangling_block_and_is_idempotent(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    list(stream.feed(_assistant(sdk, sdk.TextBlock(text="partial"))))
    assert list(stream.flush()) == [_Text(text="", complete=True)]
    assert list(stream.flush()) == []


def test_system_and_result_messages_emit_no_blocks(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    bk = _patch_blocks(monkeypatch)
    stream = bk._OpencodeStream()
    out = list(stream.feed(sdk.SystemMessage(subtype="init", data={})))
    out += list(stream.feed(sdk.ResultMessage()))
    assert out == []


def test_end_to_end_against_consumer_contract(monkeypatch):
    """Drive the translator's real blocks through a copy of the dock's
    _append_block and assert the rendered text is not duplicated."""
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    chat = pytest.importorskip("SciQLop.components.agents.chat")
    if not is_dataclass(getattr(chat, "TextBlock", None)):
        pytest.skip("SciQLop chat classes are stubbed in this env")
    from sciqlop_opencode import backend as bk

    TextBlock = chat.TextBlock
    ToolActivityBlock = chat.ToolActivityBlock

    def append_block(blocks, block):  # verbatim copy of AgentChatDock._append_block
        if isinstance(block, TextBlock):
            last = blocks[-1] if blocks else None
            if type(last) is type(block) and not last.complete:
                last.text += block.text
                last.complete = block.complete
            else:
                blocks.append(block)
        elif isinstance(block, ToolActivityBlock):
            blocks.append(block)

    stream = bk._OpencodeStream()
    rendered = []
    for s in ["Hello", "Hello world", "Hello world, plotting now."]:
        for b in stream.feed(sdk.AssistantMessage(content=[sdk.TextBlock(text=s)])):
            append_block(rendered, b)
    for b in stream.flush():
        append_block(rendered, b)
    text = "".join(b.text for b in rendered if isinstance(b, TextBlock))
    assert text == "Hello world, plotting now."
```

- [ ] **Step 3: Run the tests to verify they fail**

Run (from `/var/home/jeandet/Documents/prog/plugins_sciqlop`):
```
uv run --project /var/home/jeandet/Documents/prog/SciQLop pytest \
  sciqlop_opencode/sciqlop_opencode/tests/test_stream.py -v
```
Expected: FAIL/ERROR — `AttributeError: module 'sciqlop_opencode.backend' has no attribute '_OpencodeStream'`.

- [ ] **Step 4: Implement `_OpencodeStream` and add the import**

In `sciqlop_opencode/sciqlop_opencode/backend.py`, change the chat import line:
```python
from SciQLop.components.agents.chat import ChatMessage, TextBlock
```
to:
```python
from SciQLop.components.agents.chat import ChatMessage, TextBlock, ToolActivityBlock
```

Then add this class at module scope (e.g. just above `class OpencodeBackend`):
```python
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
        self._acc = ""      # text already emitted for the open text block
        self._open = False  # an incomplete TextBlock is open in the consumer

    def feed(self, message):
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

    def flush(self):
        yield from self._close_text()

    def _emit_text(self, snapshot):
        if snapshot == self._acc:
            return
        if not snapshot.startswith(self._acc):
            yield from self._close_text()  # buffer reset -> new block
        delta = snapshot[len(self._acc):]
        self._acc = snapshot
        self._open = True
        yield TextBlock(text=delta, complete=False)

    def _close_text(self):
        if self._open:
            self._open = False
            self._acc = ""
            yield TextBlock(text="", complete=True)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```
uv run --project /var/home/jeandet/Documents/prog/SciQLop pytest \
  sciqlop_opencode/sciqlop_opencode/tests/test_stream.py -v
```
Expected: PASS (7 passed; `test_end_to_end_against_consumer_contract` runs because
the conftest provides a QApplication and real dataclasses).

- [ ] **Step 6: Commit**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add sciqlop_opencode/sciqlop_opencode/backend.py \
        sciqlop_opencode/sciqlop_opencode/tests/conftest.py \
        sciqlop_opencode/sciqlop_opencode/tests/test_stream.py
git commit -m "fix(sciqlop_opencode): diff accumulated text + surface tool activity

Add _OpencodeStream translator: converts opencode's accumulated-snapshot
text stream into incremental TextBlock deltas (killing the quadratic
duplication) and emits ToolActivityBlock for each completed ToolUseBlock.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Wire `ask()` to the translator; remove `_decode_message`

**Files:**
- Modify: `sciqlop_opencode/sciqlop_opencode/backend.py` (`ask`, delete `_decode_message`)
- Create: `sciqlop_opencode/sciqlop_opencode/tests/test_ask_streaming.py`
- Modify: `sciqlop_opencode/README.md`

**Interfaces:**
- Consumes: `_OpencodeStream` from Task 1.
- Produces: `OpencodeBackend.ask(prompt, image_paths=None)` yields the translated
  block stream (deltas during the turn, a final `complete=True` close at the end).

- [ ] **Step 1: Write the failing `ask()` integration test**

Create `sciqlop_opencode/sciqlop_opencode/tests/test_ask_streaming.py`:

```python
"""OpencodeBackend.ask drives one _OpencodeStream per turn and flushes at the end.

Uses a fake SDK client (no opencode CLL/process) and monkeypatched block classes.
"""
import asyncio
from dataclasses import dataclass, field

import pytest


@dataclass
class _Text:
    text: str = ""
    complete: bool = False


@dataclass
class _Tool:
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    result: object = None
    tool_use_id: str = ""


class _FakeClient:
    def __init__(self, messages):
        self._messages = messages

    async def query(self, prompt):
        return None

    async def receive_response(self):
        for m in self._messages:
            yield m


def test_ask_streams_translated_blocks_and_flushes(monkeypatch):
    sdk = pytest.importorskip("opencode_agent_sdk.types")
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "TextBlock", _Text)
    monkeypatch.setattr(bk, "ToolActivityBlock", _Tool)

    inst = bk.OpencodeBackend.__new__(bk.OpencodeBackend)
    inst._lock = asyncio.Lock()
    fake = _FakeClient([
        sdk.AssistantMessage(content=[sdk.TextBlock(text="Hi")]),
        sdk.AssistantMessage(content=[sdk.TextBlock(text="Hi there")]),
        sdk.ResultMessage(),
    ])

    async def _fake_ensure():
        return fake

    monkeypatch.setattr(inst, "_ensure_client", _fake_ensure)

    async def _collect():
        return [b async for b in inst.ask("hi")]

    blocks = asyncio.run(_collect())
    texts = [b.text for b in blocks if isinstance(b, _Text)]
    assert "".join(texts) == "Hi there"
    assert blocks[-1] == _Text(text="", complete=True)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```
uv run --project /var/home/jeandet/Documents/prog/SciQLop pytest \
  sciqlop_opencode/sciqlop_opencode/tests/test_ask_streaming.py -v
```
Expected: FAIL — current `ask()` calls `self._decode_message` (which only handles
text and never closes the block), so there is no final `_Text(text="", complete=True)`.

- [ ] **Step 3: Rewire `ask()` and delete `_decode_message`**

In `sciqlop_opencode/sciqlop_opencode/backend.py`, replace the body of `ask`:
```python
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
```

Then delete the entire `_decode_message` method (the old `def _decode_message(self, message) -> List[StreamBlock]: ...` block at the end of the class).

- [ ] **Step 4: Run the new test plus the full opencode suite**

Run:
```
uv run --project /var/home/jeandet/Documents/prog/SciQLop pytest sciqlop_opencode -v
```
Expected: PASS — `test_ask_streaming.py`, `test_stream.py`, and the existing
`test_backend_hook.py` / `test_backend_models.py` / `test_plugin_metadata.py` /
`test_sessions.py` all pass.

- [ ] **Step 5: Document the SDK-blocked limitations in the README**

Append to `sciqlop_opencode/README.md`:
```markdown
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
```

- [ ] **Step 6: Commit**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add sciqlop_opencode/sciqlop_opencode/backend.py \
        sciqlop_opencode/sciqlop_opencode/tests/test_ask_streaming.py \
        sciqlop_opencode/README.md
git commit -m "fix(sciqlop_opencode): drive ask() through the stream translator

Replace _decode_message with one _OpencodeStream per turn (flushed at end)
so text streams as deltas and tool calls show as activity. Document the
SDK-blocked feature gaps in the README.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Streaming duplication fix → Task 1 (`_OpencodeStream._emit_text`) + tests 1/2/7.
- Tool-activity decoding → Task 1 (`feed` ToolUseBlock branch) + tests 3/4.
- `ask()` rewiring + `_decode_message` removal → Task 2.
- Non-text messages ignored → Task 1 test 6.
- Thinking-inline + out-of-scope items documented → Task 2 Step 5 (README) + class docstring.
- No `DESYNC-PROBE` ported → not present in any task. ✓

**Placeholder scan:** none — every step shows full code/commands.

**Type consistency:** `_OpencodeStream.feed`/`flush` and the block constructors
(`TextBlock(text, complete)`, `ToolActivityBlock(tool_name, tool_input, tool_use_id)`)
are used identically across tasks and match the real classes in
`SciQLop/components/agents/chat/view.py`.
