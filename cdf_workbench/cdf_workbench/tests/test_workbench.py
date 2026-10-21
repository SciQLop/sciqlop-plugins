"""Tests for the CdfWorkbenchPanel tab lifecycle."""
import gc
import pytest
import numpy as np
import pycdfpp

pytest.importorskip("SciQLopPlots")

from PySide6.QtWidgets import QApplication


def force_gc():
    gc.collect()
    QApplication.processEvents()
    gc.collect()


@pytest.fixture
def cdf_file(tmp_path):
    path = tmp_path / "sample.cdf"
    cdf = pycdfpp.CDF()
    epochs = np.arange(
        np.datetime64("2020-01-01"),
        np.datetime64("2020-01-01T00:00:10"),
        np.timedelta64(1, "s"),
    ).astype("datetime64[ns]")
    cdf.add_variable("Epoch", values=epochs, is_nrv=False)
    cdf.add_variable(
        "Bt",
        values=np.random.rand(10).astype(np.float32),
        is_nrv=False,
    )
    cdf["Bt"].add_attribute("VAR_TYPE", "data")
    cdf["Bt"].add_attribute("DEPEND_0", "Epoch")
    cdf["Bt"].add_attribute("UNITS", "nT")
    cdf["Bt"].add_attribute("FILLVAL", [np.float32(-1e31)])
    cdf["Bt"].add_attribute("VALIDMIN", [np.float32(0.0)])
    cdf["Bt"].add_attribute("VALIDMAX", [np.float32(100.0)])
    cdf["Epoch"].add_attribute("VAR_TYPE", "support_data")
    pycdfpp.save(cdf, str(path))
    return str(path)


@pytest.fixture
def panel(qtbot):
    from cdf_workbench.workbench import CdfWorkbenchPanel
    w = CdfWorkbenchPanel()
    qtbot.addWidget(w)
    w.show()
    return w


def test_open_and_close_tab(panel, cdf_file, qtbot):
    """Opening a file then closing its tab must not crash."""
    panel.open_file(cdf_file)
    qtbot.wait(50)
    assert panel._tabs.count() == 2  # file tab + "+"
    panel._close_tab(0)
    qtbot.wait(50)
    force_gc()
    assert panel._tabs.count() == 1


def test_open_tab_has_no_close_button(panel, cdf_file, qtbot):
    """The "+" tab cannot be closed, so it must not show a dead close cross."""
    from PySide6.QtWidgets import QTabBar
    panel.open_file(cdf_file)
    qtbot.wait(50)
    bar = panel._tabs.tabBar()
    plus = bar.count() - 1
    assert bar.tabText(plus) == "+"
    assert bar.tabButton(plus, QTabBar.LeftSide) is None
    assert bar.tabButton(plus, QTabBar.RightSide) is None
    assert bar.tabButton(0, QTabBar.RightSide) or bar.tabButton(0, QTabBar.LeftSide)


def test_open_close_multiple_tabs(panel, cdf_file, qtbot, tmp_path):
    """Opening and closing multiple tabs in sequence must not crash."""
    for i in range(3):
        copy = str(tmp_path / f"copy{i}.cdf")
        pycdfpp.save(pycdfpp.load(cdf_file), copy)
        panel.open_file(copy)
        qtbot.wait(20)
    assert panel._tabs.count() == 4
    while panel._tabs.count() > 1:
        panel._close_tab(0)
        qtbot.wait(20)
        force_gc()
    assert panel._tabs.count() == 1


def test_modified_tab_title_gets_a_dot(panel, cdf_file, qtbot):
    from dataclasses import replace
    panel.open_file(cdf_file)
    session = panel._tabs.widget(0).session
    assert panel._tabs.tabText(0) == "sample.cdf"

    session.apply(lambda d: replace(d, attributes={}))
    assert panel._tabs.tabText(0) == "sample.cdf •"

    session.mark_saved()
    assert panel._tabs.tabText(0) == "sample.cdf"


def test_url_loads_in_the_background_and_opens_on_a_variable(panel, cdf_file, qtbot, monkeypatch):
    import cdf_workbench.workbench as workbench
    from cdf_workbench.loader import load_cdf
    monkeypatch.setattr(workbench, "load_cdf", lambda source, **kw: load_cdf(cdf_file))

    panel.open_file("https://example.org/data/sample.cdf", variable="Bt")

    qtbot.waitUntil(lambda: panel._tabs.count() == 2)
    view = panel._tabs.widget(0)
    assert panel._tabs.tabText(0) == "sample.cdf"
    assert view._previewed is not None and view._previewed.name == "Bt"


