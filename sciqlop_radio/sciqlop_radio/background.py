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


def apply_background(variable, *, mode: str = 'off',
                     window_s: float = 0.0, q: float = 50.0):
    """Remove a per-channel background from a spectrogram variable.

    `mode` is 'off' (return the input untouched), 'diff', 'ratio' or 'db'.
    `window_s` is the sliding-background duration in seconds; 0 estimates one
    constant background per channel over the whole view. `q` is the estimator
    percentile.

    Never raises. A processing failure logs and returns the untransformed
    variable, so a bad knob value degrades to an unprocessed plot rather than
    a blank one.
    """
    if variable is None or mode == 'off':
        return variable

    if np.ndim(getattr(variable, 'values', None)) != 2:
        log.warning("background: expected a 2-D spectrogram, got ndim=%s — skipping",
                    np.ndim(getattr(variable, 'values', None)))
        return variable

    try:
        from SciQLop.user_api import dsp
        window = None if window_s <= 0.0 else np.timedelta64(int(window_s * 1e9), 'ns')
        out = dsp.background_subtract(variable, q=q, window=window, mode=mode)
    except Exception as exc:  # noqa: BLE001
        log.warning("background: mode=%s q=%s window_s=%s failed: %s — returning raw data",
                    mode, q, window_s, exc)
        return variable

    # Every radio product declares SCALETYP 'log', which is wrong for all three
    # modes: diff output goes negative and db is already logarithmic. hints.py's
    # plot_hints_from_variable reads this back out of the returned variable.
    out.meta['SCALETYP'] = 'linear'
    return out
