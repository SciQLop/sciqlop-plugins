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

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from SciQLop.components.agents.acp import AcpAgentBackend
from SciQLop.components.agents.acp.sessions import acp_config_options

NPM_PACKAGE = "@opencode/cli"
# Managed installs made before the opencode 2 switch; still runnable.
LEGACY_NPM_PACKAGE = "opencode-ai"
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

    Verified against a real `npm install --prefix P @opencode/cli`:
    `P/node_modules/@opencode/cli/bin/opencode.exe` is the platform binary
    (an ELF on Linux despite the name); v1's `opencode-ai` used the same
    layout. The bin/ path is used because on Windows npm only writes
    `.cmd`/`.ps1` shims into `.bin`, which can't be spawned without a shell.
    """
    prefix = managed_prefix()
    if prefix is None:
        return None
    candidates = [
        prefix / "node_modules" / package / "bin" / name
        for package in (NPM_PACKAGE, LEGACY_NPM_PACKAGE)
        for name in ("opencode.exe", "opencode")
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


def opencode_major_version(exe: str) -> Optional[int]:
    """Major version of the CLI at `exe`, or None when it can't be told.

    v1 prints `1.19.0`, v2 prints `opencode v2.0.29`.
    """
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"(\d+)\.\d+\.\d+", proc.stdout)
    return int(match.group(1)) if match else None


def is_managed(exe: str) -> bool:
    """True when `exe` is our own npm install, not one the user made."""
    prefix = managed_prefix()
    return prefix is not None and Path(exe).is_relative_to(prefix)


def _missing_message() -> str:
    if os.name == "nt":
        install = (
            "install it with `scoop install opencode`, `choco install opencode` or "
            "`npm i -g @opencode/cli` — or click Install when the dock offers it. "
            "A WSL-only install is not reachable from native SciQLop."
        )
    elif sys.platform == "darwin":
        install = "install it with `brew install anomalyco/tap/opencode` or `npm i -g @opencode/cli`."
    else:
        install = "install it with `curl -fsSL https://opencode.ai/install | bash` or `npm i -g @opencode/cli`."
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
        # Checked on every spawn, not cached: `opencode upgrade --major`
        # replaces the binary at the same path.
        if opencode_major_version(exe) == 1:
            raise RuntimeError(
                "opencode 1 is no longer supported — SciQLop needs opencode 2. "
                "Reopen the Opencode backend to upgrade, or run `opencode upgrade --major`."
            )
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
    return _promote(choices, best_free_model(model_metadata(exe)))


def _promote(choices: List[Tuple[str, Optional[str]]], value: Optional[str]):
    """Move `value` to the top; a no-op when ACP did not offer it."""
    if value is None:
        return choices
    return sorted(choices, key=lambda choice: choice[1] != value)


def model_metadata(exe: str) -> Dict[str, dict]:
    """Per-model metadata (cost, capabilities, release date) from the CLI.

    ACP's model list carries only labels and values, so ranking needs this
    second, bounded call. `--standalone` runs a private server for the call:
    plain `opencode api` would start opencode's persistent background service.
    Any failure just means no promotion.
    """
    try:
        proc = subprocess.run(
            [exe, "api", "--standalone", "model.list"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_model_list(proc.stdout)


def parse_model_list(text: str) -> Dict[str, dict]:
    """`{provider/id: meta}` from the `model.list` JSON response."""
    try:
        data = json.loads(text).get("data")
    except (json.JSONDecodeError, AttributeError):
        return {}
    if not isinstance(data, list):
        return {}
    return {
        f"{meta['providerID']}/{meta['id']}": meta
        for meta in data
        if isinstance(meta, dict) and "providerID" in meta and "id" in meta
    }


def _base_cost(meta: dict) -> dict:
    # `cost` is a list of pricing tiers; the first is the base rate.
    tiers = meta.get("cost") or [{}]
    return tiers[0] if isinstance(tiers[0], dict) else {}


def _is_free_agent_model(meta: dict) -> bool:
    cost = _base_cost(meta)
    capabilities = meta.get("capabilities") or {}
    return (
        meta.get("status", "active") == "active"
        and cost.get("input") == 0
        and cost.get("output") == 0
        and capabilities.get("tools") is True
        # The agent inspects plot screenshots; text-only models can't see them.
        and "image" in (capabilities.get("input") or [])
    )


def _free_model_rank(meta: dict) -> Tuple[bool, int, int]:
    # simplify: opencode exposes no quality score, so "best" is a proxy —
    # reasoning (effort variants), then newest (free tiers rotate in fresh
    # models), then context. Upgrade path: join a benchmark leaderboard if
    # this picks poorly.
    return (
        bool(meta.get("variants")),
        (meta.get("time") or {}).get("released") or 0,
        (meta.get("limit") or {}).get("context") or 0,
    )


def best_free_model(metadata: Dict[str, dict]) -> Optional[str]:
    """Value of the highest-ranked free, active model with tools and image input."""
    candidates = {key: meta for key, meta in metadata.items() if _is_free_agent_model(meta)}
    return max(candidates, key=lambda key: _free_model_rank(candidates[key]), default=None)
