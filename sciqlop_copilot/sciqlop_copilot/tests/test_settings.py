"""Regression tests for CopilotSettings validation.

Out-of-range persisted YAML values must not crash the settings panel —
they get clamped to the nearest bound.
"""
import pytest

from sciqlop_copilot.settings import CopilotSettings


def test_top_p_above_one_is_clamped_not_raises():
    s = CopilotSettings(top_p=3.0)
    assert s.top_p == 1.0


def test_top_p_below_zero_is_clamped():
    s = CopilotSettings(top_p=-0.5)
    assert s.top_p == 0.0


def test_temperature_above_two_is_clamped():
    s = CopilotSettings(temperature=5.0)
    assert s.temperature == 2.0


def test_valid_values_pass_through():
    s = CopilotSettings(top_p=0.7, temperature=0.2)
    assert s.top_p == 0.7
    assert s.temperature == pytest.approx(0.2)
