"""Tests for fetch_models + _split_provider_model wiring."""
from sciqlop_opencode import backend as bk


def test_split_provider_model_handles_none_and_empty():
    assert bk._split_provider_model(None) == ("", "")
    assert bk._split_provider_model("") == ("", "")


def test_split_provider_model_parses_provider_slash_model():
    assert bk._split_provider_model("opencode/some-model") == ("opencode", "some-model")
    assert bk._split_provider_model("openai/gpt-4o") == ("openai", "gpt-4o")


def test_split_provider_model_handles_model_without_provider_prefix():
    # Defensive: if the dropdown value somehow lacks a slash, treat the whole
    # thing as the provider and leave model empty rather than crash.
    assert bk._split_provider_model("solo") == ("solo", "")


def test_fetch_models_includes_default_first(monkeypatch):
    monkeypatch.setattr(bk, "_DEFAULT_MODEL_CHOICES", [("Default (opencode)", None)])
    monkeypatch.setattr("sciqlop_opencode.sessions.known_session_models", lambda: [])
    out = bk.fetch_models()
    assert out == [("Default (opencode)", None)]


def test_fetch_models_appends_known_specs(monkeypatch):
    monkeypatch.setattr(bk, "_DEFAULT_MODEL_CHOICES", [("Default (opencode)", None)])
    monkeypatch.setattr(
        "sciqlop_opencode.sessions.known_session_models",
        lambda: [
            {"id": "free-a", "providerID": "opencode"},
            {"id": "gpt-4o", "providerID": "openai"},
        ],
    )
    out = bk.fetch_models()
    assert out == [
        ("Default (opencode)", None),
        ("Free A (opencode)", "opencode/free-a"),
        ("Gpt 4o (openai)", "openai/gpt-4o"),
    ]


def test_fetch_models_falls_back_on_db_error(monkeypatch):
    monkeypatch.setattr(bk, "_DEFAULT_MODEL_CHOICES", [("Default (opencode)", None)])
    def boom():
        raise RuntimeError("db locked")
    monkeypatch.setattr("sciqlop_opencode.sessions.known_session_models", boom)
    assert bk.fetch_models() == [("Default (opencode)", None)]
