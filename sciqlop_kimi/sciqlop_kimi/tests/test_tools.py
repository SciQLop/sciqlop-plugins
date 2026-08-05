"""Dynamic tool classes: pydantic params from JSON schema, MCP-style result
conversion, write-gating, and loadability through kimi-cli's tool loader."""
import asyncio

import pytest


def _sdk():
    return pytest.importorskip("kimi_agent_sdk")


def _tool(name="sciqlop_dummy", gated=False, handler=None, schema=None):
    return {
        "name": name,
        "description": "A dummy tool.",
        "input_schema": schema or {"type": "object", "properties": {}, "required": []},
        "handler": handler or (lambda args: {"content": [{"type": "text", "text": "ok"}]}),
        "gated": gated,
    }


def _backend(monkeypatch, tmp_path, tools, allow_writes=False, confirm_cb=None):
    """A KimiBackend with __init__ bypassed (no config check, no SDK session)."""
    from sciqlop_kimi.backend import KimiBackend

    backend = KimiBackend.__new__(KimiBackend)
    backend._tools = tools
    backend._gated_names = {t["name"] for t in tools if t.get("gated")}
    backend._tempdir = tmp_path
    backend._confirm_cb = confirm_cb
    backend._allow_writes = allow_writes
    return backend


def test_params_model_required_and_optional(monkeypatch, tmp_path):
    _sdk()
    from sciqlop_kimi import backend as bk

    model = bk._params_model("t", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "where"},
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "flag": {"type": "boolean"},
        },
        "required": ["path"],
    })
    instance = model(path="a//b")
    assert instance.path == "a//b"
    assert instance.count is None and instance.ratio is None and instance.flag is None
    with pytest.raises(Exception):
        model()  # missing required 'path'


def test_registered_tool_class_loads_via_kimi_cli_loader(monkeypatch, tmp_path):
    """kimi-cli's toolset resolves tools by `module:ClassName` import — the
    dynamically created class must be resolvable and instantiable with no
    constructor args."""
    sdk = _sdk()
    from sciqlop_kimi import backend as bk

    backend = _backend(monkeypatch, tmp_path, [_tool()])
    bk._register_tool_class(backend, backend._tools[0])
    tool_cls = getattr(bk, "SciqlopTool_sciqlop_dummy")
    instance = tool_cls()
    assert instance.name == "sciqlop_dummy"
    assert instance.description == "A dummy tool."
    assert issubclass(tool_cls, sdk.CallableTool2)


def test_to_output_text_only_collapses_to_str(monkeypatch):
    _sdk()
    from sciqlop_kimi import backend as bk

    out = bk._to_output({"content": [{"type": "text", "text": "hello"}]})
    assert out == "hello"


def test_to_output_image_becomes_data_uri_part(monkeypatch):
    sdk = _sdk()
    from kosong.message import ImageURLPart
    from sciqlop_kimi import backend as bk

    out = bk._to_output({"content": [
        {"type": "text", "text": "shot"},
        {"type": "image", "data": "QUJD", "mimeType": "image/png"},
    ]})
    assert isinstance(out, list)
    assert any(isinstance(p, sdk.TextPart) and p.text == "shot" for p in out)
    images = [p for p in out if isinstance(p, ImageURLPart)]
    assert images and images[0].image_url.url == "data:image/png;base64,QUJD"


def test_gated_tool_denied_when_writes_disabled(monkeypatch, tmp_path):
    sdk = _sdk()
    from sciqlop_kimi import backend as bk

    called = []
    tool = _tool(gated=True, handler=lambda args: called.append(args) or "done")
    backend = _backend(monkeypatch, tmp_path, [tool], allow_writes=False)
    params = bk._params_model(tool["name"], tool["input_schema"])()
    result = asyncio.run(backend._run_tool(tool, params))
    assert isinstance(result, sdk.ToolError)
    assert "disabled" in result.message
    assert called == []


def test_gated_tool_runs_after_user_confirmation(monkeypatch, tmp_path):
    sdk = _sdk()
    from sciqlop_kimi import backend as bk

    seen = {}

    async def confirm(name, args):
        seen["name"] = name
        return True

    tool = _tool(gated=True)
    backend = _backend(monkeypatch, tmp_path, [tool], allow_writes=True, confirm_cb=confirm)
    params = bk._params_model(tool["name"], tool["input_schema"])()
    result = asyncio.run(backend._run_tool(tool, params))
    assert isinstance(result, sdk.ToolOk)
    assert seen["name"] == "sciqlop_dummy"


def test_gated_tool_denied_by_user(monkeypatch, tmp_path):
    sdk = _sdk()
    from sciqlop_kimi import backend as bk

    async def confirm(name, args):
        return False

    tool = _tool(gated=True)
    backend = _backend(monkeypatch, tmp_path, [tool], allow_writes=True, confirm_cb=confirm)
    params = bk._params_model(tool["name"], tool["input_schema"])()
    result = asyncio.run(backend._run_tool(tool, params))
    assert isinstance(result, sdk.ToolError)
    assert "denied" in result.message


def test_handler_exception_becomes_tool_error(monkeypatch, tmp_path):
    sdk = _sdk()
    from sciqlop_kimi import backend as bk

    def boom(args):
        raise ValueError("bad path")

    tool = _tool(handler=boom)
    backend = _backend(monkeypatch, tmp_path, [tool])
    params = bk._params_model(tool["name"], tool["input_schema"])()
    result = asyncio.run(backend._run_tool(tool, params))
    assert isinstance(result, sdk.ToolError)
    assert "ValueError" in result.message and "bad path" in result.message


def test_agent_file_lists_every_tool(monkeypatch, tmp_path):
    _sdk()
    from sciqlop_kimi import backend as bk

    tools = [_tool(name="sciqlop_a"), _tool(name="sciqlop_b")]
    backend = _backend(monkeypatch, tmp_path, tools)
    for t in tools:
        bk._register_tool_class(backend, t)
    agent_file = backend._write_agent_files()
    content = agent_file.read_text()
    assert "sciqlop_kimi.backend:SciqlopTool_sciqlop_a" in content
    assert "sciqlop_kimi.backend:SciqlopTool_sciqlop_b" in content

    # and kimi-cli actually accepts the generated spec
    from kimi_cli.agentspec import load_agent_spec
    spec = load_agent_spec(agent_file)
    assert spec.name == "sciqlop"
    assert len(spec.tools) == 2
