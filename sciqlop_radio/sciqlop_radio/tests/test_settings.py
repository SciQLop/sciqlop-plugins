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


def test_non_numeric_strings_fall_back_to_defaults():
    """Real `ConfigEntry.__init__` (SciQLop entry.py:172-177) catches any
    `ValidationError` from pydantic and silently re-constructs with defaults,
    so a corrupt YAML on disk never crashes the settings panel. That swallow
    also applies to programmatic construction: an invalid kwarg yields the
    default, not an exception. Test pins that observable behaviour so we
    notice if upstream stops swallowing."""
    from sciqlop_radio.settings import RadioSettings
    s = RadioSettings(download_timeout_s="not-a-number")
    assert s.download_timeout_s == 60   # default, NOT raised