def test_a_failed_load_is_shown_on_the_open_page(panel, qtbot):
    panel.open_file("/nonexistent/file.cdf")

    assert panel._tabs.count() == 1
    assert "File not found" in panel._open_page.status()


def _modify(view):
    from dataclasses import replace
    from cdf_workbench.document import Attribute, GlobalAttribute
    edited = GlobalAttribute((Attribute("yes", pycdfpp.DataType.CDF_CHAR),))
    view.session.apply(lambda d: replace(d, attributes={**d.attributes, "Edited": edited}))


def _was_saved(path):
    return "Edited" in pycdfpp.load(path).attributes


def test_save_writes_the_file_and_clears_the_dot(panel, cdf_file, qtbot):
    panel.open_file(cdf_file)
    _modify(panel._tabs.widget(0))

    panel.save_tab(0)

    assert panel._tabs.tabText(0) == "sample.cdf"
    assert _was_saved(cdf_file)


def test_save_as_renames_the_tab(panel, cdf_file, qtbot, tmp_path, monkeypatch):
    target = str(tmp_path / "copy.cdf")
    monkeypatch.setattr(panel, "_ask_save_path", lambda name: target)
    panel.open_file(cdf_file)

    panel.save_tab_as(0)

    assert panel._tabs.tabText(0) == "copy.cdf"
    assert pycdfpp.load(target) is not None


@pytest.mark.parametrize("answer, closed, saved", [("cancel", False, False), ("discard", True, False),
                                                    ("save", True, True)])
def test_closing_a_modified_tab_asks_first(panel, cdf_file, qtbot, monkeypatch, answer, closed, saved):
    monkeypatch.setattr(panel, "_ask_unsaved", lambda name: answer)
    panel.open_file(cdf_file)
    _modify(panel._tabs.widget(0))

    panel._close_tab(0)

    assert (panel._tabs.count() == 1) == closed
    assert _was_saved(cdf_file) == saved


def test_saving_a_url_file_asks_where(panel, cdf_file, qtbot, tmp_path, monkeypatch):
    import cdf_workbench.workbench as workbench
    from cdf_workbench.loader import load_cdf
    monkeypatch.setattr(workbench, "load_cdf", lambda source, **kw: load_cdf(cdf_file))
    asked = []
    monkeypatch.setattr(panel, "_ask_save_path", lambda name: asked.append(name) or "")
    panel.open_file("https://example.org/sample.cdf")
    qtbot.waitUntil(lambda: panel._tabs.count() == 2)

    panel.save_tab(0)

    assert asked == ["sample.cdf"]


def test_undo_shortcut_reverts_the_current_tab(panel, cdf_file, qtbot):
    panel.open_file(cdf_file)
    view = panel._tabs.widget(0)
    _modify(view)

    panel.undo_current()

    assert panel._tabs.tabText(0) == "sample.cdf"
    panel.redo_current()
    assert panel._tabs.tabText(0) == "sample.cdf •"


def test_console_add_variable_acts_on_the_current_tab(panel, cdf_file, qtbot):
    """In SciQLop's console: plugins.cdf_workbench.add_variable(...)."""
    with pytest.raises(ValueError, match="Open a CDF"):
        panel.add_variable("x", [1.0])
    panel.open_file(cdf_file)

    panel.add_variable("Bmag", np.ones(10), {"UNITS": "nT", "DEPEND_0": "Epoch"})

    doc = panel._tabs.widget(0).session.document
    assert doc["Bmag"].attributes["DEPEND_0"].value == "Epoch"
    assert panel._tabs.tabText(0) == "sample.cdf •"


def test_export_structure_as_yaml(panel, cdf_file, qtbot, tmp_path, monkeypatch):
    import yaml
    target = tmp_path / "s.yaml"
    monkeypatch.setattr(panel, "_ask_export_path", lambda name, filters: str(target))
    panel.open_file(cdf_file)

    panel.export_structure(0)

    assert set(yaml.safe_load(target.read_text())["variables"]) == {"Epoch", "Bt"}


def test_save_subset_keeps_what_the_variables_need(panel, cdf_file, qtbot, tmp_path, monkeypatch):
    target = str(tmp_path / "sub.cdf")
    monkeypatch.setattr(panel, "_ask_variables", lambda names: ["Bt"])
    monkeypatch.setattr(panel, "_ask_save_path", lambda name: target)
    panel.open_file(cdf_file)

    panel.save_subset(0)

    assert list(pycdfpp.load(target).keys()) == ["Epoch", "Bt"]
    assert panel._tabs.tabText(0) == "sample.cdf"


