"""sciqlop_radio's own tests run headless (SciQLop is stubbed -- see
conftest.py's _OPTIONAL list), so this exercises the real fallback path
tracing_compat falls back to when `SciQLop.core.tracing` isn't importable."""
from sciqlop_radio import tracing_compat


def test_zone_is_a_usable_context_manager():
    with tracing_compat.zone("test.zone", cat="test", extra=1):
        pass  # must not raise


def test_zone_propagates_exceptions_from_the_body():
    import pytest
    with pytest.raises(ValueError):
        with tracing_compat.zone("test.zone"):
            raise ValueError("boom")


def test_traced_decorator_preserves_behavior_and_identity():
    @tracing_compat.traced(cat="test", capture=("x",))
    def add_one(x):
        return x + 1

    assert add_one(41) == 42
    assert add_one.__name__ == "add_one"


def test_counter_does_not_raise():
    tracing_compat.counter("test.counter", 3.0, cat="test")
