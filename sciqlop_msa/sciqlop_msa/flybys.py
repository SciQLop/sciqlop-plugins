"""BepiColombo flybys with MSA data, read from flybys.yaml, and how to jump a panel to one."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import cache
from pathlib import Path


@dataclass(frozen=True)
class Flyby:
    name: str
    closest_approach: date
    start: float
    stop: float

    @property
    def label(self) -> str:
        return f"{self.name} ({self.closest_approach.isoformat()})"


def _epoch(value: datetime) -> float:
    return value.replace(tzinfo=timezone.utc).timestamp()


@cache
def flybys() -> tuple:
    import yaml

    entries = yaml.safe_load((Path(__file__).parent / "flybys.yaml").read_text())
    return tuple(sorted((Flyby(name=e["name"], closest_approach=e["closest_approach"],
                               start=_epoch(e["start"]), stop=_epoch(e["stop"])) for e in entries),
                        key=lambda f: f.start))


def flyby_by_label(label: str) -> "Flyby | None":
    return next((f for f in flybys() if f.label == label), None)


def next_flyby(t: float) -> "Flyby | None":
    return next((f for f in flybys() if f.start > t), None)


def previous_flyby(t: float) -> "Flyby | None":
    return next((f for f in reversed(flybys()) if f.stop < t), None)


def jump(panel, flyby: Flyby) -> None:
    """Show the whole flyby in a user_api PlotPanel."""
    from SciQLop.user_api.plot import TimeRange

    span = flyby.stop - flyby.start
    if 0 < panel.zoom_limit_seconds < span:
        panel.zoom_limit_seconds = span
    panel.time_range = TimeRange(flyby.start, flyby.stop)
