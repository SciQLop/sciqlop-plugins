# sciqlop_opencode Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fourth AI-agent backend to the SciQLop plugin bundle — `sciqlop_opencode` — feature-equivalent to `sciqlop_claude` but routed through opencode's agent loop via `opencode-agent-sdk`.

**Architecture:** Clone `sciqlop_claude/`'s structure into a sibling `sciqlop_opencode/` plugin. Use `opencode-agent-sdk` (Python, drop-in for `claude-agent-sdk`) in subprocess mode — the SDK spawns `opencode acp` over stdio JSON-RPC, tools register as in-process MCP, our handlers run in SciQLop's Qt process. Auth is delegated to the `opencode` CLI (user runs `opencode auth login` once). Permission gating uses `PreToolUse` hooks instead of `can_use_tool`.

**Tech Stack:** Python 3.10+, `opencode-agent-sdk`, `opencode` CLI (runtime dep), pytest, PySide6, SciQLop core.

**Companion spec:** `docs/superpowers/specs/2026-05-16-sciqlop-opencode-plugin-design.md`.

---

## File Structure

**Created (new):**

```
sciqlop_opencode/
├── pyproject.toml
├── README.md
└── sciqlop_opencode/
    ├── __init__.py                       # load(main_window), backend registration
    ├── plugin.json                       # SciQLop folder-discovery manifest
    ├── backend.py                        # OpencodeBackend + fetch_models + hook
    ├── sessions.py                       # opencode storage walker
    ├── resources/
    │   └── chat.svg                      # icon (copied from sciqlop_claude)
    └── tests/
        ├── __init__.py
        ├── conftest.py                   # stub Qt/SciQLop optional deps
        ├── test_sessions.py              # list_sessions, load_session_messages
        ├── test_backend_hook.py          # _pre_tool_use_hook gating
        └── test_plugin_metadata.py       # plugin.json + pyproject sanity
```

**Modified:** none — purely additive.

---

## Branch setup

- [ ] **Step 1: Verify clean tree and branch off main**

```bash
git status
git fetch origin
git checkout main
git pull --ff-only
git checkout -b feat/sciqlop-opencode
```

Expected: clean checkout on a new branch `feat/sciqlop-opencode`. If `git status` is dirty, stash or commit first.

- [ ] **Step 2: Cherry-pick the design spec from feat/sciqlop-radio**

```bash
git log feat/sciqlop-radio --oneline -- docs/superpowers/specs/2026-05-16-sciqlop-opencode-plugin-design.md
git cherry-pick <commit-sha>
```

Expected: spec file lands at `docs/superpowers/specs/2026-05-16-sciqlop-opencode-plugin-design.md` on the new branch.

---

## Task 1: Package scaffolding

Create the empty package skeleton with metadata, manifest, and icon. No behavior yet — just enough that the package can be installed and discovered.

**Files:**
- Create: `sciqlop_opencode/pyproject.toml`
- Create: `sciqlop_opencode/README.md`
- Create: `sciqlop_opencode/sciqlop_opencode/__init__.py`
- Create: `sciqlop_opencode/sciqlop_opencode/plugin.json`
- Create: `sciqlop_opencode/sciqlop_opencode/resources/chat.svg`

- [ ] **Step 1: Create directory layout**

```bash
mkdir -p sciqlop_opencode/sciqlop_opencode/resources sciqlop_opencode/sciqlop_opencode/tests
```

- [ ] **Step 2: Write `pyproject.toml`**

Content of `sciqlop_opencode/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "sciqlop-opencode"
version = "0.1.0"
description = "Opencode chat dock for SciQLop (powered by the opencode CLI via opencode-agent-sdk)"
requires-python = ">=3.10"
dependencies = ["SciQLop>=0.12.0", "opencode-agent-sdk>=0.4.0"]

[project.entry-points."sciqlop.plugins"]
sciqlop_opencode = "sciqlop_opencode"

[tool.setuptools.packages.find]
include = ["sciqlop_opencode*"]

[tool.setuptools.package-data]
sciqlop_opencode = ["plugin.json"]
```

- [ ] **Step 3: Write `plugin.json`**

Content of `sciqlop_opencode/sciqlop_opencode/plugin.json`:

```json
{
  "name": "Opencode Chat",
  "version": "0.1.0",
  "description": "Embedded opencode chat dock for SciQLop. Delegates auth to the opencode CLI (run `opencode auth login` once).",
  "authors": [
    {
      "name": "Alexis Jeandet",
      "email": "alexis.jeandet@member.fsf.org",
      "organization": "LPP"
    }
  ],
  "license": "MIT",
  "python_dependencies": ["opencode-agent-sdk"],
  "dependencies": [],
  "disabled": false
}
```

- [ ] **Step 4: Write a minimal `__init__.py`**

Content of `sciqlop_opencode/sciqlop_opencode/__init__.py`:

```python
"""Opencode backend plugin for SciQLop's generic agent chat dock.

Registers `OpencodeBackend` with the shared agent registry and makes
sure the chat dock exists. The dock itself lives in SciQLop core and
is shared with any other agent backend plugins that get installed.
"""

def load(main_window):
    # Wired up in Task 9. Keeps the package importable for now.
    return None
```

- [ ] **Step 5: Copy the icon**

```bash
cp sciqlop_claude/sciqlop_claude/resources/chat.svg sciqlop_opencode/sciqlop_opencode/resources/chat.svg
```

- [ ] **Step 6: Write a one-line README**

Content of `sciqlop_opencode/README.md`:

```markdown
# sciqlop_opencode

Opencode chat dock for SciQLop. Requires the `opencode` CLI (https://opencode.ai) and `opencode auth login` to be run once.
```

- [ ] **Step 7: Verify the package imports**

Run: `python -c "import sciqlop_opencode; print(sciqlop_opencode.load.__doc__ or 'ok')"`
Expected: prints docstring or `ok`, no traceback.

