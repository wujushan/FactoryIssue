"""认号（设计 §1.4、§4.2 第 6 步、§6.3 `lookup_numbers` 一行、§14「给了无权域的单号」）。

规则照总述「按编号查单」、国内「按订单号查单」「按 CAR 编号查单」、海外「按发货单号、PO 查单」、巴西「投诉单号」
「查询范围」：

- 用户说了是什么号时按说的查，不按样子猜；只说「订单」「订单号」时国内订单与海外发货单、PO 都查。问题编号、
  15 位编码、CAR 编号的样子总按样子认，用户说是订单也不当订单号（国内「按订单号查单」）。
- 没说时按样子认，认号表自上而下，先命中的为准。
- 写法统一：问题编号、CAR 编号不分大小写，全角转半角，忽略中间的空格、连字符。
- 号只可能在一个域（问题编号、CAR 编号、国内订单号、投诉单号）而该域无权时，只答「您没有该域的查看权限」，
  不查、不说有没有这个号；号可能在几个域时只查有权的域，写明无权的域未查（`privileges.md`「域闸门」）。
- 认不出、位数不对的号交编排追问（§4.2 第 6 步），不拿它去全库模糊搜。追问的按钮发回「原话（选项）」，
  `chosen` 认回选项，免得同一句一直追问（S3 的 BR-004 教训）。

只做字符串处理，不取数、不产生给用户的数。
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from factory_issue_module.declarations import DOMAINS, Domain
from factory_issue_module.domains import base
from factory_issue_module.plan.prematch import half

ISSUE = "issue"
CAR = "car"
PROD_ORDER = "prod_order"
XB_ORDER = "xb_order"
DELIVERY = "delivery"
PO = "po"
INV = "inv"
PN_CODE = "pn_code"
PN_NAME = "pn_name"
CLAIM = "claim"
DEBIT = "debit"
INSTORE = "instore"

#: 号的种类 → 回答里怎么叫（「按生产订单号 230939 找到」）
KIND_TEXT = {ISSUE: "问题编号", CAR: "CAR 编号", PROD_ORDER: "生产订单号", XB_ORDER: "小板订单号",
             DELIVERY: "发货单号", PO: "PO", INV: "料号", PN_CODE: "PN 编码", PN_NAME: "PN 名称",
             CLAIM: "投诉单号", DEBIT: "扣款单号", INSTORE: "入库单号"}
#: 每种号可能在哪些域
KIND_DOMAINS: dict[str, tuple[Domain, ...]] = {
    ISSUE: DOMAINS, CAR: (Domain.DOMESTIC,), PROD_ORDER: (Domain.DOMESTIC,), XB_ORDER: (Domain.DOMESTIC,),
    DELIVERY: (Domain.OVERSEAS,), PO: (Domain.OVERSEAS,), INV: DOMAINS, PN_CODE: DOMAINS, PN_NAME: DOMAINS,
    CLAIM: (Domain.BRAZIL,), DEBIT: (Domain.BRAZIL,), INSTORE: (Domain.BRAZIL,),
}
_PREFIX = {d.prefix: d for d in DOMAINS}

#: 能用来查单的号（认不出时列给用户，总述「按编号查单」对不上时怎么答）
USABLE = "问题编号、CAR 编号、国内生产订单号与小板订单号、海外发货单号与 PO、料号与 PN、巴西投诉单号"
UNKNOWN_REASON = "认不出的号"
FORMAT_REASON = "单号位数不对"
#: 认不出时给的选项：点了发回「原话（订单号）」，`chosen` 认回来当作用户说了是什么号
UNKNOWN_OPTIONS = ("订单号", "料号或 PN", "投诉单号", "发货单号")
ISSUE_FORMAT = "单号应为前缀 + 年 2 位 + 月 2 位 + 3 位序号，请核对"
CAR_FORMAT = "CAR 编号应为「CAR + 9 位数字」，请核对"
NOT_FOR_LOOKUP = "本助手不按其他在线订单号、退货单号查单，只支持按生产订单号、小板订单号查单"


@dataclass(frozen=True)
class Lookup:
    """按一种号在若干域里查：种类、规整后的值、可能在哪些域。"""

    kind: str
    value: str
    domains: tuple[Domain, ...]


@dataclass
class Number:
    raw: str
    lookups: list[Lookup] = field(default_factory=list)
    #: 认不出、位数不对：给用户的话与追问原因（编排把它做成追问）
    problem: str | None = None
    reason: str = ""
    options: list[str] = field(default_factory=list)
    #: 认得出、但本助手不按它查单（国内其他在线订单号、退货单号）
    unsupported: str | None = None

    @property
    def possible(self) -> tuple[Domain, ...]:
        """这个号可能在哪些域（国内、巴西、海外的顺序）。"""
        have = {d for lk in self.lookups for d in lk.domains}
        return tuple(d for d in DOMAINS if d in have)


def _squash(text: str) -> str:
    return re.sub(r"[\s\-_]+", "", half(text)).upper()


def issue_number(raw: str) -> tuple[str, Domain] | str:
    """问题编号 → (规整后的编号, 域)；样子像问题编号、位数或年月不对时返回要对用户说的话。"""
    s = _squash(raw)
    m = re.fullmatch(r"(ZC|BR|HW)(\d+)", s)
    if m is None or len(m.group(2)) != 7 or not 1 <= int(m.group(2)[2:4]) <= 12:
        return ISSUE_FORMAT
    return s, _PREFIX[m.group(1)]


def looks_like_issue(raw: str) -> bool:
    return re.fullmatch(r"(ZC|BR|HW)[\d\s\-]*\d[\d\s\-]*", half(raw).strip().upper()) is not None


def _yymm(digits: str) -> bool:
    """7 位数字的前四位是 2021 年以来的年月（月份 01–12）：也当作省了前缀的问题编号。"""
    return int(digits[:2]) >= 21 and 1 <= int(digits[2:4]) <= 12


def _kinds_said(said: str | None) -> list[str] | None:
    """用户说的号的种类 → 按哪几种查；没说、说的是「单号」「编号」这类泛称时返回 None（按样子认）。"""
    k = re.sub(r"\s+", "", half(said or "")).upper()
    if not k:
        return None
    if "其他在线" in k or "退货" in k:
        return ["unsupported"]
    if "CAR" in k:
        return [CAR]
    if "投诉" in k or "CLAIM" in k:
        return [CLAIM]
    if "扣款" in k:
        return [DEBIT]
    if "入库单" in k:
        return [INSTORE]
    if "发货" in k:
        return [DELIVERY]
    if "小板" in k:
        return [XB_ORDER]
    if "生产订单" in k:
        return [PROD_ORDER]
    if "订单" in k or "工单" in k:
        return [PROD_ORDER, XB_ORDER, DELIVERY, PO]
    if "PO" in k and "PN" not in k:
        return [PO]
    if ("料号" in k or "物料" in k) and "PN" in k:
        return [INV, "pn"]
    if "料号" in k or "物料" in k:
        return [INV]
    if "PN" in k:
        return ["pn"]
    return None


def recognize(raw: str, kind_said: str | None = None, query: str = "") -> Number:
    """认一个号（见模块说明）。`query` 是本轮原话：用户点了认不出时的选项，末尾带着「（订单号）」。"""
    raw = str(raw or "").strip()
    out = Number(raw=raw)
    text = half(raw).strip()
    squashed = _squash(raw)
    if looks_like_issue(text):
        got = issue_number(text)
        if isinstance(got, str):
            out.problem, out.reason = got, FORMAT_REASON
        else:
            out.lookups.append(Lookup(ISSUE, got[0], (got[1],)))
        return out
    if re.fullmatch(r"CAR[\d\s\-]*", squashed):
        if re.fullmatch(r"CAR\d{9}", squashed):
            out.lookups.append(Lookup(CAR, squashed, KIND_DOMAINS[CAR]))
        else:
            out.problem, out.reason = CAR_FORMAT, FORMAT_REASON
        return out
    said = _kinds_said(kind_said) or _kinds_said(base.chosen(query, UNKNOWN_OPTIONS))
    if re.fullmatch(r"\d{15}", text):
        # 15 位编码：说了料号或 PN 就只查那一种，其余（含说是订单）两处都查（总述「三域共用的说法」15 位数字一行）
        kinds = [INV] if said == [INV] else [PN_CODE] if said == ["pn"] else [INV, PN_CODE]
        out.lookups += [Lookup(kind, text, KIND_DOMAINS[kind]) for kind in kinds]
        return out
    if said == ["unsupported"]:
        out.unsupported = NOT_FOR_LOOKUP
        return out
    if said is not None:
        for kind in said:
            if kind == "pn":
                kind = PN_CODE if re.fullmatch(r"\d+", text) else PN_NAME
            value = text if kind != CLAIM else raw
            out.lookups.append(Lookup(kind, value, KIND_DOMAINS[kind]))
        return out
    if re.fullmatch(r"CLAIM.*", text, re.IGNORECASE):
        out.lookups.append(Lookup(CLAIM, raw, KIND_DOMAINS[CLAIM]))
    elif re.fullmatch(r"\d{6}(-\d+)?", text):
        out.lookups += [Lookup(PROD_ORDER, text, KIND_DOMAINS[PROD_ORDER]), Lookup(XB_ORDER, text, KIND_DOMAINS[XB_ORDER])]
    elif re.fullmatch(r"\d{7}", text):
        out.lookups.append(Lookup(DELIVERY, text, KIND_DOMAINS[DELIVERY]))
        if _yymm(text):
            out.lookups += [Lookup(ISSUE, d.prefix + text, (d,)) for d in DOMAINS]
    elif re.fullmatch(r"(?=.*[A-Za-z])[A-Za-z0-9]+(-[A-Za-z0-9]+)+", text):
        out.lookups += [Lookup(PN_NAME, text, KIND_DOMAINS[PN_NAME]), Lookup(PO, text, KIND_DOMAINS[PO])]
    elif re.fullmatch(r"[A-Za-z]{2}\d{7}", text):
        out.unsupported = NOT_FOR_LOOKUP
    else:
        out.problem = f"认不出「{raw}」是什么号。能用来查单的号有：{USABLE}。请说明这是哪种号"
        out.reason, out.options = UNKNOWN_REASON, list(UNKNOWN_OPTIONS)
    return out


def within(number: Number, asked: Sequence[Domain] | None) -> Number:
    """用户点了域时只在点的域里查。带前缀的问题编号按前缀定域（「巴西的 ZC2509012」仍查国内，回答里点出是哪个域
    的单）；点的域里一种都查不了时照号本来的域查。"""
    if not asked:
        return number
    if len(number.lookups) == 1 and number.lookups[0].kind == ISSUE:
        return number
    keep = set(asked)
    lookups = [Lookup(lk.kind, lk.value, tuple(d for d in lk.domains if d in keep)) for lk in number.lookups]
    lookups = [lk for lk in lookups if lk.domains]
    if not lookups:
        return number
    return Number(raw=number.raw, lookups=lookups, problem=number.problem, reason=number.reason,
                  options=number.options, unsupported=number.unsupported)


def prefix_note(number: Number, asked: Sequence[Domain] | None) -> str | None:
    """单号前缀与用户点的域不一致时点出这是哪个域的单（总述「按编号查单」对不上时怎么答）。"""
    if not asked or len(number.lookups) != 1 or number.lookups[0].kind != ISSUE:
        return None
    dom = number.lookups[0].domains[0]
    return None if dom in asked else f"{number.lookups[0].value} 是{dom.label}的单，按{dom.label}查"


def single_domain(number: Number) -> Domain | None:
    """号只可能在一个域时返回该域（问题编号、CAR 编号、国内订单号、投诉单号）。"""
    doms = number.possible
    return doms[0] if len(doms) == 1 else None
