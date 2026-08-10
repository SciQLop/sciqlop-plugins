"""opencode backend for SciQLop's agent chat dock, over ACP.

Transport, tool serving, streaming, permissions, usage and session
list/resume/replay all live in `SciQLop.components.agents.acp`; this module
supplies only what is opencode-specific: the `opencode acp` command line and
the model dropdown. Auth belongs to the CLI — the user runs
`opencode auth login` once, nothing to configure in SciQLop.

Model discovery goes through ACP rather than opencode's own config files:
`session/new` enumerates the models for the providers the user is actually
authenticated for, and the values it returns are the only ones
`session/set_config_option` accepts.
"""
from __future__ import annotations

import shutil
from typing import List, Optional, Tuple

from SciQLop.components.agents.acp import AcpAgentBackend
from SciQLop.components.agents.acp.sessions import acp_config_options

ACP_COMMAND = ["opencode", "acp"]

_DEFAULT_MODEL_CHOICES: List[Tuple[str, Optional[str]]] = [
    ("Default (opencode)", None),
]


class OpencodeBackend(AcpAgentBackend):
    display_name = "Opencode"
    model_choices: List[Tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    supports_sessions = True
    cli_label = "opencode"

    def acp_command(self) -> List[str]:
        return list(ACP_COMMAND)

    def check_prerequisites(self) -> None:
        if shutil.which(ACP_COMMAND[0]) is None:
            raise RuntimeError(
                "opencode CLI not found on PATH — install it from "
                "https://opencode.ai and run `opencode auth login`."
            )


def fetch_models() -> List[Tuple[str, Optional[str]]]:
    """Model dropdown choices, read from a throwaway ACP session.

    The dropdown is built at plugin load, before any session exists, so there
    is nothing to query but a short-lived agent. Falls back to the single
    "Default" entry — which lets opencode pick — when the CLI is absent or the
    handshake fails.
    """
    choices = list(_DEFAULT_MODEL_CHOICES)
    if shutil.which(ACP_COMMAND[0]) is None:
        return choices
    models = acp_config_options(ACP_COMMAND).get("model", [])
    choices.extend((label, value) for label, value in models if value)
    return choices
