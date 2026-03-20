from pathlib import Path
import pycdfpp


class CdfLoadError(Exception):
    pass


def load_cdf(source: str | bytes) -> pycdfpp.CDF:
    """Load a CDF from a local path, URL, or raw bytes.

    Raises CdfLoadError on any failure.
    """
    if isinstance(source, bytes):
        return _load_bytes(source)

    if source.startswith(("http://", "https://")):
        return _load_url(source)

    return _load_file(source)


def _load_bytes(data: bytes) -> pycdfpp.CDF:
    cdf = pycdfpp.load(data)
    if cdf is None:
        raise CdfLoadError("Failed to parse CDF data")
    return cdf


def _load_file(path: str) -> pycdfpp.CDF:
    if not Path(path).exists():
        raise CdfLoadError(f"File not found: {path}")
    try:
        cdf = pycdfpp.load(path)
    except Exception as e:
        raise CdfLoadError(f"Failed to load {path}: {e}") from e
    if cdf is None:
        raise CdfLoadError(f"Failed to parse CDF file: {path}")
    return cdf


def _load_url(url: str) -> pycdfpp.CDF:
    import httpx

    try:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise CdfLoadError(f"Failed to download {url}: {e}") from e
    return _load_bytes(response.content)
