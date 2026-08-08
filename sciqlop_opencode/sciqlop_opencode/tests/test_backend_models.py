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
    monkeypatch.setattr("sciqlop_opencode.sessions.configured_models", lambda: [])
    out = bk.fetch_models()
    assert out == [("Default (opencode)", None)]


def test_fetch_models_appends_config_and_session_specs(monkeypatch):
    monkeypatch.setattr(bk, "_DEFAULT_MODEL_CHOICES", [("Default (opencode)", None)])
    monkeypatch.setattr(
        "sciqlop_opencode.sessions.configured_models",
        lambda: [
            {
                "id": "qwen3.8-max",
                "providerID": "opencode-go",
                "name": "Qwen",
                "cost_input": 0,
                "cost_output": 0,
            },
        ],
    )
    monkeypatch.setattr(
        "sciqlop_opencode.sessions.known_session_models",
        lambda: [
            {
                "id": "free-a",
                "providerID": "opencode",
                "cost_input": 0,
                "cost_output": 0,
            },
            {
                "id": "gpt-4o",
                "providerID": "openai",
                "cost_input": 0.5,
                "cost_output": 2,
            },
        ],
    )
    out = bk.fetch_models()
    assert out == [
        ("Default (opencode)", None),
        ("Qwen (opencode-go) — FREE", "opencode-go/qwen3.8-max"),
        ("Free A (opencode) — FREE", "opencode/free-a"),
        ("Gpt 4o (openai) — $2.00/1M out", "openai/gpt-4o"),
    ]


def test_fetch_models_dedupes_config_vs_session_overlap(monkeypatch):
    monkeypatch.setattr(bk, "_DEFAULT_MODEL_CHOICES", [("Default (opencode)", None)])
    monkeypatch.setattr(
        "sciqlop_opencode.sessions.configured_models",
        lambda: [
            {
                "id": "longcat-2.0-free",
                "providerID": "opencode",
                "name": "Longcat",
                "cost_input": 0,
                "cost_output": 0,
            }
        ],
    )
    monkeypatch.setattr(
        "sciqlop_opencode.sessions.known_session_models",
        lambda: [
            {
                "id": "longcat-2.0-free",
                "providerID": "opencode",
                "cost_input": 0,
                "cost_output": 0,
            }
        ],
    )
    out = bk.fetch_models()
    assert out == [
        ("Default (opencode)", None),
        ("Longcat (opencode) — FREE", "opencode/longcat-2.0-free"),
    ]


def test_reorder_required_first_moves_required_props_up():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "plot_index": {"type": "integer"},
        },
        "required": ["plot_index"],
    }
    out = bk._reorder_required_first(schema)
    assert list(out["properties"].keys()) == ["plot_index", "name"]
    assert out["required"] == ["plot_index"]


def test_reorder_required_first_preserves_intra_group_order():
    schema = {
        "type": "object",
        "properties": {"a": {}, "b": {}, "c": {}, "d": {}},
        "required": ["c", "a"],
    }
    out = bk._reorder_required_first(schema)
    # required keys in their original relative order, then non-required in
    # their original relative order
    assert list(out["properties"].keys()) == ["a", "c", "b", "d"]


def test_reorder_required_first_noop_when_already_correct():
    schema = {
        "type": "object",
        "properties": {"plot_index": {"type": "integer"}, "name": {"type": "string"}},
        "required": ["plot_index"],
    }
    out = bk._reorder_required_first(schema)
    assert list(out["properties"].keys()) == ["plot_index", "name"]


def test_reorder_required_first_passes_through_when_no_required():
    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": [],
    }
    out = bk._reorder_required_first(schema)
    assert out is schema  # untouched


def test_fetch_models_falls_back_on_db_error(monkeypatch):
    monkeypatch.setattr(bk, "_DEFAULT_MODEL_CHOICES", [("Default (opencode)", None)])

    def boom():
        raise RuntimeError("db locked")

    monkeypatch.setattr("sciqlop_opencode.sessions.known_session_models", boom)
    monkeypatch.setattr("sciqlop_opencode.sessions.configured_models", boom)
    assert bk.fetch_models() == [("Default (opencode)", None)]


def test_normalize_schema_types_collapses_union():
    schema = {
        "type": "object",
        "properties": {
            "start": {"type": ["string", "number"]},
            "stop": {"type": ["string", "number"]},
            "name": {"type": "string"},
        },
        "required": ["start"],
    }
    out = bk._normalize_schema_types(schema)
    assert out["properties"]["start"]["type"] == "string"
    assert out["properties"]["stop"]["type"] == "string"
    assert out["properties"]["name"]["type"] == "string"


def test_normalize_schema_types_handles_nullable():
    schema = {"type": ["number", "null"]}
    assert bk._normalize_schema_types(schema)["type"] == "number"


def test_normalize_schema_types_recurses_into_nested():
    schema = {
        "type": "object",
        "properties": {
            "nested": {
                "type": "object",
                "properties": {"v": {"type": ["string", "null"]}},
            },
        },
    }
    out = bk._normalize_schema_types(schema)
    assert out["properties"]["nested"]["properties"]["v"]["type"] == "string"
