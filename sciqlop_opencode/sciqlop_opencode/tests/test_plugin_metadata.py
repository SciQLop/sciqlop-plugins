"""Plugin manifest sanity checks."""
import json
from pathlib import Path


_PLUGIN_DIR = Path(__file__).resolve().parent.parent


def test_plugin_json_parses_and_has_required_fields():
    data = json.loads((_PLUGIN_DIR / "plugin.json").read_text())
    assert data["name"]
    assert data["version"]
    assert data["disabled"] is False


def test_declared_deps_match_the_acp_layer():
    # The ACP layer ships in SciQLop 0.13, and the tool server it starts is
    # HTTP MCP — so both floors are load-bearing, not decorative.
    data = json.loads((_PLUGIN_DIR / "plugin.json").read_text())
    deps = " ".join(data["python_dependencies"])
    assert "SciQLop>=0.13.0" in deps
    assert "agent-client-protocol" in deps
    assert "mcp>=" in deps and "uvicorn" in deps
    assert "opencode-agent-sdk" not in deps


def test_pyproject_declares_entry_point_and_matches_plugin_json():
    pyproject = (_PLUGIN_DIR.parent / "pyproject.toml").read_text()
    data = json.loads((_PLUGIN_DIR / "plugin.json").read_text())
    assert 'sciqlop_opencode = "sciqlop_opencode"' in pyproject
    assert "opencode-agent-sdk" not in pyproject
    # the two dependency lists are hand-maintained copies; keep them in step
    for dep in data["python_dependencies"]:
        assert dep.split(">=")[0].split(",")[0] in pyproject
    assert f'version = "{data["version"]}"' in pyproject
