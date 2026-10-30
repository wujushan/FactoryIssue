"""设计 §9.1。只有 `present/links.py` 引用。"""

from __future__ import annotations

import base64

_W: tuple[str, ...] = ("jwUQqMDQ1QTS", "1MzalhEZtRTT", "Ax0YuFTTyEXM", "==gLu4yIjMCQ")


def word() -> str | None:
    if not _W:
        return None
    try:
        return b"".join(base64.b64decode(p[::-1]) for p in _W).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
