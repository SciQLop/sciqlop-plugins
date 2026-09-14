"""Managed opencode install via the bundled npm: same mechanism as
`npm i -g opencode-ai`, but into a user-writable prefix so it needs no
admin rights and survives SciQLop updates (which wipe the bundled node dir)."""

import subprocess


def _mod():
    import sciqlop_opencode.installer as inst

    return inst


def test_install_command_targets_user_prefix(monkeypatch, tmp_path):
    inst = _mod()
    monkeypatch.setattr(inst.shutil, "which", lambda _: "/x/node/npm")
    cmd = inst.install_command(tmp_path)
    assert cmd[:2] == ["/x/node/npm", "install"]
    assert "--prefix" in cmd and str(tmp_path) in cmd
    assert "opencode-ai" in cmd
    assert "-g" not in cmd


def test_install_command_raises_without_npm(monkeypatch, tmp_path):
    import pytest

    inst = _mod()
    monkeypatch.setattr(inst.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="[Nn]pm"):
        inst.install_command(tmp_path)


def test_run_install_streams_progress_and_checks_exit(monkeypatch, tmp_path):
    inst = _mod()
    lines = []

    class _Proc:
        returncode = 0

        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @property
        def stdout(self):
            return ["added 3 packages"]

    monkeypatch.setattr(inst.subprocess, "Popen", _Proc)
    inst.run_install(["npm", "install", "opencode-ai"], on_line=lines.append)
    assert lines == ["added 3 packages"]


def test_run_install_raises_on_failure(monkeypatch):
    import pytest

    inst = _mod()

    class _Proc:
        returncode = 1

        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @property
        def stdout(self):
            return ["npm ERR! boom"]

    monkeypatch.setattr(inst.subprocess, "Popen", _Proc)
    with pytest.raises(RuntimeError, match="boom"):
        inst.run_install(["npm", "install", "opencode-ai"])


def test_install_command_spawns_node_with_cli_js(monkeypatch, tmp_path):
    # Windows: npm resolves to npm.cmd, which CreateProcess cannot run —
    # so the install must go through `node npm-cli.js` instead.
    inst = _mod()
    node = tmp_path / "node.exe"
    node.write_bytes(b"fake")
    npm = tmp_path / "npm.cmd"
    npm.write_bytes(b"fake")
    cli = tmp_path / "node_modules" / "npm" / "bin" / "npm-cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"fake")
    monkeypatch.setattr(inst.shutil, "which", lambda _: str(npm))
    cmd = inst.install_command(tmp_path / "prefix")
    assert cmd[:2] == [str(node), str(cli)]
    assert "--prefix" in cmd and "opencode-ai" in cmd


def test_install_command_falls_back_to_npm_entry_point(monkeypatch, tmp_path):
    # Unknown layout (no node / npm-cli.js next to npm): keep the old
    # behavior rather than refusing to install.
    inst = _mod()
    monkeypatch.setattr(inst.shutil, "which", lambda _: "/x/node/npm")
    monkeypatch.setattr(inst, "_node_for_npm", lambda _npm: None)
    monkeypatch.setattr(inst, "_npm_cli_js", lambda _npm: None)
    assert inst.install_command(tmp_path)[:2] == ["/x/node/npm", "install"]
