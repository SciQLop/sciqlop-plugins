"""Enumerate and replay prior opencode sessions from its SQLite store.

opencode 1.x persists everything in a single SQLite database at
``${OPENCODE_DATA_DIR:-~/.local/share/opencode}/opencode.db``:

* ``session`` rows hold metadata (directory, title, time_updated, model JSON).
* ``message`` rows hold per-turn metadata indexed by ``session_id``.
* ``part`` rows hold the actual content chunks (text/reasoning/tool/...)
  indexed by ``message_id``.

We list sessions whose ``directory`` matches the current SciQLop workspace
and replay them by joining message → part, keeping only the renderable
``text`` parts (reasoning/tool/step-* parts belong to the agent loop and
have no place in a replay).
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
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


def _data_dir() -> Path:
    env = os.environ.get("OPENCODE_DATA_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".local" / "share" / "opencode"


def _db_path() -> Path:
    return _data_dir() / "opencode.db"


def _open_db() -> Optional[sqlite3.Connection]:
    path = _db_path()
    if not path.is_file():
        return None
    try:
        # Read-only URI keeps us from blocking opencode itself if it's running.
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def list_sessions(limit: Optional[int] = None) -> List[SessionEntry]:
    """Every session for the workspace, most recent first; `limit` truncates.

    Listing is complete by default: SciQLop keeps sessions the user renamed or
    grouped indefinitely, and a truncation here would hide them before it can
    decide. (SQLite reads a negative LIMIT as "no limit".)
    """
    workspace = str(current_workspace_dir())
    conn = _open_db()
    if conn is None:
        return []
    try:
        with closing(conn):
            rows = conn.execute(
                "SELECT id, title, time_updated FROM session "
                "WHERE directory = ? "
                "ORDER BY time_updated DESC LIMIT ?",
                (workspace, -1 if limit is None else limit),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [
        SessionEntry(
            session_id=row[0],
            path=_db_path(),
            mtime=(row[2] or 0) / 1000.0,
            label=_shorten(row[1] or "") or "(untitled session)",
        )
        for row in rows
    ]


_RENDERABLE_PART_TYPES = {"text"}


def load_session_messages(
    session_id: str,
    image_tempdir: Optional[Path] = None,
):
    """Replay a session into a list of `ChatMessage`.

    The SciQLop dock only renders text and images; opencode's reasoning,
    step-start/finish, tool, and patch parts belong to the internal agent
    loop and aren't useful as visible history. We filter to ``text`` parts
    only. ``image_tempdir`` is accepted for API parity with other backends
    but unused — opencode doesn't store inline image data in the part table
    in this schema version.
    """
    from SciQLop.components.agents.chat import ChatMessage, TextBlock

    conn = _open_db()
    if conn is None:
        return []
    try:
        with closing(conn):
            msg_rows = conn.execute(
                "SELECT id, data FROM message "
                "WHERE session_id = ? ORDER BY time_created",
                (session_id,),
            ).fetchall()
            messages: list = []
            for msg_id, msg_data_json in msg_rows:
                role = _role_from_message(msg_data_json)
                if role is None:
                    continue
                part_rows = conn.execute(
                    "SELECT data FROM part WHERE message_id = ? ORDER BY time_created",
                    (msg_id,),
                ).fetchall()
                blocks = _blocks_from_parts(part_rows, TextBlock)
                if not blocks:
                    continue
                if messages and messages[-1].role == role:
                    messages[-1].blocks.extend(blocks)
                else:
                    messages.append(ChatMessage(role=role, blocks=blocks, done=True))
            return messages
    except sqlite3.Error:
        return []


def _role_from_message(data_json: str) -> Optional[str]:
    try:
        data = json.loads(data_json)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    role = data.get("role")
    return role if role in ("user", "assistant") else None


def _blocks_from_parts(part_rows, TextBlock) -> list:
    blocks: list = []
    for (data_json,) in part_rows:
        try:
            part = json.loads(data_json)
        except (ValueError, TypeError):
            continue
        if not isinstance(part, dict):
            continue
        if part.get("type") not in _RENDERABLE_PART_TYPES:
            continue
        text = part.get("text") or ""
        if text.strip():
            blocks.append(TextBlock(text=text))
    return blocks


def known_session_models() -> List[dict]:
    """Return the distinct ``model`` JSON blobs seen in prior sessions.

    Used to populate the model dropdown with whatever the user has
    actually run. Returns ``[]`` if the DB is missing or empty.
    """
    conn = _open_db()
    if conn is None:
        return []
    try:
        with closing(conn):
            rows = conn.execute(
                "SELECT DISTINCT model FROM session "
                "WHERE model IS NOT NULL AND model != ''",
            ).fetchall()
    except sqlite3.Error:
        return []
    models: list = []
    seen: set = set()
    for (raw,) in rows:
        try:
            spec = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(spec, dict):
            continue
        key = (spec.get("providerID"), spec.get("id"))
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        models.append(spec)
    return models


def _models_cache_path() -> Optional[Path]:
    """Locate opencode's cached models.json.

    opencode fetches https://models.dev/api.json and caches it locally at
    ``Global.Path.cache/models.json`` (where the cache dir follows platform
    conventions). Resolution order:
    1. ``$OPENCODE_MODELS_PATH`` env var (opencode's own override)
    2. Platform-native cache dir for ``opencode`` (via platformdirs)
    """
    env = os.environ.get("OPENCODE_MODELS_PATH")
    if env:
        p = Path(env)
        if p.is_file():
            return p
    try:
        from platformdirs import user_cache_path

        cache_dir = user_cache_path("opencode", ensure_exists=False)
    except ImportError:
        # Fallback: mimic opencode's xdgCache resolution
        xdg_cache = os.environ.get("XDG_CACHE_HOME")
        if xdg_cache:
            cache_dir = Path(xdg_cache) / "opencode"
        else:
            cache_dir = Path.home() / ".cache" / "opencode"
    models_file = Path(cache_dir) / "models.json"
    return models_file if models_file.is_file() else None


def configured_models(timeout: float = 5.0) -> List[dict]:
    """Return every model opencode can serve, by reading its cached models.json.

    opencode maintains a cache at ``~/.cache/opencode/models.json`` (or
    ``$OPENCODE_MODELS_PATH``) fetched from https://models.dev. The file is a
    JSON object keyed by provider ID, each containing a ``models`` dict. We
    flatten this into ``{"providerID": ..., "id": ...}`` entries, preserving
    opencode's provider ordering (opencode providers first, then rest
    alphabetically).

    This avoids subprocess calls (won't work on Windows, requires opencode on
    PATH) and reads the same source the CLI uses. Falls back to [] if the
    cache is missing or unreadable.
    """
    cache_path = _models_cache_path()
    if cache_path is None:
        return []
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    models: list = []
    seen: set = set()
    # Sort providers: opencode* first, then alphabetical (matches `opencode models` output)
    provider_ids = sorted(
        data.keys(),
        key=lambda pid: (not pid.startswith("opencode"), pid),
    )
    for provider_id in provider_ids:
        provider_data = data.get(provider_id)
        if not isinstance(provider_data, dict):
            continue
        models_dict = provider_data.get("models")
        if not isinstance(models_dict, dict):
            continue
        for model_id, model_spec in sorted(models_dict.items()):
            if not isinstance(model_spec, dict):
                continue
            # Use canonical providerID/id from the spec if present, else fall back to keys
            canonical_provider = model_spec.get("providerID") or provider_id
            canonical_id = model_spec.get("id") or model_id
            if not canonical_provider or not canonical_id:
                continue
            key = (canonical_provider, canonical_id)
            if key in seen:
                continue
            seen.add(key)
            models.append({"providerID": canonical_provider, "id": canonical_id})
    return models


def _shorten(text: str, max_len: int = 80) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) > max_len:
        return collapsed[: max_len - 1] + "…"
    return collapsed
