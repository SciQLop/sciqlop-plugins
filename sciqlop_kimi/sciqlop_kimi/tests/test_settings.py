"""Settings-driven configuration: API key from SciQLop settings takes
precedence over the Kimi CLI config file."""
import pytest


class _FakeSettings:
    api_key = "sk-test"
    base_url = "https://example.test/v1"
    model = "kimi-test"
    max_context_size = 131072


def test_api_key_falls_back_to_keyring(monkeypatch):
    from sciqlop_kimi import settings as st

    monkeypatch.setattr(st, "_load_api_key", lambda: "sk-from-keyring")
    s = st.KimiSettings()
    assert s.api_key == "sk-from-keyring"


def test_save_writes_key_to_keyring_and_restores_it(monkeypatch):
    """save() must route the key to the keyring (not YAML) and keep it on the
    instance afterwards. Works in both stub and real-ConfigEntry envs since it
    goes through attribute assignment rather than constructor data (which the
    real framework discards when a persisted YAML exists)."""
    from sciqlop_kimi import settings as st

    monkeypatch.setattr(st, "_load_api_key", lambda: "")
    saved = {}
    monkeypatch.setattr(st, "_save_api_key", lambda k: saved.update(key=k))
    s = st.KimiSettings()
    s.api_key = "sk-explicit"
    s.save()
    assert saved.get("key") == "sk-explicit"
    assert s.api_key == "sk-explicit"


def test_settings_config_none_without_key(monkeypatch):
    pytest.importorskip("kimi_agent_sdk")
    from sciqlop_kimi import settings as st
    from sciqlop_kimi import backend as bk

    monkeypatch.setattr(st, "_load_api_key", lambda: "")
    assert bk._settings_config() is None


def test_settings_config_builds_full_config_with_key(monkeypatch):
    pytest.importorskip("kimi_agent_sdk")
    from sciqlop_kimi import settings as st
    from sciqlop_kimi import backend as bk

    monkeypatch.setattr(st, "KimiSettings", lambda: _FakeSettings())
    cfg = bk._settings_config()
    assert cfg is not None
    assert cfg.default_model == "kimi-test"
    provider = cfg.providers["kimi"]
    assert provider.base_url == "https://example.test/v1"
    assert provider.api_key.get_secret_value() == "sk-test"
    model = cfg.models["kimi-test"]
    assert model.provider == "kimi"
    assert model.max_context_size == 131072


def test_fetch_models_offers_settings_model_when_key_set(monkeypatch):
    pytest.importorskip("kimi_agent_sdk")
    from sciqlop_kimi import settings as st
    from sciqlop_kimi import backend as bk

    monkeypatch.setattr(st, "KimiSettings", lambda: _FakeSettings())
    assert bk.fetch_models() == [("kimi-test (Kimi settings)", None)]


def test_check_config_accepts_settings_key(monkeypatch, tmp_path):
    pytest.importorskip("kimi_agent_sdk")
    from sciqlop_kimi import settings as st
    from sciqlop_kimi.backend import KimiBackend

    monkeypatch.setattr(st, "KimiSettings", lambda: _FakeSettings())
    backend = KimiBackend.__new__(KimiBackend)
    backend._check_config()  # must not raise


def test_check_config_raises_without_any_credentials(monkeypatch, tmp_path):
    pytest.importorskip("kimi_agent_sdk")
    from sciqlop_kimi import settings as st
    from sciqlop_kimi import backend as bk
    from sciqlop_kimi.backend import KimiBackend

    monkeypatch.setattr(st, "_load_api_key", lambda: "")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)

    class _EmptyCfg:
        providers = {}

    monkeypatch.setattr("kimi_cli.config.load_config", lambda: _EmptyCfg())
    backend = KimiBackend.__new__(KimiBackend)
    with pytest.raises(RuntimeError, match="Settings"):
        backend._check_config()
