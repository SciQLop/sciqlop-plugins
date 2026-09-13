"""OpencodeBackend is a thin AcpAgentBackend shell: right command, right labels,
and a model dropdown read from the agent's own ACP config options."""

import pytest


def test_backend_is_acp_shell_with_opencode_command(monkeypatch):
    acp_core = pytest.importorskip("SciQLop.components.agents.acp")
    from sciqlop_opencode import backend as bk

    # hermetic: the dev machine may have a real opencode on PATH
    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: None)
    assert issubclass(bk.OpencodeBackend, acp_core.AcpAgentBackend)
    assert bk.OpencodeBackend.display_name == "Opencode"
    assert bk.OpencodeBackend.supports_sessions is True
    backend = bk.OpencodeBackend.__new__(bk.OpencodeBackend)
    assert backend.acp_command() == ["opencode", "acp"]


def test_check_prerequisites_names_the_install_and_login_steps(monkeypatch):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: None)
    backend = bk.OpencodeBackend.__new__(bk.OpencodeBackend)
    with pytest.raises(RuntimeError, match="opencode auth login"):
        backend.check_prerequisites()


def test_acp_command_is_not_shared_mutable_state(monkeypatch):
    # A caller appending flags to the returned list must not rewrite the
    # command every later session is spawned with.
    from sciqlop_opencode.backend import OpencodeBackend
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: None)
    backend = OpencodeBackend.__new__(OpencodeBackend)
    backend.acp_command().append("--boom")
    assert backend.acp_command() == ["opencode", "acp"]


def test_fetch_models_prepends_default_and_keeps_agent_values(monkeypatch):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: "/usr/bin/opencode")
    monkeypatch.setattr(
        bk,
        "acp_config_options",
        lambda _cmd: {
            "model": [
                ("OpenCode Go/GLM-5.2", "opencode-go/glm-5.2"),
                ("OpenCode Zen/Big Pickle", "opencode/big-pickle"),
            ],
            "effort": [("Low", "low")],
        },
    )
    choices = bk.fetch_models()
    assert choices[0] == ("Default (opencode)", None)
    # values must survive verbatim — set_config_option rejects anything else
    assert ("OpenCode Go/GLM-5.2", "opencode-go/glm-5.2") in choices
    assert all(value != "low" for _, value in choices)


def test_fetch_models_falls_back_to_default_when_the_cli_is_missing(monkeypatch):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: None)
    monkeypatch.setattr(
        bk,
        "acp_config_options",
        lambda _cmd: pytest.fail("must not spawn an agent when the CLI is absent"),
    )
    assert bk.fetch_models() == [("Default (opencode)", None)]


def test_fetch_models_survives_a_failed_handshake(monkeypatch):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: "/usr/bin/opencode")
    monkeypatch.setattr(bk, "acp_config_options", lambda _cmd: {})
    assert bk.fetch_models() == [("Default (opencode)", None)]


def test_module_exposes_no_sdk_era_helpers():
    # The opencode-agent-sdk workarounds (snapshot diffing, schema reordering,
    # a local system prompt) are gone; ACP and the shared layer cover them.
    from sciqlop_opencode import backend as bk

    for name in (
        "_OpencodeStream",
        "_wrap_tool",
        "_reorder_required_first",
        "_normalize_schema_types",
        "SYSTEM_PROMPT",
        "_split_provider_model",
    ):
        assert not hasattr(bk, name), f"{name} should have been removed"
