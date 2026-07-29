"""A minimal module that declares the background knobs on a nested callback,
exactly as `continuous.py` and `lofar.py` do. Exists so the introspection
regression test has a target that isolates the annotations from the rest of
the fetch machinery."""
from __future__ import annotations

from sciqlop_radio.background import BgMode, BgQ, BgWindow


def build_probe_callback():
    def _probe(start: float, stop: float, bg_mode: BgMode = 'off',
               bg_window_s: BgWindow = 0.0, bg_q: BgQ = 50.0):
        return (start, stop, bg_mode, bg_window_s, bg_q)

    return _probe
