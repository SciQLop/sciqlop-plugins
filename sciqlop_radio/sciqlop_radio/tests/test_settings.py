from pathlib import Path

import pytest


def test_defaults_are_sensible():
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings()
    assert isinstance(s.cache_dir, Path)
    assert 5 <= s.download_timeout_s <= 600
    assert 1 <= s.parallel_downloads <= 16


def test_timeout_clamps_oversized_value():
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings(download_timeout_s=10_000)
    assert s.download_timeout_s == 600


def test_timeout_clamps_negative_value():
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings(download_timeout_s=-5)
    assert s.download_timeout_s == 5


def test_parallel_clamps_oversized_value():
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings(parallel_downloads=999)
    assert s.parallel_downloads == 16


def test_parallel_clamps_zero():
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings(parallel_downloads=0)
    assert s.parallel_downloads == 1


def test_non_numeric_strings_pass_through_to_pydantic_validation():
    from sciqlop_radio.settings import RadioSettings
    with pytest.raises(Exception):
        RadioSettings(download_timeout_s="not-a-number")
