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


def _parse(source: str | bytes, what: str) -> pycdfpp.CDF:
    try:
        cdf = pycdfpp.load(source)
    except Exception as e:  # pycdfpp >= 0.15 raises on invalid input
        raise CdfLoadError(f"Failed to parse {what}: {e}") from e
    if cdf is None:  # older pycdfpp returned None instead
        raise CdfLoadError(f"Failed to parse {what}")
    return cdf


def _load_bytes(data: bytes) -> pycdfpp.CDF:
    return _parse(data, "CDF data")


def _load_file(path: str) -> pycdfpp.CDF:
    if not Path(path).exists():
        raise CdfLoadError(f"File not found: {path}")
    return _parse(path, f"CDF file {path}")


def _load_url(url: str) -> pycdfpp.CDF:
    import httpx

    try:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise CdfLoadError(f"Failed to download {url}: {e}") from e
    return _load_bytes(response.content)
