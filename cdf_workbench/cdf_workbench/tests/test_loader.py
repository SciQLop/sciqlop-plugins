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


def test_load_corrupted_bytes_raises():
    """A download that is not a CDF (e.g. an HTML login page) goes through the bytes path."""
    with pytest.raises(CdfLoadError, match="Failed to parse"):
        load_cdf(b"<html>please log in</html>")


def test_load_missing_file_raises():
    with pytest.raises(CdfLoadError):
        load_cdf("/nonexistent/path.cdf")


def test_load_from_bytes(sample_cdf_bytes):
    cdf = load_cdf(sample_cdf_bytes)
    assert "Bt" in cdf


@pytest.fixture
def http_server(tmp_path, sample_cdf_bytes):
    import functools
    import http.server
    import threading
    (tmp_path / "f.cdf").write_bytes(sample_cdf_bytes)
    (tmp_path / "big.bin").write_bytes(b"\0" * (3 * 1024 * 1024))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_load_url(http_server):
    assert "Bt" in load_cdf(f"{http_server}/f.cdf")


def test_a_cancelled_download_stops(http_server):
    from cdf_workbench.loader import DownloadCancelled
    checks = []
    with pytest.raises(DownloadCancelled):
        load_cdf(f"{http_server}/big.bin", cancelled=lambda: checks.append(1) or len(checks) > 1)
    assert len(checks) == 2