def test_opening_an_open_file_switches_to_its_tab(panel, cdf_file, qtbot, tmp_path):
    import os
    link = tmp_path / "link.cdf"
    os.symlink(cdf_file, link)
    panel.open_file(cdf_file)
    panel._tabs.setCurrentIndex(1)

    panel.open_file(str(link))

    assert panel._tabs.count() == 2 and panel._tabs.currentIndex() == 0


def test_save_as_onto_a_file_open_in_another_tab_is_refused(panel, cdf_file, qtbot, tmp_path, monkeypatch):
    other = str(tmp_path / "other.cdf")
    pycdfpp.save(pycdfpp.load(cdf_file), other)
    panel.open_file(cdf_file)
    panel.open_file(other)
    monkeypatch.setattr(panel, "_ask_save_path", lambda name: other)

    assert not panel.save_tab_as(0)

    assert "already open" in panel._tabs.widget(0)._preview_message.text()
    assert panel._tabs.widget(0).session.source == cdf_file


def test_a_url_is_downloaded_once_and_status_lists_every_download(panel, cdf_file, qtbot, monkeypatch):
    import threading
    import cdf_workbench.workbench as workbench
    from cdf_workbench.loader import load_cdf
    release = {u: threading.Event() for u in ("https://h/a.cdf", "https://h/b.cdf")}
    calls = []

    def slow_load(source, **kw):
        calls.append(source)
        release[source].wait(10)
        return load_cdf(cdf_file)
    monkeypatch.setattr(workbench, "load_cdf", slow_load)

    panel.open_file("https://h/a.cdf")
    panel.open_file("https://h/a.cdf")
    panel.open_file("https://h/b.cdf")
    qtbot.waitUntil(lambda: len(calls) == 2)
    assert "a.cdf" in panel._open_page.status() and "b.cdf" in panel._open_page.status()

    release["https://h/a.cdf"].set()
    qtbot.waitUntil(lambda: panel._tabs.count() == 2)
    assert "b.cdf" in panel._open_page.status() and "a.cdf" not in panel._open_page.status()
    release["https://h/b.cdf"].set()
    qtbot.waitUntil(lambda: panel._tabs.count() == 3)
    assert sorted(calls) == ["https://h/a.cdf", "https://h/b.cdf"]
    assert panel._open_page.status() == ""


def test_compare_with_another_open_tab(panel, cdf_file, qtbot, tmp_path):
    from cdf_workbench.compare_view import CompareView
    other = str(tmp_path / "other.cdf")
    cdf = pycdfpp.load(cdf_file)
    cdf["Bt"].attributes["UNITS"].set_value("pT")
    pycdfpp.save(cdf, other)
    panel.open_file(cdf_file)
    panel.open_file(other)

    panel.compare_tabs(0, 1)

    view = panel._tabs.currentWidget()
    assert isinstance(view, CompareView)
    assert panel._tabs.tabText(panel._tabs.currentIndex()) == "sample.cdf ↔ other.cdf"
    assert "pT" in view.html()


def test_closing_a_tab_closes_its_comparisons(panel, cdf_file, qtbot, tmp_path):
    from cdf_workbench.compare_view import CompareView
    other = str(tmp_path / "other.cdf")
    pycdfpp.save(pycdfpp.load(cdf_file), other)
    panel.open_file(cdf_file)
    panel.open_file(other)
    panel.compare_tabs(0, 1)
    assert any(isinstance(panel._tabs.widget(i), CompareView) for i in range(panel._tabs.count()))

    panel._close_tab(0)

    assert not any(isinstance(panel._tabs.widget(i), CompareView) for i in range(panel._tabs.count()))
    assert [panel._tabs.tabText(i) for i in range(panel._tabs.count())] == ["other.cdf", "+"]


def test_a_second_request_while_downloading_keeps_its_variable(panel, cdf_file, qtbot, monkeypatch):
    import threading
    import cdf_workbench.workbench as workbench
    from cdf_workbench.loader import load_cdf
    release = threading.Event()
    monkeypatch.setattr(workbench, "load_cdf", lambda source, **kw: release.wait(10) and load_cdf(cdf_file))

    panel.open_file("https://h/a.cdf")
    panel.open_file("https://h/a.cdf", variable="Bt")
    release.set()

    qtbot.waitUntil(lambda: panel._tabs.count() == 2)
    assert panel._tabs.widget(0)._previewed.name == "Bt"


