import smoke_plugins as sp

PLUGINS = ["cdf_workbench", "sciqlop_msa", "sciqlop_radio"]


def test_a_push_smokes_only_the_plugins_it_touched():
    changed = ["sciqlop_msa/sciqlop_msa/flybys.py", "sciqlop_msa/pyproject.toml", "docs/notes.md"]
    assert sp.pick("push", changed, PLUGINS) == ["sciqlop_msa"]


def test_a_push_touching_no_plugin_smokes_nothing():
    assert sp.pick("push", ["README.md", "docs/x.md"], PLUGINS) == []


def test_changing_the_smoke_itself_smokes_everything():
    assert sp.pick("push", [".github/workflows/compat.yml"], PLUGINS) == PLUGINS
    assert sp.pick("push", [".github/scripts/smoke_plugins.py"], PLUGINS) == PLUGINS


def test_scheduled_manual_and_unknown_history_runs_smoke_everything():
    assert sp.pick("schedule", [], PLUGINS) == PLUGINS
    assert sp.pick("workflow_dispatch", [], PLUGINS) == PLUGINS
    assert sp.pick("push", None, PLUGINS) == PLUGINS  # new branch: nothing to diff against


def test_a_directory_named_like_a_prefix_of_a_plugin_is_not_mistaken_for_it():
    assert sp.pick("push", ["sciqlop_msa_notes/x.md"], PLUGINS) == []


def test_plugins_are_the_folders_with_a_plugin_json(tmp_path):
    for name in ("sciqlop_a", "sciqlop_b"):
        (tmp_path / name / name).mkdir(parents=True)
        (tmp_path / name / name / "plugin.json").write_text("{}")
    (tmp_path / "docs").mkdir()

    assert sp.all_plugins(tmp_path) == ["sciqlop_a", "sciqlop_b"]
