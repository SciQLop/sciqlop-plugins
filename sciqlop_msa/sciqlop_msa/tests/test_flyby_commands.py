import sys
from types import ModuleType, SimpleNamespace

import pytest

from sciqlop_msa import flyby_commands
from sciqlop_msa.flybys import flyby_by_label

MERCURY_1 = flyby_by_label("Mercury 1 (2021-10-01)")
MERCURY_2 = flyby_by_label("Mercury 2 (2022-06-23)")
VENUS_2 = flyby_by_label("Venus 2 (2021-08-10)")


class FakeRange(tuple):
    def center(self):
        return (self[0] + self[1]) / 2


@pytest.fixture
def panels(monkeypatch):
    existing = {"panel-1": SimpleNamespace(zoom_limit_seconds=0.0,
                                           time_range=FakeRange((MERCURY_1.start, MERCURY_1.stop)))}
    created = []

    def create_plot_panel():
        created.append(SimpleNamespace(zoom_limit_seconds=0.0, time_range=None))
        return created[-1]

    plot = ModuleType("SciQLop.user_api.plot")
    plot.TimeRange = lambda start, stop: FakeRange((start, stop))
    plot.plot_panel = existing.get
    plot.create_plot_panel = create_plot_panel
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.plot", plot)
    return SimpleNamespace(existing=existing, created=created)


def test_jump_to_flyby_moves_the_named_panel(panels):
    flyby_commands.jump_to_flyby(flyby=VENUS_2.label, panel="panel-1")

    assert panels.existing["panel-1"].time_range == (VENUS_2.start, VENUS_2.stop)


def test_jump_to_flyby_in_a_new_panel(panels):
    flyby_commands.jump_to_flyby(flyby=VENUS_2.label, panel="__new__")

    assert panels.created[0].time_range == (VENUS_2.start, VENUS_2.stop)


def test_next_and_previous_step_from_the_panel_position(panels):
    flyby_commands.jump_to_next_flyby(panel="panel-1")
    assert panels.existing["panel-1"].time_range == (MERCURY_2.start, MERCURY_2.stop)

    flyby_commands.jump_to_previous_flyby(panel="panel-1")
    assert panels.existing["panel-1"].time_range == (MERCURY_1.start, MERCURY_1.stop)


def test_unknown_panel_or_flyby_and_stepping_past_the_last_do_nothing(panels):
    before = panels.existing["panel-1"].time_range

    flyby_commands.jump_to_flyby(flyby="Pluto 1", panel="panel-1")
    flyby_commands.jump_to_flyby(flyby=VENUS_2.label, panel="no-such-panel")
    flyby_commands.jump_to_previous_flyby(panel="panel-1")  # Mercury 1 -> Venus 2 ...
    flyby_commands.jump_to_previous_flyby(panel="panel-1")  # ... and nothing before Venus 2

    assert before != panels.existing["panel-1"].time_range == (VENUS_2.start, VENUS_2.stop)


def test_panel_menu_offers_next_previous_then_every_flyby(panels):
    panel = panels.existing["panel-1"]  # showing Mercury 1

    entries = flyby_commands.panel_menu_entries(panel)

    labels = [label for label, _ in entries]
    assert labels[:2] == [f"Next: {MERCURY_2.label}", f"Previous: {VENUS_2.label}"]
    assert labels[2:] == [f.label for f in flyby_commands.flybys()]
    dict(entries)[VENUS_2.label]()
    assert panel.time_range == (VENUS_2.start, VENUS_2.stop)


def test_panel_menu_drops_previous_before_the_first_flyby(panels):
    panel = panels.existing["panel-1"]
    panel.time_range = FakeRange((VENUS_2.start - 10 * 86400, VENUS_2.start - 9 * 86400))

    labels = [label for label, _ in flyby_commands.panel_menu_entries(panel)]

    assert labels[0] == f"Next: {VENUS_2.label}"
    assert not any(label.startswith("Previous") for label in labels)
