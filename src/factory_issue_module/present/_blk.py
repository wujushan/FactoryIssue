"""设计 §9.1。只有 `present/links.py` 引用。"""

from __future__ import annotations

_R = 14


def _x2(a: int) -> int:
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a


def _table() -> bytes:
    out = [0] * 256
    p = q = 1
    while True:
        p ^= _x2(p)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1 | q >> 7) & 0xFF) ^ ((q << 2 | q >> 6) & 0xFF) ^ ((q << 3 | q >> 5) & 0xFF) \
            ^ ((q << 4 | q >> 4) & 0xFF)
        out[p] = x ^ 0x63
        if p == 1:
            break
    out[0] = 0x63
    return bytes(out)


_S = _table()


def _words(k: bytes) -> list[list[int]]:
    w = [list(k[i : i + 4]) for i in range(0, 32, 4)]
    rc = 1
    for i in range(8, 4 * (_R + 1)):
        t = list(w[i - 1])
        if i % 8 == 0:
            t = [_S[b] for b in t[1:] + t[:1]]
            t[0] ^= rc
            rc = _x2(rc)
        elif i % 8 == 4:
            t = [_S[b] for b in t]
        w.append([a ^ b for a, b in zip(w[i - 8], t, strict=True)])
    return [sum(w[4 * r : 4 * r + 4], []) for r in range(_R + 1)]


def _mix(s: list[int]) -> list[int]:
    out = []
    for c in range(4):
        a = s[4 * c : 4 * c + 4]
        out += [_x2(a[0]) ^ _x2(a[1]) ^ a[1] ^ a[2] ^ a[3],
                a[0] ^ _x2(a[1]) ^ _x2(a[2]) ^ a[2] ^ a[3],
                a[0] ^ a[1] ^ _x2(a[2]) ^ _x2(a[3]) ^ a[3],
                _x2(a[0]) ^ a[0] ^ a[1] ^ a[2] ^ _x2(a[3])]
    return out


def _one(block: bytes, ks: list[list[int]]) -> bytes:
    s = [b ^ k for b, k in zip(block, ks[0], strict=True)]
    for r in range(1, _R + 1):
        s = [_S[b] for b in s]
        s = [s[(i + 4 * (i % 4)) % 16] for i in range(16)]
        if r != _R:
            s = _mix(s)
        s = [b ^ k for b, k in zip(s, ks[r], strict=True)]
    return bytes(s)


def block(data: bytes, a: bytes) -> bytes:
    """一个 16 字节分组（`a` 为 32 字节）。"""
    if len(a) != 32 or len(data) != 16:
        raise ValueError("长度不对")
    return _one(data, _words(a))


def seal(data: bytes, a: bytes, b: bytes) -> bytes:
    """分组链接、末尾按 PKCS7 补齐（`a` 为 32 字节、`b` 为 16 字节）。"""
    if len(a) != 32 or len(b) != 16:
        raise ValueError("长度不对")
    ks = _words(a)
    pad = 16 - len(data) % 16
    data = data + bytes([pad]) * pad
    prev, out = b, b""
    for i in range(0, len(data), 16):
        prev = _one(bytes(x ^ y for x, y in zip(data[i : i + 16], prev, strict=True)), ks)
        out += prev
    return out
