"""号码直通与预匹配（设计 §4.2 第 4 步）。

- 认号：按总述「按编号查单」的认号表，只看写法（闭集），自上而下认，先命中的为准。
- 号码直通：问句去掉号码之后只剩号的种类词与固定套话时不调规划，代码直接生成计划。种类词与套话是代码里的
  固定清单，不放配置；对照集 c5 里命中 16 条（单测锁住这个集合）。PN / PO 样子的串可能是写了连字符的机型
  （「A920-PRO」），用户没说是 PN、PO 时不直通。
- 预匹配：在可查的域的主数据里找问句里整串相同的名字（工厂、部门含简称、人员、机型、系列、供应商、地区说法）。
  只给校验第 15 条、§5.3 第 7 条与名称对不上时的追问选项用，不写成事实附给规划器（§1.3 实测附了更差）。
  两个字的人名会误中常用词（「上周国内」里的「周国」），所以不拿它校验人名。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Collection, Mapping, Sequence

#: 问题编号（总述「按编号查单」第一行）
ISSUE_NUMBER = "问题编号"

_NUMBER_FORMS = tuple(
    (re.compile(r"(?<![A-Za-z0-9])(" + pattern + r")(?![A-Za-z0-9])", re.IGNORECASE), kind)
    for pattern, kind in (
        (r"(?:ZC|BR|HW)[\s\-]?\d{4}[\s\-]?\d{3}", ISSUE_NUMBER),
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

Span = tuple[int, int]


def half(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def find_numbers(query: str) -> list[tuple[str, str, Span]]:
    """[(原样, 认作, 位置)]，位置不重叠，按位置排序。"""
    q = half(query)
    taken: list[Span] = []
    out = []
    for rx, kind in _NUMBER_FORMS:
        for m in rx.finditer(q):
            span = m.span(1)
            if any(a < span[1] and span[0] < b for a, b in taken):
                continue
            taken.append(span)
            out.append((m.group(1), kind, span))
    return sorted(out, key=lambda x: x[2])


def find_entities(
    query: str, index: Mapping[str, Sequence[str]], exclude: Sequence[Span] | None = None
) -> list[tuple[str, list[str], Span]]:
    """[(名字, 在库里属于哪几类, 位置)]：整串相同、长的优先、不与号码重叠。

    `index` 是「名字 → 它在库里属于哪几类」（类别里写了「机型」的才参与校验第 15 条）。英文与数字组成的
    名字前后不能紧挨字母或数字（「A920」不在「A920PRO」里认）。
    """
    q = half(query)
    low = q.lower()
    taken = list(exclude or [])
    out = []
    for name in sorted(index, key=len, reverse=True):
        if len(name) < 2:
            continue
        key = half(name).lower()
        start = 0
        while True:
            at = low.find(key, start)
            if at < 0:
                break
            span = (at, at + len(key))
            start = at + 1
            if any(a < span[1] and span[0] < b for a, b in taken):
                continue
            if _ASCII.match(key) and (
                (at > 0 and low[at - 1].isascii() and low[at - 1].isalnum())
                or (span[1] < len(low) and low[span[1]].isascii() and low[span[1]].isalnum())
            ):
                continue
            taken.append(span)
            out.append((q[span[0] : span[1]], list(index[name]), span))
    return sorted(out, key=lambda x: x[2])


# ---------------------------------------------------------------------------- 号码直通

#: 号的种类词：用户说了是什么号时按说的查
_KIND_WORDS = re.compile(
    r"(?i)小板订单号?|生产订单号?|订单号?|CAR\s*编号|CAR报告编号|发货单号?|PO号?|投诉单号?|料号|PN编码|PN|"
    r"问题编号|制程单号|单号|编号|号码"
)
#: 只在去掉号码与种类词之后才认的套话；认不全就交规划器，不硬判
_FILLER = re.compile(
    r"帮我|帮忙|麻烦|请|查一下|查查|查询|查|看一下|看看|一下|这张单|这几张单|这些单|这个|这几个|这些|"
    r"(?:是|对应|关联了?|挂着?)(?:的)?(?:哪张|哪些|哪个|什么|哪几张)(?:制程)?(?:问题)?单?|"
    r"(?:关联|对应)(?:了)?(?:哪些|哪张)?(?:制程)?问题|的问题|有哪些|是什么|的|和|与|及|以及|还有|"
    r"[\s，,、；;。？?！!：:]"
)


#: 认作「PN 名称或海外 PO」的串去掉连字符后长得像机型名（字母 + 数字 + 可有字母：「A920-PRO」即 A920PRO，
#: 总述「机型与系列怎么对」忽略连字符）；用户又没说是 PN、PO 时可能是机型，不直通，交规划器
_MACHINE_SHAPE = re.compile(r"[A-Z]+\d+[A-Z]*", re.IGNORECASE)
_PN_OR_PO = "PN 名称或海外 PO"
_SAID_PN_OR_PO = re.compile(r"(?i)PN|PO")


def _maybe_machine(raw: str, kinds: Sequence[str], machines: Collection[str] | None) -> bool:
    if any(_SAID_PN_OR_PO.match(k) for k in kinds):
        return False
    joined = re.sub(r"[\s\-_]+", "", half(raw))
    if machines is not None and joined.lower() in {re.sub(r"[\s\-_]+", "", half(m)).lower() for m in machines}:
        return True
    return bool(_MACHINE_SHAPE.fullmatch(joined))


def number_shortcut(query: str, machines: Collection[str] | None = None) -> dict | None:
    """返回直通的计划；问句里除了号码还有别的意思时返回 None，照常规划。

    `machines` 是可查的域的机型名称（S2 起由主数据给）：PN / PO 样子的串去掉连字符后对得上机型、用户又没说
    是 PN、PO 时不直通。没给机型清单时按长相判断（`_MACHINE_SHAPE`）。不直通的代价只是一次规划调用。
    """
    nums = find_numbers(query)
    if not nums:
        return None
    q = half(query)
    rest = "".join(ch for i, ch in enumerate(q) if not any(a <= i < b for *_, (a, b) in nums))
    kinds = _KIND_WORDS.findall(rest)
    rest = _FILLER.sub("", _KIND_WORDS.sub("", rest))
    if rest:
        return None
    if any(kind == _PN_OR_PO and _maybe_machine(raw, kinds, machines) for raw, kind, _ in nums):
        return None
    if len(nums) == 1 and nums[0][1] == ISSUE_NUMBER:
        return {
            "understanding": "（号码直通）看这张单的详情", "alternatives": [],
            "steps": [{"id": "s1", "skill": "issue_detail", "when": None,
                       "params": {"issue": {"value": nums[0][0], "from": "user"}}}],
        }
    kind_said = kinds[0] if len(kinds) == 1 and len(nums) == 1 else None
    return {
        "understanding": "（号码直通）按号码找单", "alternatives": [],
        "steps": [{"id": "s1", "skill": "lookup_numbers", "when": None,
                   "params": {"numbers": [{"raw": raw, "kind_said": kind_said} for raw, *_ in nums]}}],
    }
