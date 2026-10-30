"""设计 §9.1。只有 `present/links.py` 引用。"""

from __future__ import annotations

import base64

_A: tuple[str, ...] = ("=gzNmN3ZzITM", "=ADMrpWawATO", "=YGa5VDNzITM", "=ADMhpWbwATO")
_B: tuple[str, ...] = ("=gzNopWdzITM", "=ADMnZGZwATO")


def _join(parts: tuple[str, ...]) -> bytes:
    return b"".join(base64.b64decode(p[::-1]) for p in parts)


def pair() -> tuple[bytes, bytes] | None:
    if not _A or not _B:
        return None
    a, b = _join(_A)[:32], _join(_B)[:16]
    if len(a) != 32 or len(b) != 16:
        return None
    return a, b
