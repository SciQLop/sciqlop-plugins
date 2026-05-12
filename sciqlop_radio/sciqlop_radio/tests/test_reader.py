"""Reader integration test against a committed sample file.

Requires real sunpy + radiospectra in the test env. Skip if unavailable.
"""
from pathlib import Path

import pytest

pytest.importorskip("radiospectra")

DATA_DIR = Path(__file__).parent / "data"
SAMPLE_CALLISTO = DATA_DIR / "ecallisto_sample.fit.gz"
SAMPLE_CALLISTO_UNCOMPRESSED = DATA_DIR / "ecallisto_sample.fit"
SAMPLE_WIND = DATA_DIR / "wind_waves_sample.cdf"


def _pick_sample():
    for p in (SAMPLE_CALLISTO, SAMPLE_CALLISTO_UNCOMPRESSED, SAMPLE_WIND):
        if p.exists():
            return p
    pytest.skip("no sample data file present")


def test_open_sample_returns_spectrogram_like_object():
    from sciqlop_radio.reader import open_spectrogram
    spec = open_spectrogram(_pick_sample())
    assert spec is not None
    assert hasattr(spec, "data")
    assert hasattr(spec, "times")
    assert hasattr(spec, "frequencies")
    assert spec.data.size > 0


def test_open_nonexistent_file_raises():
    from sciqlop_radio.reader import open_spectrogram
    with pytest.raises(FileNotFoundError):
        open_spectrogram(Path("/nonexistent/file.cdf"))
