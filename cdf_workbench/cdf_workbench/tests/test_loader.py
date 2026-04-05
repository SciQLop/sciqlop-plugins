import pytest
from cdf_workbench.loader import load_cdf, CdfLoadError


def test_load_local_file(tmp_path, sample_cdf_bytes):
    path = tmp_path / "test.cdf"
    path.write_bytes(sample_cdf_bytes)
    cdf = load_cdf(str(path))
    assert cdf is not None
    assert "Bt" in cdf


def test_load_corrupted_file_raises(tmp_path):
    path = tmp_path / "bad.cdf"
    path.write_bytes(b"not a cdf file")
    with pytest.raises(CdfLoadError, match="Failed to parse"):
        load_cdf(str(path))


def test_load_missing_file_raises():
    with pytest.raises(CdfLoadError):
        load_cdf("/nonexistent/path.cdf")


def test_load_from_bytes(sample_cdf_bytes):
    cdf = load_cdf(sample_cdf_bytes)
    assert "Bt" in cdf
