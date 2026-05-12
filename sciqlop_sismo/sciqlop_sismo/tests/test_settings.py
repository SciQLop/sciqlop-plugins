"""Tests for sciqlop_sismo.settings."""
from pathlib import Path

import pytest

from sciqlop_sismo.settings import SismoSettings


def test_defaults_are_sane():
    s = SismoSettings()
    assert s.default_routing == "iris-federator"
    assert s.bandpass_min_hz == pytest.approx(0.01)
    assert s.bandpass_max_hz == pytest.approx(10.0)
    assert s.cache_retention_days == 7
    assert s.stationxml_cache_hours == 12
    assert s.search_timeout_s == 60
    assert s.fetch_timeout_s == 120
    assert isinstance(s.cache_dir, Path)


def test_bandpass_clamped_when_out_of_range():
    s = SismoSettings(bandpass_min_hz=-1, bandpass_max_hz=99999)
    assert s.bandpass_min_hz == 0.0
    assert s.bandpass_max_hz == 1000.0


def test_bandpass_min_below_max_after_clamp():
    s = SismoSettings(bandpass_min_hz=20, bandpass_max_hz=5)
    assert s.bandpass_min_hz == 5.0
    assert s.bandpass_max_hz == 20.0


def test_cache_retention_clamped():
    s = SismoSettings(cache_retention_days=-3)
    assert s.cache_retention_days == 0
    s2 = SismoSettings(cache_retention_days=99999)
    assert s2.cache_retention_days == 365


def test_routing_is_lowercased():
    s = SismoSettings(default_routing="IRIS-Federator")
    assert s.default_routing == "iris-federator"


def test_cache_dir_defaults_to_user_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    s = SismoSettings()
    assert s.cache_dir == tmp_path / "sciqlop" / "sismo"
