"""Per-channel background removal shared by the radio spectrogram callbacks.

Exposes `SciQLop.user_api.dsp.background_subtract` as three knobs that
`continuous.py` and `lofar.py` declare on their fetch callbacks. All numerics
live in SciQLop's DSP layer; only the knob surface, the seconds-to-duration
conversion and the colour-scale policy are instrument/display concerns and
therefore belong here.
"""
from __future__ import annotations

import logging
from typing import Annotated, Literal

import numpy as np

log = logging.getLogger(__name__)


# Module-level Knob binding — SciQLop resolves the stringified annotations
# below in the *callback's* module globals, not in this one, so the aliases
# must be importable as plain top-level names by every module that declares
# them. Both of SciQLop's introspection paths degrade silently on a NameError
# (knobs vanish from the UI; the provider warns about missing type hints and
# assumes float), so a lazy import here would be invisible until someone
# noticed the knobs missing. Headless tests without a SciQLop install fall
# back to a no-op stub so module import never breaks.
try:
    from SciQLop.user_api.knobs import Knob
except ImportError:  # pragma: no cover — only hit in headless CI
    class Knob:  # type: ignore[no-redef]
        def __init__(self, **kwargs):
            pass


BgMode = Annotated[
    Literal['off', 'diff', 'ratio', 'db'],
    Knob(label="Background",
         description="Per-channel background removal: off, S-bg, S/bg, "
                     "or 10*log10(S/bg)."),
]

# Seconds rather than samples: I-LOFAR runs at 1 s cadence and e-Callisto at
# 0.25 s, so one shared sample-count default would mean a different duration
# per product. It also keeps the plugin clear of `resolve_window`'s
# int-vs-timedelta dispatch — we only ever pass None or an np.timedelta64.
BgWindow = Annotated[
    float,
    Knob(min=0.0, max=86400.0, step=1.0, unit="s", label="BG window",
         description="Sliding background duration in seconds; 0 uses one "
                     "constant background over the whole view."),
]

BgQ = Annotated[
    float,
    Knob(min=0.0, max=100.0, step=1.0, unit="%", label="BG percentile",
         description="Percentile of the background estimator. 50 is the "
                     "median; 5-10 when bursts fill much of the view."),
]
