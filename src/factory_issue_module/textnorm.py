"""文字归一化（设计 §1.4、§12 第 5 步）：治理任务、查询期、沙箱脚本共用同一份写法。

只用 `re` 与内建函数：沙箱禁止 import `html`、`unicodedata`（设计 §1.4，实测），这份源码以后
要原样拼进沙箱脚本。剥图去标签在 S6 随治理任务补上。
"""

from __future__ import annotations

import re

_SPACES = re.compile(r"\s+")


def to_halfwidth(text: str) -> str:
    """全角转半角：U+FF01–U+FF5E 平移到 ASCII，全角空格 U+3000 转普通空格。"""
    out = []
    for ch in text:
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def normalize(text: str) -> str:
    """全角转半角、转小写、连续空白压成一个空格、去首尾空白。"""
    return _SPACES.sub(" ", to_halfwidth(text).lower()).strip()


def compact(text: str) -> str:
    """归一化后去掉全部空白（中文说法按业务规则忽略空格匹配）。"""
    return _SPACES.sub("", normalize(text))


def has_cjk(text: str) -> bool:
    """是否含汉字（中文说法与纯英文缩写的匹配规则不同，见 topic_terms.md「怎么读」）。"""
    return any("\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf" for ch in text)
