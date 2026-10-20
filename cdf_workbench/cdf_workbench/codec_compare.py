"""X1: re-encode a document with each codec pycdfpp knows, to compare sizes and speeds."""
from __future__ import annotations
import time
import warnings
from dataclasses import dataclass, replace
from typing import Optional

import pycdfpp

from .document import Document, to_cdf

CODECS = tuple(pycdfpp.CompressionType.__members__.values())
_EXPERIMENTAL = {pycdfpp.CompressionType.zstd_compression, pycdfpp.CompressionType.blosc2_compression}


@dataclass(frozen=True)
class CodecResult:
    codec: pycdfpp.CompressionType
    size: Optional[int] = None
    write_s: float = 0.0
    read_s: float = 0.0
    identical: bool = False
    error: str = ""

    @property
    def experimental(self) -> bool:
        """Files other CDF readers may not open yet (pycdfpp warns on save)."""
        return self.codec in _EXPERIMENTAL


def with_compression(doc: Document, codec: pycdfpp.CompressionType) -> Document:
    return replace(doc, variables={name: replace(var, compression=codec) for name, var in doc.items()})


def _same_values(doc: Document, reloaded: pycdfpp.CDF) -> bool:
    return all(reloaded[name].values.tobytes() == var.values.tobytes() for name, var in doc.items())


def try_codec(doc: Document, codec: pycdfpp.CompressionType) -> CodecResult:
    """Encode, then decode eagerly and check every value comes back bit-identical.
    pycdfpp can't write every codec it reads (e.g. Huffman): that is reported, not raised."""
    try:
        start = time.perf_counter()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", pycdfpp.ExperimentalCompressionWarning)
            data = bytes(pycdfpp.save(to_cdf(with_compression(doc, codec))))
        written = time.perf_counter()
        reloaded = pycdfpp.load(data, lazy_load=False)
        read = time.perf_counter()
    except Exception as e:
        return CodecResult(codec, error=str(e))
    return CodecResult(codec, size=len(data), write_s=written - start, read_s=read - written,
                       identical=_same_values(doc, reloaded))
