# SciQLop Plugins — Development Guide

This repo is a bundle of plugins for [SciQLop](https://github.com/SciQLop/SciQLop). Each plugin is an independent Python package with its own `pyproject.toml`, built as a wheel and published to GitHub releases.

## Layout

```
plugins_sciqlop/
├── cdf_workbench/          # plugin directory (matches pyproject name)
│   ├── pyproject.toml      # name: sciqlop-cdf-workbench, entry-points
│   └── cdf_workbench/      # the actual Python package
│       ├── __init__.py     # re-exports load()
│       ├── plugin.json     # descriptor
│       └── ...
├── sciqlop_opencode/
│   ├── pyproject.toml
│   └── sciqlop_opencode/
│       ├── __init__.py
│       ├── backend.py
│       ├── sessions.py
│       ├── plugin.json
│       └── tests/
└── ...
```

Each plugin has two names:
- **Directory name** (e.g. `sciqlop_opencode`) — what `extra_plugins_folders` points to
- **Package name** in `pyproject.toml` (e.g. `sciqlop-opencode`) — what pip installs

## How SciQLop Loads Plugins

SciQLop discovers plugins from three sources (in order):
1. **Bundled** — `SciQLop/plugins/` (shipped with SciQLop)
2. **User folder** — `~/.local/share/sciqlop/plugins/`
3. **Extra folders** — paths listed in `~/.config/sciqlop/sciqloppluginssettings.yaml` under `extra_plugins_folders`

For each folder, the loader (`SciQLop/components/plugins/backend/loader/loader.py`) does:
- `list_plugins_as_modules()` — finds `*.py` files (excluding `__init__.py`)
- `list_plugins_as_packages()` — finds subdirectories (excluding `_`-prefixed)
- For packages, it calls `import_from_path(name, path/__init__.py)` which uses `importlib.util.spec_from_file_location` — **no pip install needed**

The loader then calls `module.load(main_window)` on each discovered plugin.

Entry-point plugins (installed via pip) are discovered separately via `importlib.metadata.entry_points(group="sciqlop.plugins")`.

## Development Workflow (No Install Needed)

**You do NOT need to pip-install the plugin to develop it.** SciQLop loads it directly from source via `extra_plugins_folders`.

### Setup

1. Add the plugin directory to `~/.config/sciqlop/sciqloppluginssettings.yaml`:
   ```yaml
   extra_plugins_folders:
     - /path/to/plugins_sciqlop/sciqlop_opencode
   ```

2. Make sure the plugin is enabled in the same file:
   ```yaml
   plugins:
     sciqlop_opencode:
       enabled: true
   ```

3. Restart SciQLop — it will load the plugin from source.

### Making Changes

- Edit the plugin source directly
- Clear `__pycache__` if changes aren't picked up: `rm -rf sciqlop_opencode/__pycache__`
- Restart SciQLop to reload

### Running Plugin Tests

Plugin tests mock SciQLop dependencies. Run them from the SciQLop environment (which has the real `SciQLop` package installed):

```bash
# From the SciQLop repo root (NOT from the plugin repo)
cd /path/to/SciQLop
python3 -m pytest /path/to/plugins_sciqlop/sciqlop_opencode/sciqlop_opencode/tests/ -v
```

**Do NOT use `uv run`** — it creates a new venv and breaks the SciQLop import. Use the system Python that has SciQLop installed.

**Do NOT install the plugin via pip** — it's loaded from source via `extra_plugins_folders`.

### Environment Rules

- **NEVER modify the user's development environment** — no `uv run --python X`, no `pip install`, no venv creation
- **Use the system Python directly** — `python3`, `python3 -m pytest`
- **If you break an env, yell immediately** — don't silently work around it

## Plugin Contract

Every plugin must expose:

```python
# plugin_name/__init__.py
from .plugin_name import load  # re-export load()
```

```python
# plugin_name/plugin_name.py or similar
def load(main_window):
    """Called by SciQLop to initialize the plugin.
    
    Args:
        main_window: SciQLopMainWindow instance
        
    Returns:
        Plugin instance (or None). If returned, SciQLop calls 
        `await plugin.close()` on shutdown.
    """
    plugin = MyPlugin(main_window)
    return plugin
```

### plugin.json Schema

```json
{
  "name": "My Plugin",
  "version": "0.1.0",
  "description": "What it does",
  "authors": [{"name": "...", "email": "...", "organization": "..."}],
  "license": "MIT",
  "python_dependencies": ["SciQLop>=0.13.0,<0.14.0"],
  "dependencies": [],
  "disabled": false
}
```

## pyproject.toml Template

```toml
[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[project]
name = "sciqlop-my-plugin"
version = "0.1.0"
description = "My plugin for SciQLop"
requires-python = ">=3.10"
dependencies = ["SciQLop>=0.12.0,<0.14.0"]

[project.entry-points."sciqlop.plugins"]
sciqlop_my_plugin = "sciqlop_my_plugin"

[tool.setuptools.packages.find]
include = ["sciqlop_my_plugin*"]

[tool.setuptools.package-data]
sciqlop_my_plugin = ["plugin.json", "resources/*"]
```

## CI / Releases

- Trigger: push a tag `<plugin_dir>/v*` (e.g. `sciqlop_opencode/v0.1.1`)
- CI builds the wheel and attaches it to a GitHub release
- Users install from the release URL or via the SciQLop AppStore

## Key SciQLop APIs for Plugin Authors

### Main Window Integration
- `main_window.addToolBar(title)` → QToolBar
- `main_window.toolsMenu`, `main_window.viewMenu` — QMenu
- `main_window.add_side_pan(widget, location, icon)` — side panels
- `main_window.new_plot_panel(name=...)` → TimeSyncPanel

### Data Provider
- Base: `SciQLop.components.plotting.backend.data_provider.DataProvider`
- Register products: `ProductsModel.instance().add_node(path, node)`

### Settings
- Extend `ConfigEntry` (Pydantic) with `category` and `subcategory` ClassVars
- Auto-persisted to `~/.config/sciqlop/<classname>.yaml`

### User API
- `SciQLop.user_api.plot` — `plot_panel()`, `create_plot_panel()`
- `SciQLop.user_api.virtual_products` — `create_virtual_product()`
- `SciQLop.user_api.gui` — `get_main_window()`
