"""Offer to move an opencode 1 install to opencode 2."""
import subprocess


def _version_run(stdout):
    def fake_run(cmd, **_kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return fake_run


def test_major_version_reads_both_version_formats(monkeypatch):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk.subprocess, "run", _version_run("1.19.0\n"))
    assert bk.opencode_major_version("/x/opencode") == 1
    monkeypatch.setattr(bk.subprocess, "run", _version_run("opencode v2.0.29\n"))
    assert bk.opencode_major_version("/x/opencode") == 2


def test_major_version_is_none_when_unknown(monkeypatch):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk.subprocess, "run", _version_run("garbage"))
    assert bk.opencode_major_version("/x/opencode") is None

    def boom(*_a, **_k):
        raise OSError("gone")

    monkeypatch.setattr(bk.subprocess, "run", boom)
    assert bk.opencode_major_version("/x/opencode") is None


def test_is_managed_only_under_our_prefix(monkeypatch, tmp_path):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "managed_prefix", lambda: tmp_path)
    assert bk.is_managed(str(tmp_path / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"))
    assert not bk.is_managed("/home/u/.opencode/bin/opencode")
    monkeypatch.setattr(bk, "managed_prefix", lambda: None)
    assert not bk.is_managed("/home/u/.opencode/bin/opencode")


def test_upgrade_of_a_managed_install_reinstalls_v2_into_our_prefix(monkeypatch, tmp_path):
    import sciqlop_opencode.installer as inst

    monkeypatch.setattr(inst, "managed_prefix", lambda: tmp_path)
    monkeypatch.setattr(inst, "is_managed", lambda _exe: True)
    monkeypatch.setattr(inst.shutil, "which", lambda _: "/x/node/npm")
    cmd = inst.upgrade_command(str(tmp_path / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"))
    assert "@opencode/cli" in cmd and str(tmp_path) in cmd


def test_upgrade_of_a_user_install_uses_opencodes_own_major_upgrade(monkeypatch):
    # v1's `upgrade --major` knows how the user installed it (curl, brew, npm, scoop…).
    import sciqlop_opencode.installer as inst

    monkeypatch.setattr(inst, "is_managed", lambda _exe: False)
    assert inst.upgrade_command("/home/u/.opencode/bin/opencode") == [
        "/home/u/.opencode/bin/opencode", "upgrade", "--major",
    ]


def test_run_install_strips_terminal_escape_codes(monkeypatch):
    # `opencode upgrade` draws a spinner; raw escapes would litter the log.
    import sciqlop_opencode.installer as inst

    class _Proc:
        returncode = 0
        stdout = ["\x1b[0m●  Using method: curl\x1b[?25l", "\x1b[?25h"]

        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(inst.subprocess, "Popen", _Proc)
    lines = []
    inst.run_install(["opencode", "upgrade", "--major"], on_line=lines.append)
    assert lines == ["●  Using method: curl", ""]


def _activate(monkeypatch, exe, major):
    import sciqlop_opencode as plugin

    offers = []
    monkeypatch.setattr(plugin, "resolve_opencode_executable", lambda: exe)
    monkeypatch.setattr(plugin, "opencode_major_version", lambda _exe: major)
    monkeypatch.setattr(plugin.QTimer, "singleShot", lambda _ms, fn: fn())
    monkeypatch.setattr(plugin, "run_install_flow", lambda _w: offers.append("install"))
    monkeypatch.setattr(plugin, "run_upgrade_flow", lambda _w, e: offers.append(("upgrade", e)))
    monkeypatch.setattr(plugin, "_upgrade_offered", set())
    backend = plugin.OpencodeBackend.__new__(plugin.OpencodeBackend)
    backend._main_window = None
    return backend, offers


def test_activation_offers_install_when_missing(monkeypatch):
    backend, offers = _activate(monkeypatch, None, None)
    backend.on_activated()
    assert offers == ["install"]


def test_activation_offers_upgrade_once_per_session_for_v1(monkeypatch):
    backend, offers = _activate(monkeypatch, "/x/opencode", 1)
    backend.on_activated()
    backend.on_activated()
    assert offers == [("upgrade", "/x/opencode")]


def test_activation_is_silent_for_v2_or_unknown_versions(monkeypatch):
    for major in (2, None):
        backend, offers = _activate(monkeypatch, "/x/opencode", major)
        backend.on_activated()
        assert offers == []
