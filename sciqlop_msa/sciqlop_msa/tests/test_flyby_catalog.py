from datetime import datetime, timezone

from sciqlop_msa import flyby_catalog
from sciqlop_msa.flybys import flybys


def test_one_event_per_flyby_with_stable_ids_and_its_window():
    events = flyby_catalog.flyby_events()

    assert len(events) == len(flybys())
    mercury_6 = events[-1]
    assert mercury_6["uuid"] == "msa-flyby-mercury-6"
    assert mercury_6["start"] == datetime(2025, 1, 8, 1, 38, 44, tzinfo=timezone.utc)
    assert mercury_6["stop"] == datetime(2025, 1, 8, 17, 26, 51, tzinfo=timezone.utc)
    assert mercury_6["meta"] == {"flyby": "Mercury 6", "closest_approach": "2025-01-08"}