def test_a_failed_load_keeps_the_other_downloads_in_the_status(panel, qtbot, monkeypatch):
    import threading
    import cdf_workbench.workbench as workbench
    from cdf_workbench.loader import CdfLoadError
    release = threading.Event()

    def load(source, **kw):
        if source.endswith("bad.cdf"):
            raise CdfLoadError("404 for bad.cdf")
        release.wait(10)
        raise CdfLoadError("late")
    monkeypatch.setattr(workbench, "load_cdf", load)

    panel.open_file("https://h/slow.cdf")
    panel.open_file("https://h/bad.cdf")

    qtbot.waitUntil(lambda: "404" in panel._open_page.status())
    assert "slow.cdf" in panel._open_page.status()
    release.set()


@pytest.mark.parametrize("answer, allowed, saved", [("cancel", False, False), ("discard", True, False),
                                                    ("save", True, True)])
def test_quitting_with_unsaved_tabs_asks(panel, cdf_file, qtbot, monkeypatch, answer, allowed, saved):
    asked = []
    monkeypatch.setattr(panel, "_ask_unsaved_on_quit", lambda names: asked.append(names) or answer)
    panel.open_file(cdf_file)
    _modify(panel._tabs.widget(0))

    assert panel.confirm_quit() == allowed

    assert asked == [["sample.cdf"]]
    assert _was_saved(cdf_file) == saved


def test_quitting_without_unsaved_tabs_does_not_ask(panel, cdf_file, qtbot, monkeypatch):
    monkeypatch.setattr(panel, "_ask_unsaved_on_quit", lambda names: pytest.fail("asked"))
    panel.open_file(cdf_file)
    assert panel.confirm_quit()


def test_the_quit_guard_blocks_the_main_window_close(panel, cdf_file, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMainWindow
    from cdf_workbench.workbench import install_quit_guard
    window = QMainWindow()
    qtbot.addWidget(window)
    window.show()
    install_quit_guard(window, panel)
    monkeypatch.setattr(panel, "_ask_unsaved_on_quit", lambda names: "cancel")
    panel.open_file(cdf_file)
    _modify(panel._tabs.widget(0))

    window.close()
    assert window.isVisible()

    window._closing = True  # SciQLop's own second close, or --batch: no prompt
    window.close()
    assert not window.isVisible()


def test_cancel_downloads(panel, cdf_file, qtbot, monkeypatch):
    import threading
    import cdf_workbench.workbench as workbench
    from cdf_workbench.loader import DownloadCancelled, load_cdf
    started = threading.Event()

    def load(source, cancelled=None):
        started.set()
        while not cancelled():
            threading.Event().wait(0.01)
        raise DownloadCancelled(source)
    monkeypatch.setattr(workbench, "load_cdf", load)
    panel.open_file("https://h/a.cdf")
    started.wait(5)
    assert not panel._open_page._cancel.isHidden()

    panel.cancel_downloads()

    assert panel._open_page.status() == "Download cancelled."
    assert panel._open_page._cancel.isHidden()
    qtbot.wait(200)
    assert panel._tabs.count() == 1 and panel._open_page.status() == "Download cancelled."


def _enabled(panel):
    return {name: action.isEnabled() for name, action in panel._actions.items()}


def test_toolbar_follows_the_current_tab(panel, cdf_file, qtbot):
    assert set(panel._actions) == {"save", "save_as", "undo", "redo", "compare", "export", "compression", "new_variable"}
    assert not any(_enabled(panel).values())

    panel.open_file(cdf_file)
    state = _enabled(panel)
    assert state["save_as"] and state["compare"] and state["new_variable"]
    assert not state["save"] and not state["undo"] and not state["redo"]

    _modify(panel._tabs.widget(0))
    assert _enabled(panel)["save"] and _enabled(panel)["undo"]
    panel.undo_current()
    assert _enabled(panel)["redo"] and not _enabled(panel)["save"]

    panel._tabs.setCurrentWidget(panel._open_page)
    assert not any(_enabled(panel).values())


def test_toolbar_menus_list_compare_targets_and_exports(panel, cdf_file, qtbot, tmp_path):
    other = str(tmp_path / "other.cdf")
    pycdfpp.save(pycdfpp.load(cdf_file), other)
    panel.open_file(cdf_file)
    panel.open_file(other)
    panel._tabs.setCurrentIndex(0)

    compare = [a.text() for a in panel._compare_menu().actions() if not a.isSeparator()]
    export = [a.text() for a in panel._export_menu().actions() if not a.isSeparator()]

    assert compare == ["other.cdf", "File…"]
    assert export == ["Structure as YAML…", "Subset of variables…", "Data of the selected variable…"]
