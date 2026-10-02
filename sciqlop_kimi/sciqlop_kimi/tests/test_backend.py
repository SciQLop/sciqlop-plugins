"""KimiBackend is a thin AcpAgentBackend shell: right command, right labels,
and model discovery from the Kimi Code config file."""
import pytest


def test_backend_is_acp_shell_with_kimi_command(monkeypatch):
    acp_core = pytest.importorskip("SciQLop.components.agents.acp")
    from sciqlop_kimi import backend as bk
    from sciqlop_kimi.backend import KimiBackend

    monkeypatch.setattr(bk.shutil, "which", lambda name: "/usr/bin/kimi")  # hermetic

    assert issubclass(KimiBackend, acp_core.AcpAgentBackend)
    assert KimiBackend.display_name == "Kimi"
    assert KimiBackend.supports_sessions is True
    assert KimiBackend.cli_label == "Kimi Code"
    backend = KimiBackend.__new__(KimiBackend)
    assert backend.acp_command() == ["kimi", "acp"]


def test_backend_constructs_without_cli_and_says_so_when_started(monkeypatch, tmp_path):
    """AcpAgentBackend.__init__ calls check_prerequisites(): raising there escaped the
    agent dock's construction and failed the plugin load on any machine without the CLI."""
    from SciQLop.components.agents.backend import BackendContext
    from sciqlop_kimi import backend as bk

    monkeypatch.setattr(bk.shutil, "which", lambda name: None)
    ctx = BackendContext(main_window=None, tools=[], tempdir=tmp_path, confirm_cb=lambda *a: True)
    backend = bk.KimiBackend(ctx)  # must not raise
    with pytest.raises(RuntimeError, match="install Kimi Code"):
        backend.acp_command()


def test_fetch_models_reads_kimi_code_config(monkeypatch, tmp_path):
    from sciqlop_kimi import backend as bk

    config_dir = tmp_path / ".kimi-code"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        'default_model = "kimi-code/k3"\n'
        '[providers.managed]\n'
        'type = "kimi"\n'
        'base_url = "https://example.invalid/v1"\n'
        'api_key = "x"\n'
        '[models."kimi-code/k3"]\n'
        'provider = "managed"\n'
        'model = "k3"\n'
        'display_name = "K3"\n'
        '[models."kimi-code/k3-256k"]\n'
        'provider = "managed"\n'
        'model = "k3-256k"\n'
        'display_name = "K3-256k"\n'
    )
    monkeypatch.setattr(bk.Path, "home", classmethod(lambda cls: tmp_path))
    choices = bk.fetch_models()
    assert choices[0] == ("Default (Kimi Code)", None)
    # the default model is covered by the "Default" entry, others are listed
    assert ("K3-256k", "kimi-code/k3-256k") in choices
    assert all(label != "K3" for label, _ in choices)


def test_fetch_models_without_config_returns_default_only(monkeypatch, tmp_path):
    from sciqlop_kimi import backend as bk

    monkeypatch.setattr(bk.Path, "home", classmethod(lambda cls: tmp_path))
    assert bk.fetch_models() == [("Default (Kimi Code)", None)]
