"""Small HTTP helpers shared by the routers."""

from __future__ import annotations

import re
from urllib.parse import quote

_ASCII_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def content_disposition(filename: str, *, inline: bool = False) -> str:
    """Build a Content-Disposition value that survives an Arabic filename.

    HTTP header values are latin-1, so "مزاد أعيان حائل.pdf" cannot be written
    directly. RFC 5987 gives an ASCII fallback plus a UTF-8 encoded form, which
    every current browser prefers.
    """
    disposition = "inline" if inline else "attachment"
    stem, _, suffix = filename.rpartition(".")
    ascii_stem = _ASCII_SAFE.sub("-", stem or filename).strip("-") or "download"
    fallback = f"{ascii_stem}.{suffix}" if suffix else ascii_stem
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"
