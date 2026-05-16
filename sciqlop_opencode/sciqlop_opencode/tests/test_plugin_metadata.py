"""Plugin manifest sanity checks."""
import json
from pathlib import Path


_PLUGIN_DIR = Path(__file__).resolve().parent.parent


def test_plugin_json_parses_and_has_required_fields():
    data = json.loads((_PLUGIN_DIR / "plugin.json").read_text())
    assert data["name"]
    assert data["version"]
    assert "opencode-agent-sdk" in data["python_dependencies"]
    assert data["disabled"] is False


def test_pyproject_declares_entry_point():
    pyproject = (_PLUGIN_DIR.parent / "pyproject.toml").read_text()
    assert 'sciqlop_opencode = "sciqlop_opencode"' in pyproject
    assert "opencode-agent-sdk" in pyproject