(You may need `pip install -e sciqlop_opencode/` first if it's not already on PYTHONPATH.)

- [ ] **Step 8: Commit**

```bash
git add sciqlop_opencode/
git commit -m "feat(sciqlop_opencode): scaffold plugin package"
```

---

## Task 2: Test infrastructure

Stub Qt/SciQLop modules unavailable in CI so tests can import the plugin without a real SciQLop install.

**Files:**
- Create: `sciqlop_opencode/sciqlop_opencode/tests/__init__.py`
- Create: `sciqlop_opencode/sciqlop_opencode/tests/conftest.py`

- [ ] **Step 1: Write empty `tests/__init__.py`**

Content of `sciqlop_opencode/sciqlop_opencode/tests/__init__.py`:

```python
```

- [ ] **Step 2: Write `tests/conftest.py`**

This mirrors `sciqlop_albert/sciqlop_albert/tests/conftest.py` minus the settings-specific bits (we don't have settings for opencode — auth is CLI-only).

Content of `sciqlop_opencode/sciqlop_opencode/tests/conftest.py`:

```python
"""Stub optional plugin deps so backend/sessions modules can be imported in a test env."""
import importlib
import sys
from unittest.mock import MagicMock

_OPTIONAL = [
    "PySide6QtAds",
    "SciQLop",
    "SciQLop.components",
    "SciQLop.components.agents",
    "SciQLop.components.agents.backend",
    "SciQLop.components.agents.chat",
    "SciQLop.components.theming",
    "SciQLop.components.theming.icons",
    "SciQLop.components.workspaces",
]
for name in _OPTIONAL:
    if name in sys.modules:
        continue
    try:
        importlib.import_module(name)
    except Exception:
        sys.modules[name] = MagicMock()
```

- [ ] **Step 3: Write `test_plugin_metadata.py`**

Content of `sciqlop_opencode/sciqlop_opencode/tests/test_plugin_metadata.py`:

```python
"""Plugin manifest sanity checks."""
import json
from pathlib import Path


_PLUGIN_DIR = Path(__file__).resolve().parent.parent


def test_plugin_json_parses_and_has_required_fields():
    data = json.loads((_PLUGIN_DIR / "plugin.json").read_text())
    assert data["name"]
    assert data["version"]
    assert "opencode-agent-sdk" in data["python_dependencies"]
    assert data["disabled"] is False


def test_pyproject_declares_entry_point():
    pyproject = (_PLUGIN_DIR.parent / "pyproject.toml").read_text()
    assert 'sciqlop_opencode = "sciqlop_opencode"' in pyproject
    assert "opencode-agent-sdk" in pyproject
```

- [ ] **Step 4: Run — expect 2 passed**

Run: `pytest sciqlop_opencode/sciqlop_opencode/tests/ -v`
Expected: 2 passed (the metadata tests; no others yet).

- [ ] **Step 5: Commit**

```bash
git add sciqlop_opencode/sciqlop_opencode/tests/
git commit -m "test(sciqlop_opencode): scaffold test infrastructure + manifest tests"
```

---

## Task 3: sessions.py — workspace + list_sessions (TDD)

Walk opencode's storage tree under `${OPENCODE_DATA_DIR:-~/.local/share/opencode}/storage/session/<projectHash>/<sessionID>.json` and return entries filtered by the current workspace.

**Files:**
- Create: `sciqlop_opencode/sciqlop_opencode/sessions.py`
- Test: `sciqlop_opencode/sciqlop_opencode/tests/test_sessions.py`

- [ ] **Step 1: Write the failing test for `list_sessions` filtering by cwd**

Content of `sciqlop_opencode/sciqlop_opencode/tests/test_sessions.py`:

```python
"""Tests for opencode session storage walker."""
import json
from pathlib import Path

import pytest

from sciqlop_opencode import sessions as sess


def _write_session(storage: Path, project_hash: str, sid: str, *, cwd: str, label: str, mtime: float | None = None) -> Path:
    sdir = storage / "session" / project_hash
    sdir.mkdir(parents=True, exist_ok=True)
    p = sdir / f"{sid}.json"
    p.write_text(json.dumps({"id": sid, "cwd": cwd, "label": label}))
    if mtime is not None:
        import os
        os.utime(p, (mtime, mtime))
    return p


def test_list_sessions_filters_by_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    storage = tmp_path / "storage"
    _write_session(storage, "hashA", "sess-1", cwd="/work/ws-a", label="alpha")
    _write_session(storage, "hashB", "sess-2", cwd="/work/ws-b", label="beta")

    monkeypatch.setattr(sess, "current_workspace_dir", lambda: Path("/work/ws-a"))

    out = sess.list_sessions()
    assert [s.session_id for s in out] == ["sess-1"]
    assert out[0].label == "alpha"


def test_list_sessions_sorted_by_mtime_desc(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    storage = tmp_path / "storage"
    _write_session(storage, "h", "old", cwd="/w", label="old", mtime=100.0)
    _write_session(storage, "h", "new", cwd="/w", label="new", mtime=200.0)

    monkeypatch.setattr(sess, "current_workspace_dir", lambda: Path("/w"))

    out = sess.list_sessions()
    assert [s.session_id for s in out] == ["new", "old"]


def test_list_sessions_returns_empty_when_storage_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path / "does-not-exist"))
    assert sess.list_sessions() == []


def test_list_sessions_tolerates_corrupt_json(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    storage = tmp_path / "storage"
    sdir = storage / "session" / "h"
    sdir.mkdir(parents=True)
    (sdir / "broken.json").write_text("{not json")
    _write_session(storage, "h", "good", cwd="/w", label="ok")

    monkeypatch.setattr(sess, "current_workspace_dir", lambda: Path("/w"))

    out = sess.list_sessions()
    assert [s.session_id for s in out] == ["good"]
```

- [ ] **Step 2: Run tests — expect collection failure**

Run: `pytest sciqlop_opencode/sciqlop_opencode/tests/test_sessions.py -v`
Expected: `ModuleNotFoundError: No module named 'sciqlop_opencode.sessions'`.

- [ ] **Step 3: Implement `sessions.py` — workspace + list**

Content of `sciqlop_opencode/sciqlop_opencode/sessions.py`:

```python
"""Enumerate prior opencode sessions stored on disk.

opencode persists each session as
`${OPENCODE_DATA_DIR:-~/.local/share/opencode}/storage/session/<projectHash>/<sessionID>.json`
and per-message content under `storage/message/<sessionID>/msg_*.json`.

We list sessions whose `cwd` matches the current SciQLop workspace and
extract a short label for the resume dropdown.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def current_workspace_dir() -> Path:
    try:
        from SciQLop.components.workspaces import workspaces_manager_instance
        mgr = workspaces_manager_instance()
        ws = getattr(mgr, "workspace", None)
        wdir = getattr(ws, "workspace_dir", None) if ws is not None else None
        if wdir:
            return Path(wdir).resolve()
    except Exception:
        pass
    env = os.environ.get("SCIQLOP_WORKSPACE_DIR")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


@dataclass
class SessionEntry:
    session_id: str
    path: Path
    mtime: float
    label: str


def _storage_root() -> Path:
    env = os.environ.get("OPENCODE_DATA_DIR")
    if env:
        return Path(env).expanduser() / "storage"
    return Path.home() / ".local" / "share" / "opencode" / "storage"


def _session_root() -> Path:
    return _storage_root() / "session"


def list_sessions(limit: int = 50) -> List[SessionEntry]:
    workspace = str(current_workspace_dir())
    root = _session_root()
    if not root.is_dir():
        return []

    entries: List[SessionEntry] = []
    for project_dir in root.iterdir():
        if not project_dir.is_dir():
            continue
        for path in project_dir.iterdir():
            if path.suffix != ".json" or not path.is_file():
                continue
            entry = _read_session_entry(path, workspace)
            if entry is not None:
                entries.append(entry)
    entries.sort(key=lambda e: e.mtime, reverse=True)
    return entries[:limit]


def _read_session_entry(path: Path, workspace: str) -> Optional[SessionEntry]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd != workspace:
        return None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    label = _label_from_session(data) or "(empty session)"
    return SessionEntry(session_id=path.stem, path=path, mtime=mtime, label=label)


def _label_from_session(data: dict) -> Optional[str]:
    for key in ("label", "title", "name"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return _shorten(v.strip())
    return None


def _shorten(text: str, max_len: int = 80) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) > max_len:
        return collapsed[: max_len - 1] + "…"
    return collapsed
```

- [ ] **Step 4: Run tests — expect all to pass**

Run: `pytest sciqlop_opencode/sciqlop_opencode/tests/test_sessions.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add sciqlop_opencode/sciqlop_opencode/sessions.py sciqlop_opencode/sciqlop_opencode/tests/test_sessions.py
git commit -m "feat(sciqlop_opencode): list opencode sessions filtered by workspace"
```

---

## Task 4: sessions.py — load_session_messages (TDD)

Replay an opencode session's message files into a `ChatMessage` list that the dock can render.

**Files:**
- Modify: `sciqlop_opencode/sciqlop_opencode/sessions.py`
- Modify: `sciqlop_opencode/sciqlop_opencode/tests/test_sessions.py`

opencode stores each message at `storage/message/<sessionID>/msg_*.json`. The JSON layout we target (verify at implementation by inspecting a real opencode session): each file contains role + content blocks. Text blocks → `TextBlock`. Image blocks (or tool-result blocks containing images) → `ImageBlock` after writing to `image_tempdir` via `write_b64_image`. The implementation must tolerate format drift (skip unknown block types).

- [ ] **Step 1: Append failing test for `load_session_messages`**

Append to `sciqlop_opencode/sciqlop_opencode/tests/test_sessions.py`:

```python
def _write_message(storage: Path, sid: str, name: str, payload: dict) -> Path:
    mdir = storage / "message" / sid
    mdir.mkdir(parents=True, exist_ok=True)
    p = mdir / f"{name}.json"
    p.write_text(json.dumps(payload))
    return p


def test_load_session_messages_decodes_text_blocks(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    import sys

    # SciQLop.components.agents.chat is stubbed by conftest; replace ChatMessage / TextBlock
    # with simple namespace-like objects so we can introspect the result.
    fake_chat = MagicMock()

    class _Msg:
        def __init__(self, role, blocks, done=True):
            self.role = role
            self.blocks = list(blocks)
            self.done = done

    class _Text:
        def __init__(self, text):
            self.text = text

    class _Image:
        def __init__(self, path):
            self.path = path

    fake_chat.ChatMessage = _Msg
    fake_chat.TextBlock = _Text
    fake_chat.ImageBlock = _Image
    fake_chat.write_b64_image = lambda data, mime, tempdir, prefix: None
    monkeypatch.setitem(sys.modules, "SciQLop.components.agents.chat", fake_chat)

    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    storage = tmp_path / "storage"
    _write_message(storage, "sid", "msg_001", {"role": "user", "content": [{"type": "text", "text": "hi"}]})
    _write_message(storage, "sid", "msg_002", {"role": "assistant", "content": [{"type": "text", "text": "hello"}]})

    out = sess.load_session_messages("sid", image_tempdir=tmp_path / "imgs")
    assert [(m.role, m.blocks[0].text) for m in out] == [("user", "hi"), ("assistant", "hello")]


def test_load_session_messages_skips_unknown_blocks(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    import sys

    fake_chat = MagicMock()

    class _Msg:
        def __init__(self, role, blocks, done=True):
            self.role = role
            self.blocks = list(blocks)
            self.done = done

    class _Text:
        def __init__(self, text):
            self.text = text

    fake_chat.ChatMessage = _Msg
    fake_chat.TextBlock = _Text
    fake_chat.ImageBlock = MagicMock
    fake_chat.write_b64_image = lambda data, mime, tempdir, prefix: None
    monkeypatch.setitem(sys.modules, "SciQLop.components.agents.chat", fake_chat)

    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    storage = tmp_path / "storage"
    _write_message(storage, "sid", "msg_001", {
        "role": "user",
        "content": [
            {"type": "text", "text": "hi"},
            {"type": "weird_unknown_type", "stuff": 123},
        ],
    })

    out = sess.load_session_messages("sid", image_tempdir=None)
    assert len(out) == 1
    assert out[0].blocks[0].text == "hi"


def test_load_session_messages_missing_session_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(tmp_path))
    assert sess.load_session_messages("nonexistent", image_tempdir=None) == []
```

- [ ] **Step 2: Run — expect `AttributeError: module has no attribute 'load_session_messages'`**

Run: `pytest sciqlop_opencode/sciqlop_opencode/tests/test_sessions.py -v`
Expected: 3 new failures.

- [ ] **Step 3: Implement `load_session_messages`**

Append to `sciqlop_opencode/sciqlop_opencode/sessions.py`:

```python
def load_session_messages(
    session_id: str,
    image_tempdir: Optional[Path] = None,
):
    """Replay a session's message files into a list of `ChatMessage`."""
    from SciQLop.components.agents.chat import ChatMessage, ImageBlock, TextBlock, write_b64_image

    msg_dir = _storage_root() / "message" / session_id
    if not msg_dir.is_dir():
        return []

    tempdir = Path(image_tempdir) if image_tempdir else None
    if tempdir is not None:
        tempdir.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in msg_dir.iterdir() if p.suffix == ".json" and p.is_file())
    messages: list = []
    for path in files:
        record = _read_message_record(path)
        if record is None:
            continue
        role = record.get("role")
        if role not in ("user", "assistant"):
            continue
        blocks = _render_blocks(record.get("content"), tempdir, TextBlock, ImageBlock, write_b64_image)
        if not blocks:
            continue
        if messages and messages[-1].role == role:
            messages[-1].blocks.extend(blocks)
        else:
            messages.append(ChatMessage(role=role, blocks=blocks, done=True))
    return messages


def _read_message_record(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _render_blocks(content, tempdir, TextBlock, ImageBlock, write_b64_image):
    if isinstance(content, str):
        return [TextBlock(text=content)] if content.strip() else []
    if not isinstance(content, list):
        return []
    out = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text") or ""
            if text.strip():
                out.append(TextBlock(text=text))
        elif btype == "image":
            path = _decode_image(block, tempdir, write_b64_image)
            if path:
                out.append(ImageBlock(path=path))
        elif btype == "tool_result":
            inner = block.get("content")
            if isinstance(inner, list):
                for item in inner:
                    if isinstance(item, dict) and item.get("type") == "image":
                        p = _decode_image(item, tempdir, write_b64_image)
                        if p:
                            out.append(ImageBlock(path=p))
    return out


def _decode_image(block: dict, tempdir, write_b64_image) -> Optional[str]:
    if tempdir is None:
        return None
    source = block.get("source") if isinstance(block.get("source"), dict) else block
    mime = source.get("mediaType") or source.get("media_type") or source.get("mimeType") or "image/png"
    return write_b64_image(source.get("data"), mime, tempdir, prefix="replay")
```

- [ ] **Step 4: Run tests — expect all to pass**

Run: `pytest sciqlop_opencode/sciqlop_opencode/tests/test_sessions.py -v`
Expected: 7 passed (4 from Task 3 + 3 from this task).

- [ ] **Step 5: Verify against a real opencode session (manual)**

If you have opencode installed with at least one prior session under `~/.local/share/opencode/storage/`, run a quick smoke:

```bash
python -c "
import os
from sciqlop_opencode import sessions
os.environ.setdefault('SCIQLOP_WORKSPACE_DIR', os.getcwd())
for s in sessions.list_sessions(limit=5):
    print(s.session_id, s.label, s.mtime)
"
```

If the message JSON shape doesn't match what `_render_blocks` expects (e.g. blocks live under `parts` instead of `content`, or fields are named differently), adjust `_render_blocks` to match the real shape and add a regression test for it. **Do not skip this step — the JSON shape we coded against is inferred; verify it.**

- [ ] **Step 6: Commit**

```bash
git add sciqlop_opencode/sciqlop_opencode/sessions.py sciqlop_opencode/sciqlop_opencode/tests/test_sessions.py
git commit -m "feat(sciqlop_opencode): replay session messages from on-disk storage"
```

---

## Task 5: backend.py — availability + system prompt + tool wrapper

Set up the file skeleton with the availability checks, the system prompt, and the in-process tool wrapper. No SDK client yet.

**Files:**
- Create: `sciqlop_opencode/sciqlop_opencode/backend.py`

- [ ] **Step 1: Write `backend.py` skeleton**

Content of `sciqlop_opencode/sciqlop_opencode/backend.py`:

```python
"""opencode-agent-sdk adapter — implements `SciQLop.components.agents.AgentBackend`."""
from __future__ import annotations

import asyncio
import shutil
from typing import Callable, List, Optional

try:
    from opencode_agent_sdk import (
        AgentOptions,
        SDKClient,
        create_sdk_mcp_server,
        tool as sdk_tool,
    )
    _SDK_AVAILABLE = True
    _SDK_IMPORT_ERROR: Optional[str] = None
except Exception as e:  # pragma: no cover
    _SDK_AVAILABLE = False
    _SDK_IMPORT_ERROR = str(e)


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
```

- [ ] **Step 2: Verify the module imports**

Run: `pytest sciqlop_opencode/sciqlop_opencode/tests/ -v --collect-only`
Expected: still 0 new tests, no import errors.

- [ ] **Step 3: Verify availability helpers**

Run:

```bash
python -c "from sciqlop_opencode.backend import opencode_cli_available, sdk_available; print('cli:', opencode_cli_available()); print('sdk:', sdk_available())"
```

Expected: `cli: True` if you have opencode installed, `False` otherwise; `sdk: (True, None)` if you've pip-installed `opencode-agent-sdk`, `(False, "...")` otherwise.

- [ ] **Step 4: Commit**

```bash
git add sciqlop_opencode/sciqlop_opencode/backend.py
git commit -m "feat(sciqlop_opencode): backend skeleton with availability checks + system prompt"
```

---

## Task 6: backend.py — fetch_models

Mirror `sciqlop_claude.fetch_models`: open a throwaway SDK client in a worker thread, ask for the model list, fall back to the default on any error.

**Files:**
- Modify: `sciqlop_opencode/sciqlop_opencode/backend.py`

**Verification required:** The exact shape of `get_server_info()`'s return for opencode-agent-sdk isn't pinned in public docs. Inspect the SDK source (`pip show opencode-agent-sdk` → site-packages) at this step. If `get_server_info()` doesn't expose models, fall back to parsing `client.models()` or whatever the SDK provides; if neither, ship the static `_DEFAULT_MODEL_CHOICES` fallback and skip the dynamic fetch (document this in a comment in `fetch_models`).

- [ ] **Step 1: Inspect the SDK**

```bash
python -c "import opencode_agent_sdk; print(opencode_agent_sdk.__file__)"
```

Then read the source of `SDKClient` to find the equivalent of `get_server_info()`. Note the actual method name and return shape — you'll need it in step 2.

- [ ] **Step 2: Implement `fetch_models`**

Append to `sciqlop_opencode/sciqlop_opencode/backend.py`:

```python
from concurrent.futures import ThreadPoolExecutor


def fetch_models(timeout: float = 10.0) -> List[tuple[str, Optional[str]]]:
    """Fetch the live model list opencode advertises.

    Returns `[("Default (opencode)", None)]` on any failure — the dock
    works fine without a live list, opencode just picks its default.
    """
    if not _SDK_AVAILABLE or not opencode_cli_available():
        return list(_DEFAULT_MODEL_CHOICES)

    async def _run() -> list:
        # Adjust the method name + result shape per the SDK inspection in Step 1.
        async with SDKClient(options=AgentOptions()) as client:
            info = await client.get_server_info() or {}
            return info.get("models") or []

    def _blocking() -> list:
        return asyncio.run(asyncio.wait_for(_run(), timeout=timeout))

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            raw = pool.submit(_blocking).result(timeout=timeout + 2.0)
    except Exception:
        return list(_DEFAULT_MODEL_CHOICES)

    choices: List[tuple[str, Optional[str]]] = []
    for m in raw:
        # Best-effort shape coercion; adjust to match real SDK output.
        if isinstance(m, dict):
            value = m.get("value") or m.get("id")
            label = m.get("displayName") or m.get("name") or value
        else:
            value = label = str(m)
        if not value or not label:
            continue
        choices.append((label, None if value == "default" else value))
    return choices or list(_DEFAULT_MODEL_CHOICES)
```

- [ ] **Step 3: Verify it doesn't crash even without opencode installed**

Run:

```bash
python -c "from sciqlop_opencode.backend import fetch_models; print(fetch_models(timeout=2.0))"
```

Expected: returns `[("Default (opencode)", None)]` if opencode isn't installed/authed, or a list of model tuples if it is. **Must not raise.**

- [ ] **Step 4: Commit**

```bash
git add sciqlop_opencode/sciqlop_opencode/backend.py
git commit -m "feat(sciqlop_opencode): live model discovery with safe fallback"
```

---

## Task 7: backend.py — permission hook (TDD)

The `PreToolUse` hook is the single most behavior-critical piece. Test the gating logic in isolation before wiring it into the class.

**Files:**
- Modify: `sciqlop_opencode/sciqlop_opencode/backend.py`
- Create: `sciqlop_opencode/sciqlop_opencode/tests/test_backend_hook.py`

**Critical verification:** Before writing the hook, inspect `opencode_agent_sdk` source to determine whether `PreToolUse` hooks accept **async** functions or are strictly **sync**. Based on the answer, the hook either `await`s `confirm_cb` directly or bridges via `asyncio.run_coroutine_threadsafe`. The test target is the same in both cases — the hook returns the right `permissionDecision`.

- [ ] **Step 1: Inspect the SDK's hook signature**

```bash
python -c "
import inspect, opencode_agent_sdk as o
# Find the hook type / examples
import opencode_agent_sdk as oa
print([n for n in dir(oa) if 'hook' in n.lower() or 'permission' in n.lower()])
"
```

Read the SDK source around hooks. Determine: are hooks called as `await hook(...)` (async-capable) or `hook(...)` (sync)? Note the answer here:

```
HOOK_TYPE: async / sync         ← fill in
```

- [ ] **Step 2: Write the failing tests**

Content of `sciqlop_opencode/sciqlop_opencode/tests/test_backend_hook.py`:

```python
"""Permission gating tests for OpencodeBackend's PreToolUse hook.

The hook is tested in isolation — we don't need a real opencode SDK
running, only the dict-in / dict-out contract.
"""
import asyncio

import pytest

from sciqlop_opencode import backend as bk


class _StubConfirm:
    def __init__(self, decision: bool):
        self.decision = decision
        self.calls = []

    async def __call__(self, name, args):
        self.calls.append((name, args))
        return self.decision


def _make_backend(*, gated, allow_writes, confirm_decision=True):
    inst = bk.OpencodeBackend.__new__(bk.OpencodeBackend)
    inst._gated_names = set(gated)
    inst._allow_writes = allow_writes
    inst._confirm_cb = _StubConfirm(confirm_decision)
    inst._qasync_loop = asyncio.new_event_loop()
    return inst


def _input(name, **fields):
    return {"tool_name": f"mcp__sciqlop__{name}", "tool_input": fields}


def test_ungated_tool_is_allowed():
    inst = _make_backend(gated={"sciqlop_exec_python"}, allow_writes=False)
    result = _call_hook(inst, _input("sciqlop_window_state"))
    assert result is None  # None / no decision = allow


def test_gated_tool_denied_when_writes_disabled():
    inst = _make_backend(gated={"sciqlop_exec_python"}, allow_writes=False)
    result = _call_hook(inst, _input("sciqlop_exec_python", code="print(1)"))
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "Allow write actions" in result["hookSpecificOutput"]["permissionDecisionReason"]


def test_gated_tool_allowed_when_user_confirms():
    inst = _make_backend(gated={"sciqlop_exec_python"}, allow_writes=True, confirm_decision=True)
    result = _call_hook(inst, _input("sciqlop_exec_python", code="print(1)"))
    assert result["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert inst._confirm_cb.calls == [("sciqlop_exec_python", {"code": "print(1)"})]


def test_gated_tool_denied_when_user_refuses():
    inst = _make_backend(gated={"sciqlop_exec_python"}, allow_writes=True, confirm_decision=False)
    result = _call_hook(inst, _input("sciqlop_exec_python", code="print(1)"))
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def _call_hook(inst, input_data):
    """Invoke the hook regardless of whether the SDK contract is sync or async."""
    hook = inst._pre_tool_use_hook
    if asyncio.iscoroutinefunction(hook):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(hook(input_data, "tool-use-1", {}))
        finally:
            loop.close()
    return hook(input_data, "tool-use-1", {})
```

- [ ] **Step 3: Run — expect `AttributeError: 'OpencodeBackend'` or similar**

Run: `pytest sciqlop_opencode/sciqlop_opencode/tests/test_backend_hook.py -v`
Expected: all 4 fail with `AttributeError` (class doesn't exist yet).

- [ ] **Step 4: Implement the hook (and minimal class shell to host it)**

Append to `sciqlop_opencode/sciqlop_opencode/backend.py`:

```python
class OpencodeBackend:
    display_name = "Opencode"
    model_choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    supports_sessions = True

    # __init__ and the rest of the lifecycle methods land in Task 8.

    def _pre_tool_use_hook(self, input_data, tool_use_id, context):
        """Decide whether to allow a tool call.

        Three-branch logic:
          1. tool not gated → allow (return None)
          2. gated + writes disabled → deny with explanation
          3. gated + writes allowed → ask the user via confirm_cb
        """
        tool_name = input_data.get("tool_name", "")
        short = tool_name.split("__")[-1]
        if short not in self._gated_names:
            return None
        if not self._allow_writes:
            return {
                "hookSpecificOutput": {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "write actions are disabled — toggle 'Allow write actions' "
                        "in the SciQLop chat dock"
                    ),
                }
            }
        tool_input = input_data.get("tool_input") or {}
        try:
            allowed = self._invoke_confirm(short, tool_input)
        except Exception as e:
            return {
                "hookSpecificOutput": {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"approval callback failed: {e}",
                }
            }
        return {
            "hookSpecificOutput": {
                "permissionDecision": "allow" if allowed else "deny",
                "permissionDecisionReason": "user approval" if allowed else "user denied",
            }
        }

    def _invoke_confirm(self, short: str, tool_input: dict) -> bool:
        """Bridge from the (possibly sync) hook to the async confirm_cb.

        If the SDK calls hooks on the same asyncio loop as the rest of
        the backend (verified in Task 7 Step 1), we can `await` here. If
        the SDK calls hooks on a worker thread, we bridge via
        `run_coroutine_threadsafe` onto the qasync loop.
        """
        coro = self._confirm_cb(short, tool_input)
        try:
            asyncio.get_running_loop()
            # We're already on an event loop — caller must await us. But
            # this code path is sync; if the SDK calls the hook async, the
            # hook itself should be async (see Task 7 Step 1 finding).
            # Reaching here from a sync hook means we MUST be on a worker
            # thread and the qasync loop is elsewhere.
            raise RuntimeError("unexpected: sync hook called on an event loop")
        except RuntimeError:
            pass
        future = asyncio.run_coroutine_threadsafe(coro, self._qasync_loop)
        return bool(future.result())
```

**If Step 1 found the hook is async:** change `def _pre_tool_use_hook` and `def _invoke_confirm` to `async def`, and replace the `_invoke_confirm` body with `return bool(await self._confirm_cb(short, tool_input))`. Update `_pre_tool_use_hook` to `await self._invoke_confirm(...)`. The tests' `_call_hook` helper already handles both shapes.

- [ ] **Step 5: Run tests — expect all 4 to pass**

Run: `pytest sciqlop_opencode/sciqlop_opencode/tests/test_backend_hook.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add sciqlop_opencode/sciqlop_opencode/backend.py sciqlop_opencode/sciqlop_opencode/tests/test_backend_hook.py
git commit -m "feat(sciqlop_opencode): PreToolUse permission gating with confirm bridge"
```

---

## Task 8: backend.py — full OpencodeBackend class

Fill in the rest of `OpencodeBackend`: `__init__`, `_ensure_client`, `ask`, `reset`, `cancel`, `resume`, `set_model`, `set_allow_writes`, `list_slash_commands`, `list_sessions`, `load_session`, `_decode_message`, `_tool_result_blocks`, `_build_user_stream`.

**Files:**
- Modify: `sciqlop_opencode/sciqlop_opencode/backend.py`

This is the bulk of the port from `sciqlop_claude/backend.py:162-393`. Most methods are mechanical adaptations; the `_decode_message` call paths require checking that opencode-agent-sdk emits the same `AssistantMessage` / `UserMessage` shapes as claude-agent-sdk.

- [ ] **Step 1: Verify message types**

```bash
python -c "
import opencode_agent_sdk
print([n for n in dir(opencode_agent_sdk) if 'Message' in n or 'Block' in n or 'Result' in n])
try:
    from opencode_agent_sdk.types import AssistantMessage, UserMessage, ToolResultBlock
    print('drop-in types ok')
except ImportError as e:
    print('NOT a drop-in for types:', e)
"
```

If types match: import them directly. If they differ: import the actual names exposed and adapt `_decode_message` field accesses. **Document the actual import path you used in a comment in `_decode_message`.**

- [ ] **Step 2: Add imports for SciQLop-side types**

Insert at the top of `sciqlop_opencode/sciqlop_opencode/backend.py` (after the existing imports):

```python
import base64
from pathlib import Path

from SciQLop.components.agents import BackendContext, SessionEntry
from SciQLop.components.agents.backend import StreamBlock
from SciQLop.components.agents.chat import (
    ChatMessage,
    ImageBlock,
    TextBlock,
    write_b64_image,
)

from . import sessions as _sessions

# Adjust if Step 1 found different names.
try:
    from opencode_agent_sdk.types import (
        AssistantMessage,
        ToolResultBlock,
        UserMessage,
    )
except ImportError:
    # Fallback: drop-in promise didn't hold for types; SDK exposes them at top level.
    from opencode_agent_sdk import AssistantMessage, ToolResultBlock, UserMessage
```

- [ ] **Step 3: Replace the placeholder class body with the full implementation**

Replace the `class OpencodeBackend:` block from Task 7 (everything from `class OpencodeBackend:` to the end of `_invoke_confirm`) with:

```python
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
        self._slash_cache: Optional[List[str]] = None
        try:
            self._qasync_loop = asyncio.get_event_loop()
        except RuntimeError:
            self._qasync_loop = asyncio.new_event_loop()

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
            hooks={"PreToolUse": [self._pre_tool_use_hook]} if self._confirm_cb else None,
            model=self._model,
            resume=self._resume,
            cwd=str(_sessions.current_workspace_dir()),
            # server_url unset -> subprocess mode (spawns `opencode acp`).
        )
        self._client = SDKClient(options=options)
        await self._client.connect()
        return self._client

    async def ask(self, prompt: str, image_paths: Optional[List[str]] = None):
        async with self._lock:
            client = await self._ensure_client()
            await client.query(_build_user_stream(prompt, image_paths or []))
            async for message in client.receive_response():
                for block in self._decode_message(message):
                    yield block

    async def reset(self) -> None:
        async with self._lock:
            await self._disconnect()
            self._resume = None
            self._slash_cache = None

    async def cancel(self) -> None:
        async with self._lock:
            client = self._client
            if client is None:
                return
            interrupt = getattr(client, "interrupt", None)
            if interrupt is not None:
                try:
                    await interrupt()
                    return
                except Exception:
                    pass
            await self._disconnect()

    async def resume(self, session_id: str) -> None:
        async with self._lock:
            await self._disconnect()
            self._resume = session_id
            self._slash_cache = None

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
            if self._client is not None:
                set_model = getattr(self._client, "set_model", None)
                if set_model is not None:
                    try:
                        await set_model(model)
                        return
                    except Exception:
                        pass
                await self._disconnect()

    def set_allow_writes(self, allow: bool) -> None:
        self._allow_writes = allow

    async def list_slash_commands(self) -> List[str]:
        if self._slash_cache is not None:
            return self._slash_cache
        async with self._lock:
            if self._slash_cache is not None:
                return self._slash_cache
            client = await self._ensure_client()
            try:
                info = await client.get_server_info()
            except Exception:
                return []
            if not isinstance(info, dict):
                return []
            commands = info.get("commands") or []
            names: List[str] = []
            for c in commands:
                if isinstance(c, dict):
                    name = c.get("name")
                    if isinstance(name, str):
                        names.append("/" + name.lstrip("/"))
                elif isinstance(c, str):
                    names.append("/" + c.lstrip("/"))
            self._slash_cache = names
            return names

    def list_sessions(self) -> List[SessionEntry]:
        return [
            SessionEntry(id=s.session_id, label=s.label, mtime=s.mtime)
            for s in _sessions.list_sessions()
        ]

    def load_session(self, session_id: str, image_tempdir: Path) -> List[ChatMessage]:
        return _sessions.load_session_messages(session_id, image_tempdir=image_tempdir)

    def _pre_tool_use_hook(self, input_data, tool_use_id, context):
        tool_name = input_data.get("tool_name", "")
        short = tool_name.split("__")[-1]
        if short not in self._gated_names:
            return None
        if not self._allow_writes:
            return {
                "hookSpecificOutput": {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "write actions are disabled — toggle 'Allow write actions' "
                        "in the SciQLop chat dock"
                    ),
                }
            }
        tool_input = input_data.get("tool_input") or {}
        try:
            allowed = self._invoke_confirm(short, tool_input)
        except Exception as e:
            return {
                "hookSpecificOutput": {
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"approval callback failed: {e}",
                }
            }
        return {
            "hookSpecificOutput": {
                "permissionDecision": "allow" if allowed else "deny",
                "permissionDecisionReason": "user approval" if allowed else "user denied",
            }
        }

    def _invoke_confirm(self, short: str, tool_input: dict) -> bool:
        coro = self._confirm_cb(short, tool_input)
        try:
            asyncio.get_running_loop()
            raise RuntimeError("unexpected: sync hook called on an event loop")
        except RuntimeError:
            pass
        future = asyncio.run_coroutine_threadsafe(coro, self._qasync_loop)
        return bool(future.result())

    def _decode_message(self, message) -> List[StreamBlock]:
        blocks: List[StreamBlock] = []
        if isinstance(message, AssistantMessage):
            for block in getattr(message, "content", []) or []:
                text = getattr(block, "text", None)
                if text:
                    blocks.append(TextBlock(text=text))
            return blocks
        if isinstance(message, UserMessage):
            for block in _iter_tool_results(message):
                blocks.extend(self._tool_result_blocks(block))
        return blocks

    def _tool_result_blocks(self, block) -> List[StreamBlock]:
        out: List[StreamBlock] = []
        content = getattr(block, "content", None)
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "image":
                    path = write_b64_image(
                        item.get("data"),
                        item.get("mimeType", "image/png"),
                        self._tempdir,
                        prefix="tool",
                    )
                    if path:
                        out.append(ImageBlock(path=path))
        return out


def _iter_tool_results(message) -> list:
    content = getattr(message, "content", None)
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, ToolResultBlock)]


def _build_user_stream(text: str, image_paths: List[str]):
    async def _gen():
        content: list = [{"type": "text", "text": text or ""}]
        for path in image_paths:
            try:
                data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
            except OSError:
                continue
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": data,
                    },
                }
            )
        yield {
            "type": "user",
            "message": {"role": "user", "content": content},
            "parent_tool_use_id": None,
        }
    return _gen()
```

**Important:** If Task 7 Step 1 found that the hook is async, change `_pre_tool_use_hook` and `_invoke_confirm` to `async def` per the note at the end of Task 7 Step 4. Adjust `hooks={"PreToolUse": [self._pre_tool_use_hook]}` only if the SDK requires a different shape for async hooks (it usually doesn't).

- [ ] **Step 4: Re-run hook tests — must still pass**

Run: `pytest sciqlop_opencode/sciqlop_opencode/tests/test_backend_hook.py -v`
Expected: 4 passed. If the test helper `_make_backend` no longer works because `__init__` requires `BackendContext`, that's fine — the helper bypasses `__init__` via `__new__`. Make sure it still sets `_qasync_loop`, `_gated_names`, `_allow_writes`, `_confirm_cb`.

- [ ] **Step 5: Quick sanity import**

Run:

```bash
python -c "
from sciqlop_opencode.backend import OpencodeBackend
print('class:', OpencodeBackend.display_name, 'supports_sessions:', OpencodeBackend.supports_sessions)
print('attrs:', sorted(a for a in dir(OpencodeBackend) if not a.startswith('__'))[:10])
"
```

Expected: no traceback, prints class metadata. May fail if SciQLop core isn't installed in the env — that's acceptable for now (the manual smoke test in Task 10 covers full integration).

- [ ] **Step 6: Commit**

```bash
git add sciqlop_opencode/sciqlop_opencode/backend.py
git commit -m "feat(sciqlop_opencode): full OpencodeBackend with subprocess opencode acp"
```

---

## Task 9: Wire up `load()` in `__init__.py`

Replace the no-op `load()` with backend registration mirroring `sciqlop_claude/__init__.py`.

**Files:**
- Modify: `sciqlop_opencode/sciqlop_opencode/__init__.py`

- [ ] **Step 1: Rewrite `__init__.py`**

Replace the entire content of `sciqlop_opencode/sciqlop_opencode/__init__.py`:

```python
"""Opencode backend plugin for SciQLop's generic agent chat dock.

Registers `OpencodeBackend` with the shared agent registry and makes
sure the chat dock exists. The dock itself lives in SciQLop core and
is shared with any other agent backend plugins that get installed.
"""
from pathlib import Path

import PySide6QtAds as QtAds
from PySide6.QtGui import QIcon

from SciQLop.components.agents import ensure_agent_dock, register_agent_backend
from SciQLop.components.theming.icons import register_icon, theme_adapted_icon

from .backend import OpencodeBackend, fetch_models

_ICON_NAME = "sciqlop_opencode_chat"
_ICON_PATH = str(Path(__file__).parent / "resources" / "chat.svg")
_DOCK_TITLE = "Agents"


def load(main_window):
    register_icon(_ICON_NAME, lambda: QIcon(_ICON_PATH))
    icon = theme_adapted_icon(_ICON_NAME)

    models = fetch_models()
    if models:
        OpencodeBackend.model_choices = models

    register_agent_backend(OpencodeBackend)
    dock = ensure_agent_dock(main_window)
    dock.setWindowTitle(_DOCK_TITLE)
    dock.setWindowIcon(icon)

    dock_widget = main_window.dock_manager.findDockWidget(_DOCK_TITLE)
    if dock_widget is None:
        main_window.addWidgetIntoDock(QtAds.DockWidgetArea.RightDockWidgetArea, dock)
        dock_widget = main_window.dock_manager.findDockWidget(_DOCK_TITLE)
        if dock_widget:
            dock_widget.setIcon(icon)
            dock_widget.toggleView(False)
            toggle_action = dock_widget.toggleViewAction()
            toggle_action.setIcon(icon)
            main_window.toolBar.addAction(toggle_action)

    # The "Agent Chat" entry in the Tools menu is added by
    # SciQLop.components.agents.ensure_agent_dock (idempotent) so multiple
    # backend plugins don't produce duplicate entries.

    return dock
```

- [ ] **Step 2: Run the full plugin test suite**

Run: `pytest sciqlop_opencode/sciqlop_opencode/tests/ -v`
Expected: 2 manifest + 7 sessions + 4 hook = 13 passed.

- [ ] **Step 3: Commit**

```bash
git add sciqlop_opencode/sciqlop_opencode/__init__.py
git commit -m "feat(sciqlop_opencode): register backend and wire up dock on plugin load"
```

---

## Task 10: Manual smoke test against a live SciQLop

No code in this task — only verification steps. Run them before merging.

- [ ] **Step 1: Install opencode CLI**

Follow https://opencode.ai install instructions. Verify:

```bash
opencode --version
which opencode
```

- [ ] **Step 2: Authenticate opencode with a provider**

```bash
opencode auth login
```

Pick a provider (Anthropic / OpenAI / OpenRouter). Confirm a quick `opencode` REPL session works outside SciQLop first.

- [ ] **Step 3: Install the plugin into the SciQLop env**

```bash
pip install -e sciqlop_opencode/
pip install opencode-agent-sdk
```

- [ ] **Step 4: Launch SciQLop and verify backend appears**

Run SciQLop. In the agent chat dock dropdown, **Opencode** should appear alongside Claude/Copilot/Albert. Switch to it.

- [ ] **Step 5: Read-only smoke**

Without enabling "Allow write actions", ask:

> What panels are currently open?

Expected: the agent calls `sciqlop_list_panels` / `sciqlop_window_state` and reports back. Tool results stream cleanly. No permission prompts.

- [ ] **Step 6: Gated-tool smoke**

Enable "Allow write actions". Ask:

> Create a new panel and tell me its name.

Expected: agent calls `sciqlop_create_panel`. The SciQLop confirm modal appears. Approve. New panel appears in the workspace.

Then ask:

> Run `print("hello")` in the embedded Python kernel.

Expected: confirm modal appears for `sciqlop_exec_python`. Approve. Output appears.

- [ ] **Step 7: Deny path**

With writes still allowed, ask the agent to delete something or run a destructive command. Click **Deny** in the confirm modal. Expected: agent receives "user denied" and reports back gracefully — does not retry or crash.

- [ ] **Step 8: Session resume**

Quit SciQLop. Relaunch. Open the agent dock, look at the session list. Pick the previous session. Expected: full message history reappears in the dock; new messages continue from where you left off.

- [ ] **Step 9: Disable & re-enable writes mid-conversation**

Mid-conversation, toggle "Allow write actions" off. Ask the agent to do something gated. Expected: it gets the "writes disabled" deny message and tells the user.

- [ ] **Step 10: Provider auth missing**

```bash
opencode auth logout
```

Try to ask a question. Expected: a graceful error message in the chat dock pointing the user to `opencode auth login`, not a hard crash.

- [ ] **Step 11: Open PR**

```bash
git push -u origin feat/sciqlop-opencode
gh pr create --title "feat: sciqlop_opencode plugin" --body "$(cat <<'EOF'
## Summary
- New sibling plugin `sciqlop_opencode` providing an opencode-backed agent in the SciQLop chat dock.
- Mirrors `sciqlop_claude` structure, uses `opencode-agent-sdk` in subprocess mode (`opencode acp`).
- Auth delegated to the opencode CLI — users run `opencode auth login` once, no API-key field in SciQLop settings.
- Permission gating via `PreToolUse` hook with sync/async bridge to the qasync loop.

## Test plan
- [ ] `pytest sciqlop_opencode/sciqlop_opencode/tests/` passes
- [ ] Manual smoke per `docs/superpowers/plans/2026-05-16-sciqlop-opencode-plugin.md` Task 10

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Out of scope (deferred — track separately)

- Sharing code between `sciqlop_claude` and `sciqlop_opencode` backends — clone-and-adapt now; revisit if a third SDK-shaped backend lands.
- HTTP-mode operation (talking to an external `opencode serve`). Subprocess mode is enough for the dock.
- Custom opencode plugins / per-project agent config under `.opencode/`. Users configure opencode globally.
- API-key field in the SciQLop settings panel. opencode CLI auth only.
