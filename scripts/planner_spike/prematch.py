"""问句预匹配：规划之前，代码先读一遍问句，找出能核对的号码与名字，写成一段提示附在问句后。

只报告「这个词在库里是什么」，不建议用哪种查法；条件仍由模型照抄原话填写，代码规划后照常对库。

- 号码：按总述「按编号查单」的认号表，只看写法（闭集）。
- 名字：在合成主数据（mockdata.py）里找整串相同的名字，只查工厂、部门、人员、机型、系列、供应商、地区说法；
  物料名称不查（存货档案 9.5 万条，「喇叭」这种词会对上一大片）。英文与数字组成的名字前后不能紧挨字母或数字。
  长的优先：「A920PRO」不再报「A920」，号码里的「A35-000-RD6-00E0」不再报机型「A35」。
"""

from __future__ import annotations

import re
import unicodedata

from mockdata import CATALOG

# 自上而下认，先命中的为准（总述「按编号查单」）
_NUMBER_FORMS = tuple(
    (re.compile(r"(?<![A-Za-z0-9])(" + pattern + r")(?![A-Za-z0-9])", re.IGNORECASE), kind)
    for pattern, kind in (
        (r"(?:ZC|BR|HW)[\s\-]?\d{4}[\s\-]?\d{3}", "问题编号"),
        (r"CAR\s?\d{9}", "CAR 编号"),
        (r"CLAIM[\w\-/]*", "巴西投诉单号"),
        (r"\d{6}-\d{1,3}", "国内生产订单号（手填）"),
        (r"[A-Z0-9]*[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+|[A-Z0-9]+(?:-[A-Z0-9]+)*-[A-Z0-9]*[A-Z][A-Z0-9]*", "PN 名称或海外 PO"),
        (r"\d{15}", "料号或 PN 编码"),
        (r"\d{7}", "海外发货单号，也可能是省了前缀的问题编号"),
        (r"\d{6}", "国内生产订单号或小板订单号"),
        (r"[A-Z]{2}\d{7}", "国内其他在线订单号（不用于查单）"),
        (r"\d{8,}", "认不出是什么号"),
    )
)
_ASCII = re.compile(r"^[A-Za-z0-9]+$")


def _half(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def find_numbers(query: str) -> list[tuple[str, str, tuple[int, int]]]:
    """[(原样, 认作, 位置)]，位置不重叠。"""
    q = _half(query)
    taken: list[tuple[int, int]] = []
    out = []
    for rx, kind in _NUMBER_FORMS:
        for m in rx.finditer(q):
            span = m.span(1)
            if any(a < span[1] and span[0] < b for a, b in taken):
                continue
            taken.append(span)
            out.append((m.group(1), kind, span))
    return sorted(out, key=lambda x: x[2])


_BY_LEN = sorted(CATALOG, key=len, reverse=True)


def find_entities(query: str, exclude: list[tuple[int, int]] | None = None) -> list[tuple[str, list[str], tuple[int, int]]]:
    """[(名字, 在库里属于哪几类, 位置)]：整串相同、长的优先、不与号码重叠。"""
    q = _half(query)
    low = q.lower()
    taken = list(exclude or [])
    out = []
    for name in _BY_LEN:
        if len(name) < 2:
            continue
        key = _half(name).lower()
        start = 0
        while True:
            at = low.find(key, start)
            if at < 0:
                break
            span = (at, at + len(key))
            start = at + 1
            if any(a < span[1] and span[0] < b for a, b in taken):
                continue
            if _ASCII.match(key) and ((at > 0 and low[at - 1].isascii() and low[at - 1].isalnum())
                                     or (span[1] < len(low) and low[span[1]].isascii() and low[span[1]].isalnum())):
                continue
            taken.append(span)
            out.append((q[span[0]:span[1]], CATALOG[name], span))
    return sorted(out, key=lambda x: x[2])


HEADER = ("【问句里能对上的名称与号码】（程序对照库里的取值找出来的，只说明这些词在库里是什么；"
          "用不用、放进哪个条件由你判断，条件里仍照抄用户的原话）")


def hints(query: str) -> list[str]:
    nums = find_numbers(query)
    lines = [f"- 「{raw}」：" + (kind if kind.startswith("认不出") else f"样子像{kind}") for raw, kind, _ in nums]
    for text, kinds, _ in find_entities(query, [s for *_, s in nums]):
        lines.append(f"- 「{text}」：{'；'.join(kinds)}" + ("（同名）" if len(kinds) > 1 else ""))
    return lines


def hint_text(query: str) -> str | None:
    lines = hints(query)
    return "\n".join([HEADER, *lines]) if lines else None
