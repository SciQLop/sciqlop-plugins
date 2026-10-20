from pathlib import Path
from typing import Callable, Optional
import pycdfpp

DOWNLOAD_CHUNK = 1024 * 1024


class CdfLoadError(Exception):
    pass


class DownloadCancelled(CdfLoadError):
    pass


def load_cdf(source: str | bytes, cancelled: Optional[Callable[[], bool]] = None) -> pycdfpp.CDF:
    """Load a CDF from a local path, URL, or raw bytes.

    Raises CdfLoadError on any failure. A URL download checks `cancelled` between chunks.
    """
    if isinstance(source, bytes):
        return _load_bytes(source)

    if source.startswith(("http://", "https://")):
        return _load_url(source, cancelled or (lambda: False))

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


def _load_url(url: str, cancelled: Callable[[], bool]) -> pycdfpp.CDF:
    import httpx

    data = bytearray()
    try:
        with httpx.stream("GET", url, timeout=30.0, follow_redirects=True) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(DOWNLOAD_CHUNK):
                if cancelled():
                    raise DownloadCancelled(f"Download of {url} cancelled")
                data += chunk
    except httpx.HTTPError as e:
        raise CdfLoadError(f"Failed to download {url}: {e}") from e
    return _load_bytes(bytes(data))
