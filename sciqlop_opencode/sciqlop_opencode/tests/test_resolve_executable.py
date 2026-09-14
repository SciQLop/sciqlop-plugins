"""Executable resolution: the `opencode` binary must be found even when the
GUI process inherits a minimal PATH (macOS Finder/Dock launch drops
/opt/homebrew/bin, ~/.local/bin, ~/.opencode/bin)."""

import os

import pytest


def _mod():
    import sciqlop_opencode.backend as bk

    return bk


def test_resolve_prefers_managed_prefix_over_path(monkeypatch, tmp_path):
    bk = _mod()
    monkeypatch.setattr(bk, "managed_executable", lambda: str(tmp_path / "opencode"))
    monkeypatch.setattr(bk.shutil, "which", lambda _: "/usr/bin/opencode")
    assert bk.resolve_opencode_executable() == str(tmp_path / "opencode")


def test_resolve_falls_back_to_which(monkeypatch):
    bk = _mod()
    monkeypatch.setattr(bk, "managed_executable", lambda: None)
    monkeypatch.setattr(bk.shutil, "which", lambda _: "/usr/bin/opencode")
    assert bk.resolve_opencode_executable() == "/usr/bin/opencode"


def test_resolve_checks_well_known_paths_when_which_misses(monkeypatch):
    bk = _mod()
    monkeypatch.setattr(bk, "managed_executable", lambda: None)
    monkeypatch.setattr(bk.shutil, "which", lambda _: None)
    # the macOS Homebrew default, invisible to Finder-launched apps
    monkeypatch.setattr(
        bk, "_well_known_candidates", lambda: ["/opt/homebrew/bin/opencode"]
    )
    monkeypatch.setattr(os.path, "isfile", lambda p: p == "/opt/homebrew/bin/opencode")
    monkeypatch.setattr(os, "access", lambda p, _m: True)
    monkeypatch.setattr(
        bk,
        "_shell_probe",
        lambda: (_ for _ in ()).throw(
            AssertionError("must not probe the shell when a known path hits")
        ),
    )
    assert bk.resolve_opencode_executable() == "/opt/homebrew/bin/opencode"


def test_resolve_skips_non_executable_candidates(monkeypatch):
    bk = _mod()
    monkeypatch.setattr(bk, "managed_executable", lambda: None)
    monkeypatch.setattr(bk.shutil, "which", lambda _: None)
    monkeypatch.setattr(
        bk, "_well_known_candidates", lambda: ["/usr/local/bin/opencode"]
    )
    monkeypatch.setattr(os.path, "isfile", lambda _: True)
    monkeypatch.setattr(os, "access", lambda p, _m: False)
    monkeypatch.setattr(bk, "_shell_probe", lambda: None)
    assert bk.resolve_opencode_executable() is None


def test_resolve_uses_login_shell_probe_as_last_resort(monkeypatch):
    bk = _mod()
    monkeypatch.setattr(bk, "managed_executable", lambda: None)
    monkeypatch.setattr(bk.shutil, "which", lambda _: None)
    monkeypatch.setattr(bk, "_well_known_candidates", lambda: [])
    monkeypatch.setattr(bk, "_shell_probe", lambda: "/Users/x/.local/bin/opencode")
    assert bk.resolve_opencode_executable() == "/Users/x/.local/bin/opencode"


def test_resolve_returns_none_when_nothing_found(monkeypatch):
    bk = _mod()
    monkeypatch.setattr(bk, "managed_executable", lambda: None)
    monkeypatch.setattr(bk.shutil, "which", lambda _: None)
    monkeypatch.setattr(bk, "_well_known_candidates", lambda: [])
    monkeypatch.setattr(bk, "_shell_probe", lambda: None)
    assert bk.resolve_opencode_executable() is None


def test_acp_command_uses_resolved_absolute_path(monkeypatch):
    bk = _mod()
    monkeypatch.setattr(
        bk, "resolve_opencode_executable", lambda: "/opt/homebrew/bin/opencode"
    )
    backend = bk.OpencodeBackend.__new__(bk.OpencodeBackend)
    assert backend.acp_command() == ["/opt/homebrew/bin/opencode", "acp"]


def test_acp_command_raises_actionable_error_when_missing(monkeypatch):
    bk = _mod()
    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: None)
    backend = bk.OpencodeBackend.__new__(bk.OpencodeBackend)
    with pytest.raises(RuntimeError, match="opencode auth login"):
        backend.acp_command()


def test_missing_cli_gate_lives_at_spawn_not_construction(monkeypatch):
    # check_prerequisites must stay lenient: AcpAgentBackend.__init__ calls it,
    # and raising there would make construction — and the on_activated install
    # offer — unreachable exactly when the CLI is missing.
    bk = _mod()
    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: None)
    backend = bk.OpencodeBackend.__new__(bk.OpencodeBackend)
    assert backend.check_prerequisites() is None
    with pytest.raises(RuntimeError, match="opencode auth login") as exc:
        backend.acp_command()
    assert (
        "opencode-ai" in str(exc.value)
        or "brew" in str(exc.value)
        or "npm" in str(exc.value)
    )


def test_fetch_models_uses_resolved_command(monkeypatch):
    bk = _mod()
    seen = []
    monkeypatch.setattr(
        bk, "resolve_opencode_executable", lambda: "/opt/homebrew/bin/opencode"
    )
    monkeypatch.setattr(
        bk, "acp_config_options", lambda cmd: seen.append(cmd) or {"model": []}
    )
    assert bk.fetch_models() == [("Default (opencode)", None)]
    assert seen == [["/opt/homebrew/bin/opencode", "acp"]]


def test_managed_executable_finds_postinstall_binary(monkeypatch, tmp_path):
    bk = _mod()
    bindir = tmp_path / "node_modules" / "opencode-ai" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "opencode.exe").write_bytes(b"fake")
    monkeypatch.setattr(bk, "managed_prefix", lambda: tmp_path)
    assert bk.managed_executable() == str(bindir / "opencode.exe")


def test_managed_executable_returns_none_when_absent(monkeypatch, tmp_path):
    bk = _mod()
    monkeypatch.setattr(bk, "managed_prefix", lambda: tmp_path)
    assert bk.managed_executable() is None


def test_resolve_rejects_windows_shell_shims(monkeypatch):
    # shutil.which follows PATHEXT, so a global `npm i -g opencode-ai` shows
    # up as opencode.cmd — unspawnable without a shell, must not be returned.
    bk = _mod()
    monkeypatch.setattr(bk, "managed_executable", lambda: None)
    monkeypatch.setattr(
        bk.shutil, "which", lambda _: r"C:\Users\x\AppData\npm\opencode.cmd"
    )
    monkeypatch.setattr(bk, "_well_known_candidates", lambda: [])
    monkeypatch.setattr(bk, "_shell_probe", lambda: None)
    monkeypatch.setattr(bk.os, "name", "nt")
    assert bk.resolve_opencode_executable() is None


def test_shim_check_is_posix_inert(monkeypatch):
    bk = _mod()
    monkeypatch.setattr(bk.os, "name", "posix")
    assert bk._is_unspawnable_shim("/usr/local/bin/opencode.cmd") is False
