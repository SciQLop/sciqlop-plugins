"""ISTP metadata + plot-hints parity helpers for sciqlop_radio.

Mirrors what `SciQLop.plugins.speasy_provider` does for native Speasy
products, so our 40 virtual products (38 catalog + 2 continuous) carry
the same rich product-tree metadata and apply the same pre/post-fetch
plot hints as their `speasy/...` siblings.

The three public-ish exports:

- `extract_speasy_index_meta(index, *, components=None) -> dict[str, Any]`
  Mines a Speasy ParameterIndex into a flat primitives-only metadata
  dict suitable for `ProductsModelNode`. Mirrors
  `SciQLop.plugins.speasy_provider.get_node_meta + make_product`.

- `RichEasyScalar / RichEasyVector / RichEasyMultiComponent /
  RichEasySpectrogram` - `EasyProvider` subclasses that override
  `plot_hints` and `plot_hints_from_variable` using SciQLop's
  ISTP translators (same logic as the bundled Speasy plugin).

- `make_rich_vp(path, callback, vp_type, *, metadata, labels=None)
  -> EasyProvider` - internal factory used by catalog.py and
  continuous.py. Replaces the call site of user_api
  `create_virtual_product` (which does not take metadata).
"""
from __future__ import annotations

import ast
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)


def _components_from_index(index: Any) -> Optional[list[str]]:
    """Mirror of `SciQLop.plugins.speasy_provider.get_components` reduced
    to the cases the radio catalog actually hits (AMDA + CDA spectrograms).
    Returns None when nothing usable is found - caller falls back to
    `[spz_uid()]`."""
    provider = ""
    try:
        provider = index.spz_provider() or ""
    except Exception:
        pass
    if provider == "amda":
        display = getattr(index, "display_type", "")
        if isinstance(display, str) and display.lower() == "timeseries":
            try:
                return [index.spz_name()]
            except Exception:
                return None
    labl = getattr(index, "LABL_PTR_1", None)
    if isinstance(labl, list):
        return [str(v) for v in labl]
    if isinstance(labl, str):
        try:
            value = ast.literal_eval(labl)
            if isinstance(value, (list, tuple)):
                return [str(v) for v in value]
        except (ValueError, SyntaxError):
            return [s.strip() for s in labl.split(",") if s.strip()]
    lablaxis = getattr(index, "LABLAXIS", None)
    if isinstance(lablaxis, str):
        if lablaxis.startswith("["):
            return [s.strip() for s in lablaxis.strip("[]").split(",") if s.strip()]
        return [lablaxis]
    return None


def extract_speasy_index_meta(
    index: Any, *, components: Optional[list[str]] = None
) -> dict[str, Any]:
    """Mine a Speasy `ParameterIndex` into a flat metadata dict.

    Walks `index.__dict__` keeping primitive values (str/int/float/bool)
    and list-of-primitives. Drops underscored keys, dicts, callables,
    exotic objects (Qt QVariant won't round-trip them). Adds the four
    canonical Speasy keys (`uid`, `provider`, `speasy_id`, `stable_id`)
    and a `components` list.

    Raises whatever `index.spz_uid()` / `index.spz_provider()` raise -
    the caller in catalog.py is responsible for falling back to minimal
    metadata.
    """
    uid = index.spz_uid()
    provider = index.spz_provider()
    speasy_id = f"{provider}/{uid}"

    meta: dict[str, Any] = {}
    for name, value in vars(index).items():
        if name.startswith("_"):
            continue
        if isinstance(value, bool):
            meta[name] = value
        elif isinstance(value, (str, int, float)):
            meta[name] = value
        elif isinstance(value, (list, tuple)) and value and all(
            isinstance(v, (str, int, float, bool)) for v in value
        ):
            meta[name] = list(value)

    meta["uid"] = uid
    meta["provider"] = provider
    meta["speasy_id"] = speasy_id
    meta["stable_id"] = speasy_id
    meta["components"] = components or _components_from_index(index) or [uid]
    return meta


# ---------------------------------------------------------------------------
# RichEasy* subclasses - override plot_hints + plot_hints_from_variable
# exactly as SciQLop.plugins.speasy_provider.SpeasyPlugin does.
# ---------------------------------------------------------------------------

from SciQLop.components.plotting.backend.easy_provider import (  # noqa: E402
    EasyScalar as _EasyScalarRaw,
    EasyVector as _EasyVectorRaw,
    EasyMultiComponent as _EasyMultiComponentRaw,
    EasySpectrogram as _EasySpectrogramRaw,
)

# When the test conftest pre-stubs easy_provider as MagicMock the imported
# names are MagicMock instances (not classes). Inheriting from a MagicMock
# causes MagicMock.__new__ to fail with "issubclass() arg 1 must be a class".
# Fall back to `object` so the RichEasy* classes remain ordinary Python classes
# that can be instantiated via __new__ in tests.
_EasyScalar = _EasyScalarRaw if isinstance(_EasyScalarRaw, type) else object
_EasyVector = _EasyVectorRaw if isinstance(_EasyVectorRaw, type) else object
_EasyMultiComponent = _EasyMultiComponentRaw if isinstance(_EasyMultiComponentRaw, type) else object
_EasySpectrogram = _EasySpectrogramRaw if isinstance(_EasySpectrogramRaw, type) else object
from SciQLop.core.plot_hints import PlotHints  # noqa: E402
from SciQLop.core.istp_hints import istp_metadata_to_hints  # noqa: E402
from SciQLop.core.speasy_hints import variable_as_istp_meta  # noqa: E402
from SciQLop.core.enums import GraphType  # noqa: E402


def _plot_hints_from_node(node) -> PlotHints:
    try:
        return istp_metadata_to_hints(node.metadata())
    except Exception:
        log.debug("plot_hints failed for %s", node, exc_info=True)
        return PlotHints()


def _plot_hints_from_variable(self, node, variable) -> PlotHints:
    try:
        meta = variable_as_istp_meta(variable)
        if self.graph_type(node) == GraphType.ColorMap:
            meta.setdefault("DISPLAY_TYPE", "spectrogram")
        return istp_metadata_to_hints(meta)
    except Exception:
        log.debug("plot_hints_from_variable failed for %s", node, exc_info=True)
        return PlotHints()


class RichEasyScalar(_EasyScalar):
    def plot_hints(self, node) -> PlotHints:
        return _plot_hints_from_node(node)

    def plot_hints_from_variable(self, node, variable) -> PlotHints:
        return _plot_hints_from_variable(self, node, variable)


class RichEasyVector(_EasyVector):
    def plot_hints(self, node) -> PlotHints:
        return _plot_hints_from_node(node)

    def plot_hints_from_variable(self, node, variable) -> PlotHints:
        return _plot_hints_from_variable(self, node, variable)


class RichEasyMultiComponent(_EasyMultiComponent):
    def plot_hints(self, node) -> PlotHints:
        return _plot_hints_from_node(node)

    def plot_hints_from_variable(self, node, variable) -> PlotHints:
        return _plot_hints_from_variable(self, node, variable)


class RichEasySpectrogram(_EasySpectrogram):
    def plot_hints(self, node) -> PlotHints:
        return _plot_hints_from_node(node)

    def plot_hints_from_variable(self, node, variable) -> PlotHints:
        return _plot_hints_from_variable(self, node, variable)
