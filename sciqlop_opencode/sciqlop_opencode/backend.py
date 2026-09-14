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

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

from SciQLop.components.agents.acp import AcpAgentBackend
from SciQLop.components.agents.acp.sessions import acp_config_options

NPM_PACKAGE = "opencode-ai"
MANAGED_DIRNAME = "opencode"

_DEFAULT_MODEL_CHOICES: List[Tuple[str, Optional[str]]] = [
    ("Default (opencode)", None),
]


def managed_prefix() -> Optional[Path]:
    """User-writable prefix holding the npm-managed opencode install."""
    try:
        from SciQLop.components.storage import user_data_dir
    except Exception:
        return None
    return user_data_dir(MANAGED_DIRNAME, create=False)


def managed_executable() -> Optional[str]:
    """Real binary npm's postinstall drops under the managed prefix.

    Verified against a real `npm install --prefix P opencode-ai`:
    `P/node_modules/opencode-ai/bin/opencode.exe` is the platform binary
    (an ELF on Linux despite the name). The bin/ path is used because on
    Windows npm only writes `.cmd`/`.ps1` shims into `.bin`, which can't be
    spawned without a shell.
    """
    prefix = managed_prefix()
    if prefix is None:
        return None
    candidates = [
        prefix / "node_modules" / NPM_PACKAGE / "bin" / "opencode.exe",
        prefix / "node_modules" / NPM_PACKAGE / "bin" / "opencode",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _well_known_candidates() -> List[str]:
    """Install locations invisible to GUI-launched processes.

    macOS apps started from Finder/Dock inherit a minimal PATH without
    /opt/homebrew/bin or ~/.local/bin; the install script defaults to
    ~/.opencode/bin, which is rarely on PATH either.
    """
    if os.name == "nt":
        # .exe only: create_subprocess_exec spawns without a shell, so the
        # .cmd shims npm drops next to them are unreachable to us.
        roots = [
            os.path.expandvars(r"%USERPROFILE%\.opencode\bin"),
            os.path.expandvars(r"%USERPROFILE%\scoop\shims"),
            os.path.expandvars(r"%APPDATA%\npm"),
        ]
        return [str(Path(root) / "opencode.exe") for root in roots]
    candidates = ["/opt/homebrew/bin/opencode", "/usr/local/bin/opencode"]
    home = Path.home()
    for sub in (".local/bin/opencode", "bin/opencode", ".opencode/bin/opencode"):
        candidates.append(str(home / sub))
    return candidates


def _shell_probe() -> Optional[str]:
    """Ask a login shell where opencode is, for dotfile-only PATH entries.

    Bounded and last-resort: plugin load must never hang on this.
    """
    if os.name == "nt":
        return None
    for shell in ("/bin/zsh", "/bin/bash", "/bin/sh"):
        if not os.path.isfile(shell):
            continue
        try:
            proc = subprocess.run(
                [shell, "-lc", "which opencode"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except Exception:
            continue
        for line in proc.stdout.splitlines():
            path = line.strip()
            if path and os.path.isfile(path):
                return path
    return None


def _is_unspawnable_shim(path: str) -> bool:
    """True for Windows shell shims (npm's .cmd/.ps1/.bat wrappers).

    shutil.which follows PATHEXT, so on Windows it happily returns an
    `opencode.cmd` that create_subprocess_exec (no shell) cannot spawn.
    Never reject on posix: there the npm wrapper is a real script.
    """
    return os.name == "nt" and Path(path).suffix.lower() in (".cmd", ".bat", ".ps1")


def resolve_opencode_executable() -> Optional[str]:
    """Absolute path to the opencode binary, or None when not installed."""
    managed = managed_executable()
    if managed is not None:
        return managed
    on_path = shutil.which("opencode")
    if on_path is not None and not _is_unspawnable_shim(on_path):
        return on_path
    for candidate in _well_known_candidates():
        if os.path.isfile(candidate) and (
            os.name == "nt" or os.access(candidate, os.X_OK)
        ):
            return candidate
    return _shell_probe()


def _missing_message() -> str:
    if os.name == "nt":
        install = (
            "install it with `scoop install opencode`, `choco install opencode` or "
            "`npm i -g opencode-ai` — or click Install when the dock offers it. "
            "A WSL-only install is not reachable from native SciQLop."
        )
    elif sys.platform == "darwin":
        install = "install it with `brew install anomalyco/tap/opencode` or `npm i -g opencode-ai`."
    else:
        install = "install it with `curl -fsSL https://opencode.ai/install | bash` or `npm i -g opencode-ai`."
    return f"opencode CLI not found — {install} Then run `opencode auth login` once."


class OpencodeBackend(AcpAgentBackend):
    display_name = "Opencode"
    model_choices: List[Tuple[str, Optional[str]]] = list(_DEFAULT_MODEL_CHOICES)
    supports_sessions = True
    cli_label = "opencode"

    def acp_command(self) -> List[str]:
        exe = resolve_opencode_executable()
        if exe is None:
            raise RuntimeError(_missing_message())
        return [exe, "acp"]

    def check_prerequisites(self) -> None:
        # Deliberately lenient: AcpAgentBackend.__init__ calls this, and
        # raising here would make backend construction — and the on_activated
        # install offer — unreachable exactly when the CLI is missing. The
        # spawn-time gate is acp_command(), which raises instead; connection
        # setup is lazy and retries on the next turn, so installing mid-bind
        # heals the session without a restart.
        return None


def fetch_models() -> List[Tuple[str, Optional[str]]]:
    """Model dropdown choices, read from a throwaway ACP session.

    The dropdown is built at plugin load, before any session exists, so there
    is nothing to query but a short-lived agent. Falls back to the single
    "Default" entry — which lets opencode pick — when the CLI is absent or the
    handshake fails.
    """
    choices = list(_DEFAULT_MODEL_CHOICES)
    exe = resolve_opencode_executable()
    if exe is None:
        return choices
    models = acp_config_options([exe, "acp"]).get("model", [])
    choices.extend((label, value) for label, value in models if value)
    return choices
