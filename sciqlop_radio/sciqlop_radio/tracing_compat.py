"""Guarded import of SciQLop's runtime tracer.

sciqlop_radio's tests run headless (SciQLop isn't a real installed package --
see tests/conftest.py's `_OPTIONAL` stubbing), so a bare `from SciQLop.core
import tracing` would break test collection. Falls back to no-op stand-ins
with the same names, mirroring the `Knob` fallback already used in lofar.py.
"""
from __future__ import annotations

try:
    from SciQLop.core.tracing import zone, traced, counter  # noqa: F401
except ImportError:  # pragma: no cover — headless CI / SciQLop not installed
    import functools
    from contextlib import contextmanager
    from typing import Iterable

    @contextmanager
    def zone(name: str, cat: str = "", **kwargs):
        yield

    def traced(name: str | None = None, cat: str = "", capture: Iterable[str] = ()):
        def decorator(fn):
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                return fn(*args, **kwargs)
            return wrapper
        return decorator

    def counter(name: str, value: float, cat: str = "") -> None:
        pass


__all__ = ["zone", "traced", "counter"]
