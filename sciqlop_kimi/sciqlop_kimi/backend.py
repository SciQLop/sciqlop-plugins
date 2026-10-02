"""Kimi Code backend for SciQLop's agent chat dock, over ACP.

All transport, tool-serving, streaming, permission and session machinery
lives in `SciQLop.components.agents.acp`; this module supplies only what is
Kimi-specific: the `kimi acp` command line and model discovery from the
user's Kimi Code config. Auth belongs to the CLI — the user runs
`kimi login` once, nothing to configure in SciQLop.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from SciQLop.components.agents.acp import AcpAgentBackend

_DEFAULT_MODEL_CHOICES: List[tuple[str, Optional[str]]] = [
    ("Default (Kimi Code)", None),
]


class KimiBackend(AcpAgentBackend):
    display_name = "Kimi"
    model_choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    supports_sessions = True
    cli_label = "Kimi Code"

    def acp_command(self) -> List[str]:
        if shutil.which("kimi") is None:
            raise RuntimeError("kimi CLI not found on PATH — install Kimi Code first.")
        return ["kimi", "acp"]

    def check_prerequisites(self) -> None:
        # Deliberately lenient, like OpencodeBackend: AcpAgentBackend.__init__ calls
        # this, and raising here escapes the agent dock's construction and fails the
        # load() of this and every later agent plugin. acp_command() is the gate, at
        # spawn time, and its error shows in the chat.
        return None


def fetch_models() -> List[tuple[str, Optional[str]]]:
    """Model dropdown choices from the user's Kimi Code config file.

    The ACP server reports the same list per session, but the dropdown is
    built before any session exists; parsing the config TOML directly avoids
    spawning a throwaway agent at plugin load.
    """
    choices: List[tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    config = Path.home() / ".kimi-code" / "config.toml"
    try:
        import tomllib
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except Exception:
        return choices
    default = data.get("default_model") or ""
    for name, spec in (data.get("models") or {}).items():
        if not name or name == default:
            continue
        label = spec.get("display_name") or name if isinstance(spec, dict) else name
        choices.append((label, name))
    return choices
