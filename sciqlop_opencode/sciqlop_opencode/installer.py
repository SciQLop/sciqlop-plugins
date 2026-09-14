"""One-click opencode install through the bundled npm.

Same mechanism as `npm i -g opencode-ai` (a thin wrapper plus a ~180 MB
platform binary via optionalDependencies), but into a user-writable prefix
under SciQLop's user-data dir: no admin rights, and it survives SciQLop
updates, which wipe the bundled node dir. The launcher already prepends the
bundled node dir to the child's PATH, so `npm` resolves via `shutil.which`
— in a dev checkout without bundled node it falls back to a system npm.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

from .backend import NPM_PACKAGE, managed_prefix


def find_npm() -> Optional[str]:
    """Bundled npm first (launcher puts it on PATH), else a system one."""
    return shutil.which("npm")


def _node_for_npm(npm: str) -> Optional[str]:
    """node binary shipped next to the npm entry point.

    Both the SciQLop-bundled layout and a system Node.js install keep
    node(.exe) next to npm(.cmd); falls back to PATH when it isn't there.
    """
    here = Path(npm).parent
    for name in ("node.exe", "node"):
        candidate = here / name
        if candidate.is_file():
            return str(candidate)
    return shutil.which("node")


def _npm_cli_js(npm: str) -> Optional[str]:
    """npm's real entry point, bypassing the platform wrapper script.

    Spawning `npm` directly works on posix (shebang script) but not on
    Windows, where it resolves to npm.cmd — which CreateProcess cannot run
    without a shell. `node npm-cli.js` behaves identically everywhere.
    """
    cli = Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
    return str(cli) if cli.is_file() else None


def install_command(prefix: Path) -> List[str]:
    """npm argv installing opencode-ai into `prefix`. No `-g`: the global
    prefix would land inside the SciQLop install dir."""
    npm = find_npm()
    if npm is None:
        raise RuntimeError(
            "npm not found — install Node.js from https://nodejs.org, "
            "then run `npm i -g opencode-ai` manually."
        )
    node = _node_for_npm(npm)
    cli = _npm_cli_js(npm)
    if node is not None and cli is not None:
        argv = [node, cli]
    else:
        # Unknown layout: spawn the entry point directly. Works on posix;
        # on Windows only when it resolves to something CreateProcess runs.
        argv = [npm]
    return argv + [
        "install",
        "--prefix",
        str(prefix),
        "--no-audit",
        "--no-fund",
        NPM_PACKAGE,
    ]


def run_install(
    command: List[str], on_line: Optional[Callable[[str], None]] = None
) -> None:
    """Run the install, streaming output lines. Raises with the tail on failure."""
    tail: List[str] = []
    popen_kwargs = {}
    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        # Don't flash a console window from the GUI on Windows.
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    with subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        **popen_kwargs,
    ) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            tail.append(line)
            tail[:] = tail[-20:]
            if on_line is not None:
                on_line(line)
    if proc.returncode != 0:
        raise RuntimeError("opencode install failed:\n" + "\n".join(tail))


def ensure_managed_prefix() -> Path:
    """Create the user-data prefix the managed install lives in."""
    prefix = managed_prefix()
    if prefix is None:  # pragma: no cover — storage import never fails in-app
        raise RuntimeError("SciQLop storage unavailable — cannot stage install.")
    prefix.mkdir(parents=True, exist_ok=True)
    return prefix
