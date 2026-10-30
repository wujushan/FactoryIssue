"""文字归一化（设计 §1.4、§12 第 5 步、§13）：治理任务、查询期、沙箱脚本共用同一份写法。

只用 `re` 与内建函数：沙箱禁止 import `html`、`unicodedata`（设计 §1.4，实测），这份源码原样拼进沙箱脚本。
- `rich_display`：单张详情展示前的剥图（S4，§13；`dirty_data.md`「富文本」）：剔除内嵌 base64 图片，段落与换行
  标记改成换行，外链图片留成链接，其余标签去掉、实体换回字符；剥净后单个字段超过 2 万字时截断并标记。
- 按文字找单用的剥净（标签、外链图片也全部去掉）随 S6 的治理任务补上。
"""

from __future__ import annotations

import re

_SPACES = re.compile(r"\s+")
#: 内嵌 base64 图片（整个 img 标签，或游离的 data: 串）
_TN_IMG_DATA = re.compile(r"<img\b[^>]*?src\s*=\s*[\"']?\s*data:[^>]*>", re.IGNORECASE)
_TN_DATA_URI = re.compile(r"data:image/[^\s\"'<>]*", re.IGNORECASE)
_TN_IMG_URL = re.compile(r"<img\b[^>]*?src\s*=\s*[\"']?(https?://[^\"'\s>]+)[^>]*>", re.IGNORECASE)
_TN_BREAK = re.compile(r"<\s*(?:br\s*/?|/\s*(?:p|div|li|tr|h[1-6]))\s*>", re.IGNORECASE)
_TN_TAG = re.compile(r"<[^>]+>")
_TN_NUM_ENTITY = re.compile(r"&#(x[0-9a-fA-F]+|\d+);")
_TN_ENTITIES = {"&nbsp;": " ", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#39;": "'", "&apos;": "'", "&amp;": "&"}
#: 剥净后单个字段的上限（设计 §13 防护）
RICH_LIMIT = 20000


def _tn_entity(m: re.Match) -> str:
    body = m.group(1)
    try:
        code = int(body[1:], 16) if body[:1] in ("x", "X") else int(body)
        return chr(code)
    except (ValueError, OverflowError):
        return ""


def rich_display(value: object, limit: int = RICH_LIMIT) -> tuple[str, bool]:
    """富文本 → 展示用的文字：(文字, 是否因超长截断)。空值、只剩空的格式标记都返回空串。"""
    if value is None or (isinstance(value, float) and value != value):  # 空值与 NaN
        return "", False
    text = str(value)
    if not text.strip():
        return "", False
    text = _TN_IMG_DATA.sub("", text)
    text = _TN_DATA_URI.sub("", text)
    text = _TN_IMG_URL.sub(lambda m: f" [图片]({m.group(1)}) ", text)
    text = _TN_BREAK.sub("\n", text)
    text = _TN_TAG.sub("", text)
    for key, ch in _TN_ENTITIES.items():
        text = text.replace(key, ch)
    text = _TN_NUM_ENTITY.sub(_tn_entity, text).replace("\u00a0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    if len(text) > limit:
        return text[:limit], True
    return text, False


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
