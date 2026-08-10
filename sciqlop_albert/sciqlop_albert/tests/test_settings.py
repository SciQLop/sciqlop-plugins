"""Regression tests for AlbertSettings validation.

The settings panel instantiates AlbertSettings() with whatever lives in
the persisted YAML. Historical or hand-edited YAML values outside the
declared bounds must not crash the settings UI — they get clamped.
"""
import pytest

from sciqlop_albert.settings import AlbertSettings


def test_top_p_above_one_is_clamped_not_raises():
    s = AlbertSettings(top_p=3.0)
    assert s.top_p == 1.0


def test_top_p_below_zero_is_clamped():
    s = AlbertSettings(top_p=-0.5)
    assert s.top_p == 0.0


def test_temperature_above_two_is_clamped():
    s = AlbertSettings(temperature=5.0)
    assert s.temperature == 2.0


def test_valid_values_pass_through():
    s = AlbertSettings(top_p=0.7, temperature=0.2)
    assert s.top_p == 0.7
    assert s.temperature == pytest.approx(0.2)
