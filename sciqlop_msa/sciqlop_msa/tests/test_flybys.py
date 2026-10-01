import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace

import pytest

from sciqlop_msa import flybys


def _epoch(text):
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


def test_flybys_are_loaded_in_time_order_with_unique_labels():
    all_flybys = flybys.flybys()

    assert [f.name for f in all_flybys] == ["Venus 2", "Mercury 1", "Mercury 2", "Mercury 3", "Mercury 4", "Mercury 6"]
    assert all(f.start < f.stop for f in all_flybys)
    assert len({f.label for f in all_flybys}) == len(all_flybys)
    assert flybys.flyby_by_label("Mercury 6 (2025-01-08)").name == "Mercury 6"


def test_next_flyby_from_inside_a_flyby_is_the_following_one():
    inside_mercury_1 = _epoch("2021-10-01T12:00:00")

    assert flybys.next_flyby(inside_mercury_1).name == "Mercury 2"
    assert flybys.previous_flyby(inside_mercury_1).name == "Venus 2"


def test_next_and_previous_flyby_stop_at_the_ends():
    before_all, after_all = _epoch("2020-01-01T00:00:00"), _epoch("2026-01-01T00:00:00")

    assert flybys.next_flyby(before_all).name == "Venus 2"
    assert flybys.previous_flyby(before_all) is None
    assert flybys.next_flyby(after_all) is None
    assert flybys.previous_flyby(after_all).name == "Mercury 6"


@pytest.fixture
def time_range(monkeypatch):
    plot = ModuleType("SciQLop.user_api.plot")
    plot.TimeRange = lambda start, stop: (start, stop)
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.plot", plot)


def test_jump_shows_the_whole_flyby_and_widens_a_shorter_zoom_limit(time_range):
    venus_2 = flybys.flyby_by_label("Venus 2 (2021-08-10)")
    panel = SimpleNamespace(zoom_limit_seconds=86400.0, time_range=None)

    flybys.jump(panel, venus_2)

    assert panel.time_range == (venus_2.start, venus_2.stop)
    assert panel.zoom_limit_seconds == venus_2.stop - venus_2.start


def test_jump_leaves_an_unlimited_or_wide_enough_zoom_limit_alone(time_range):
    mercury_6 = flybys.flyby_by_label("Mercury 6 (2025-01-08)")
    for limit in (0.0, 7 * 86400.0):
        panel = SimpleNamespace(zoom_limit_seconds=limit, time_range=None)

        flybys.jump(panel, mercury_6)

        assert panel.zoom_limit_seconds == limit
