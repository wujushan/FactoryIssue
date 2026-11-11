"""富文本的拆与拼、判空判长、给模型的字数（润色设计 §6；第 ③ 步见 §4）。

逻辑照 r1、r2 实测时的 `scripts/polish_spike/polish_core.py`（`e773011` 及之前的版本）搬来，只改结构与命名；
此后实测工具反过来调这里。只用标准库 `re`、`html`（`polish/` 不进沙箱，§2.4）。
"""

from __future__ import annotations

import html
import math
import re
from dataclasses import dataclass

from factory_issue_module.turn import errors

Style = tuple[str, str]
#: 占位标记的两套写法（§6.1）：原文文字里已有 `[[` 或 `]]` 时换成第二套
BRACKET: Style = ("[[", "]]")
ALT: Style = ("⟦", "⟧")

_OPEN = re.compile(r"<(img|table|a)\b", re.IGNORECASE)
#: 段落边界，与 `textnorm._TN_BREAK` 同一组标签（`</tr>` 只会出现在表格里，表格已整个保留）
_BREAK = re.compile(r"<\s*(?:br\s*/?|/\s*(?:p|div|li|h[1-6]))\s*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_KIND = {"img": "图", "table": "表", "a": "链接"}
TABLE_KIND = "表"


@dataclass(frozen=True)
class Split:
    """`text` 是带占位标记的纯文字（每行一段），`tokens` 是 (标记, 原样 HTML) 的有序表。"""

    text: str
    tokens: tuple[tuple[str, str], ...]
    style: Style
    rich: bool

    @property
    def paragraphs(self) -> int:
        return len([ln for ln in self.text.split("\n") if ln.strip()])


def mark_re(style: Style) -> re.Pattern[str]:
    return re.compile(rf"{re.escape(style[0])}(图|表|链接)\d+{re.escape(style[1])}")


def strip_marks(text: str, style: Style) -> str:
    return mark_re(style).sub("", text)


def text_chars(text: str, style: Style) -> int:
    """去掉占位标记与空白后的字数：判空、判长、长度比、日志 `input_chars` 同一口径（§6.1、§14）。"""
    return len(re.sub(r"\s+", "", strip_marks(text, style)))


def has_cjk(text: str) -> bool:
    """只认基本区汉字（同实测工具；`textnorm.has_cjk` 另认扩展 A 区，这里不换，免得与 r2 不一致）。"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def english_only(text: str, style: Style) -> bool:
    """原文没有汉字、有英文字母：按英文润色（§8.1 末段的「原文语言」、§9 第 7 项）。"""
    body = strip_marks(text, style)
    return not has_cjk(body) and any(ch.isascii() and ch.isalpha() for ch in body)


# ---------------------------------------------------------------- 拆（§6.1）


def _close(src: str, start: int, tag: str) -> int:
    """从 `start` 处的开标签起，到与它配对的闭标签之后；没闭合就到原文末尾。按嵌套层数配对，不用非贪婪正则。"""
    if tag == "img":
        end = src.find(">", start)
        return len(src) if end < 0 else end + 1
    depth = 0
    for m in re.finditer(rf"<(/?){tag}\b[^>]*>", src[start:], re.IGNORECASE):
        depth += -1 if m.group(1) else 1
        if depth == 0:
            return start + m.end()
    return len(src)


def _to_text(fragment: str) -> str:
    text = _BREAK.sub("\n", fragment)
    text = _TAG.sub("", text)
    return html.unescape(text).replace("\u00a0", " ")


def _lines(text: str) -> str:
    """每行压缩连续空白、去首尾空白，丢掉空行。"""
    out = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(ln for ln in out if ln)


def split_rich(src: str) -> Split:
    pieces: list[tuple[str, str]] = []  # ("text", 文字) / (类别, 原样 HTML)
    pos = 0
    while True:
        m = _OPEN.search(src, pos)
        if m is None:
            pieces.append(("text", _to_text(src[pos:])))
            break
        pieces.append(("text", _to_text(src[pos:m.start()])))
        end = _close(src, m.start(), m.group(1).lower())
        pieces.append((_KIND[m.group(1).lower()], src[m.start():end]))
        pos = end
    plain = "".join(p for k, p in pieces if k == "text")
    style = ALT if (BRACKET[0] in plain or BRACKET[1] in plain) else BRACKET
    counts: dict[str, int] = {}
    tokens: list[tuple[str, str]] = []
    parts: list[str] = []
    for kind, piece in pieces:
        if kind == "text":
            parts.append(piece)
            continue
        counts[kind] = counts.get(kind, 0) + 1
        mark = f"{style[0]}{kind}{counts[kind]}{style[1]}"
        tokens.append((mark, piece))
        parts.append(mark)
    return Split(text=_lines("".join(parts)), tokens=tuple(tokens), style=style, rich=True)


def split_plain(src: str) -> Split:
    """纯文字栏（5Why 的问与答）：按换行分段，不做 HTML 处理。"""
    return Split(text=_lines(src), tokens=(), style=BRACKET, rich=False)


# ---------------------------------------------------------------- 给模型的字数（§6.2）


def budget(split: Split, limit: int | None) -> int | None:
    """告诉模型的正文字数上限 K；没有字数上限为 None。K ≤ 0 由 `prepare` 按 `POLISH_TOO_LONG` 处理。"""
    if limit is None:
        return None
    if split.rich:
        overhead = sum(len(raw) for _, raw in split.tokens) + 7 * (split.paragraphs + 2)
    else:
        overhead = split.paragraphs  # 拼回用单个换行连接，段落标记按 1 个换行算
    return math.floor((limit - overhead) * 0.95)


# ---------------------------------------------------------------- 拼（§6.3）


def assemble(text: str, split: Split) -> str:
    """模型的正文 → 交给页面的整段。"""
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not split.rich:
        return "\n".join(lines)
    raw = dict(split.tokens)
    pat = mark_re(split.style)
    out: list[str] = []
    for ln in lines:
        buf: list[str] = []
        pos = 0
        for m in pat.finditer(ln):
            buf.append(html.escape(ln[pos:m.start()], quote=False))
            if m.group(1) == TABLE_KIND:  # 表格不能放在 <p> 里：前后断开段落
                para = "".join(buf).strip()
                if para:
                    out.append(f"<p>{para}</p>")
                buf = []
                out.append(raw.get(m.group(0), ""))
            else:
                buf.append(raw.get(m.group(0), ""))
            pos = m.end()
        buf.append(html.escape(ln[pos:], quote=False))
        para = "".join(buf).strip()
        if para:
            out.append(f"<p>{para}</p>")
    return "".join(out)


# ---------------------------------------------------------------- 判空、判长（§4 第 ③ 步）


class NotPolishable(ValueError):
    """原文为空或太长：按 `code` 答，`reason` 只进日志。"""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


REASON_EMPTY = "empty"
REASON_MAX_INPUT = "max_input"
REASON_MARKUP_FILLS = "markup_fills_limit"


@dataclass(frozen=True)
class Prepared:
    split: Split
    #: 这次的字数上限（页面给的或栏目默认，`params.limit_of`）；None 为不限
    limit: int | None
    #: 告诉模型的正文字数上限（§6.2）
    k: int | None
    input_chars: int


def prepare(query: str, *, rich: bool, max_input: int, limit: int | None, ignore_cap: bool = False) -> Prepared:
    """拆原文、判空判长、算 K。`ignore_cap` 只给实测的长度阶梯用（要越过原文长度上限量耗时）。"""
    split = split_rich(query or "") if rich else split_plain(query or "")
    chars = text_chars(split.text, split.style)
    if chars == 0:
        raise NotPolishable(errors.POLISH_EMPTY_CODE, REASON_EMPTY)
    if chars > max_input and not ignore_cap:
        raise NotPolishable(errors.POLISH_TOO_LONG_CODE, REASON_MAX_INPUT)
    k = budget(split, limit)
    if k is not None and k <= 0:
        raise NotPolishable(errors.POLISH_TOO_LONG_CODE, REASON_MARKUP_FILLS)
    return Prepared(split=split, limit=limit, k=k, input_chars=chars)
