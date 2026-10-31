"""文字归一化（设计 §1.4、§12 第 5 步、§13）：治理任务、查询期、沙箱脚本共用同一份写法。

只用 `re`、`json` 与内建函数：沙箱禁止 import `html`、`unicodedata`（设计 §1.4，实测），这份源码原样拼进沙箱脚本。
- `rich_display`：单张详情展示前的剥图（S4，§13；`dirty_data.md`「富文本」）：剔除内嵌 base64 图片，段落与换行
  标记改成换行，外链图片留成链接，其余标签去掉、实体换回字符；剥净后单个字段超过 2 万字时截断并标记。
- `strip_rich`：按文字找单用的剥净（S6，§12 第 5 步）：同上，但外链图片也去掉、不截断。治理任务写进 mart 的文字都是它。
- `phen_parts` / `phen_text`：巴西、海外问题现象 JSON 的展平（各域主表「问题现象」「JSON 列结构」）。详情展示与治理任务
  共用；治理任务另要知道哪几段是手填的（只有手填的参与按意思找）。
- `normalize` / `compact`：按词找的归一化与去空格，治理任务写 `seg_norm`、`seg_compact` 与查询期归一化说法用同一份。
"""

from __future__ import annotations

import json
import re

_SPACES = re.compile(r"\s+")
#: 内嵌 base64 图片（整个 img 标签，或游离的 data: 串）
_TN_IMG_DATA = re.compile(r"<img\b[^>]*?src\s*=\s*[\"']?\s*data:[^>]*>", re.IGNORECASE)
_TN_DATA_URI = re.compile(r"data:image/[^\s\"'<>]*", re.IGNORECASE)
_TN_IMG_URL = re.compile(r"<img\b[^>]*?src\s*=\s*[\"']?(https?://[^\"'\s>]+)[^>]*>", re.IGNORECASE)
_TN_IMG_ANY = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
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


def _tn_clean(value: object, links: bool) -> str:
    """富文本 → 文字。`links` 为真时外链图片留成「[图片](地址)」，否则去掉。空值与 NaN 按空。"""
    if value is None or (isinstance(value, float) and value != value):  # 空值与 NaN
        return ""
    text = str(value)
    if not text.strip():
        return ""
    text = _TN_IMG_DATA.sub("", text)
    text = _TN_DATA_URI.sub("", text)
    if links:
        text = _TN_IMG_URL.sub(lambda m: f" [图片]({m.group(1)}) ", text)
    else:
        text = _TN_IMG_ANY.sub(" ", text)
    text = _TN_BREAK.sub("\n", text)
    text = _TN_TAG.sub("", text)
    for key, ch in _TN_ENTITIES.items():
        text = text.replace(key, ch)
    text = _TN_NUM_ENTITY.sub(_tn_entity, text).replace("\u00a0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


def rich_display(value: object, limit: int = RICH_LIMIT) -> tuple[str, bool]:
    """富文本 → 展示用的文字：(文字, 是否因超长截断)。空值、只剩空的格式标记都返回空串。"""
    text = _tn_clean(value, True)
    if len(text) > limit:
        return text[:limit], True
    return text, False


def strip_rich(value: object) -> str:
    """富文本 → 按文字找单用的文字：图片（内嵌与外链）、标签都去掉，实体还原，段落留成换行，不截断。"""
    return _tn_clean(value, False)


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


# ---------------------------------------------------------------- 问题现象 JSON


def json_items(value: object) -> list[dict]:
    """JSON 数组列：空、不以 `[` 开头、解析不了都按空数组；只留对象元素。

    巴西问题现象可能含非法转义：先按原样解析，不行再把孤立的反斜杠换成两个再解析一次。
    """
    if value is None or (isinstance(value, float) and value != value):
        return []
    text = str(value).strip()
    if not text.startswith("["):
        return []
    for attempt in (text, re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", text)):
        try:
            data = json.loads(attempt)
        except ValueError:
            continue
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    return []


def _tn_key(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            return int(value) if value == int(value) else None
        except (ValueError, OverflowError):
            return None
    text = "" if value is None else str(value).strip()
    return int(text) if re.fullmatch(r"-?\d+", text) else None


def phen_parts(value: object, style: str) -> list[tuple[str, bool]]:
    """问题现象 JSON → [(片段, 是否手填)]，按数组顺序，空段的位置保留。

    `style` 为 `brazil`：手填 `parentType->Value`，`otherVal` 非空时再接一个空格和它（巴西主表「问题现象」）；
    `overseas`：手填 `parentType -> Value`，`otherVal` 去掉空白后仍有内容时接 ` (otherVal)`（海外主表「JSON 列结构」）。
    `Key` 大于 0、为 0 或缺失时只取 `Value`。
    """
    out = []
    for x in json_items(value):
        key = _tn_key(x.get("Key"))
        val = str(x.get("Value") or "")
        if key is not None and key < 0:
            parent = str(x.get("parentType") or "")
            if style == "brazil":
                seg = parent + "->" + val
                other = str(x.get("otherVal") or "")
                if other.strip():
                    seg += " " + other
            else:
                seg = parent + " -> " + val
                other = str(x.get("otherVal") or "").strip()
                if other:
                    seg += " (" + other + ")"
            out.append((seg, True))
        else:
            out.append((val, False))
    return out


def phen_text(value: object, style: str) -> str:
    """问题现象展平后的一段文字：各片段用「；」连接。"""
    return "；".join(seg for seg, _manual in phen_parts(value, style))
