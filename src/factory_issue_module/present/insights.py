"""结论里的要点与需关注的单（总述「先给结论」「结论里的要点与需关注的单」，决策 2026-11-03「结论的要点与需关注的单」）。

要点与需关注的单由沙箱判断、排好（`stats/lib/insights.py`），这里只做三件事，不算任何数：
- `params`：交沙箱的参数（门槛取自 `answer_params.toml`；用户已按某一项筛选或分组时不写那一项）；
- `point_text`：每条要点的模板句（模型没写出合格的那一条时用；数与名称原样取自沙箱）；
- `focus_block`：「需关注」一小段：问题编号（带链接）、理由（沙箱给）、问题描述摘要（同清单那一列，
  `present/summaries.py`；表格里已有摘要的直接用）。

结论 = 加粗的结论句 + 要点 + 需关注，由 `assemble` 拼，块之间空一行。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from factory_issue_module.config.files import AnswerParams
from factory_issue_module.declarations import DOMAINS, Domain
from factory_issue_module.domains import enums
from factory_issue_module.plan import schema
from factory_issue_module.present import columns, links, summaries

_BY_LABEL = {d.label: d for d in DOMAINS}

#: 用户已按它筛选（「是」「属于」）时不写的项
_BY_FILTER = {"问题类型": "集中", "机型": "机型", "系列": "机型", "加工厂": "加工厂", "供应商": "供应商",
              "问题等级": "等级"}
#: 按它分组时不写的项（表里已经给了）
_BY_GROUP = {"问题类型": "集中", "机型": "机型", "系列": "机型", "加工厂": "加工厂", "问题等级": "等级",
             "停线状态": "停线", "处理环节": "积压", "状态": "积压", "结案与否": "积压",
             "年": "时间", "季度": "时间", "月": "时间", "周": "时间"}
_NEGATIVE = ("不是", "不属于")
_STOP_KINDS = ("停线中", "曾经停线", "已经重启", "重启审核通过", "重启审核中", "责任人填写重启方案", "没有停线")
#: 摘要那一格是这几种时「需关注」不给摘要
_NO_SUMMARY = (summaries.NEW_SOON, summaries.EMPTY, columns.DESC_UNAVAILABLE, "")
FOCUS_TITLE = "需关注"


def skips(step: Mapping[str, Any]) -> list[str]:
    """用户已按它筛选或分组、结论里不再写的项。"""
    p = step.get("params") or {}
    out: set[str] = set()
    for f in schema.as_list(p.get("filters")):
        if not isinstance(f, dict) or str(f.get("op") or "") in _NEGATIVE:
            continue
        field = str(f.get("field"))
        if field in _BY_FILTER:
            out.add(_BY_FILTER[field])
        if field == "状态":
            for v in schema.as_list(f.get("value")):
                kind = (enums.status_kind(v) or enums.status_kind(v, enums.BR_STAGES)
                        or enums.status_kind(v, enums.OS_STAGES))
                if kind is not None and kind[0] in _STOP_KINDS:
                    out.add("停线")
    for g in schema.as_list(p.get("group_by")):
        if str(g) in _BY_GROUP:
            out.add(_BY_GROUP[str(g)])
    if "结案周期" in [str(m) for m in schema.as_list(p.get("metrics"))]:
        out.add("时效")
    return sorted(out)


def params(step: Mapping[str, Any], answer: AnswerParams, today: date) -> dict[str, Any]:
    """交沙箱的参数（`stats/lib/insights.py` 开头）。"""
    return {"today": today.isoformat(), "share": answer.concentrate_share, "repeat": answer.repeat_min,
            "months": answer.trend_months, "close_min": answer.close_min, "points": answer.points_max,
            "focus": answer.focus_max, "common": answer.similar_common_min, "skip": skips(step)}


# ---------------------------------------------------------------------------- 要点的模板句


def _names(pairs: Sequence[Sequence[Any]]) -> str:
    return "、".join(str(p[0]) for p in pairs)


def _counted(pairs: Sequence[Sequence[Any]]) -> str:
    """「A（3 张）」；并列的几个张数相同，写「A、B（各 3 张）」。"""
    if not pairs:
        return ""
    n = pairs[0][1]
    return f"{_names(pairs)}（{'各 ' if len(pairs) > 1 else ''}{n} 张）"


def _concentrate(p: Mapping[str, Any]) -> str:
    text = f"最多的是{_counted(p.get('最多的问题类型') or [])}，占 {p.get('占比（%）')}%"
    if p.get("其次"):
        text += f"；其次是{_counted(p['其次'])}"
    return text


def _backlog(p: Mapping[str, Any]) -> str:
    parts = [f"未结案 {p.get('未结案', 0)} 张"]
    for s in p.get("各域未结案最多停在的环节") or []:
        stages = "」「".join(str(x) for x in s.get("最多停在的环节") or [])
        many = "各 " if len(s.get("最多停在的环节") or []) > 1 else ""
        parts.append(f"{s.get('域')}未结案的 {s.get('该域未结案')} 张里，停在「{stages}」的最多（{many}{s.get('张数')} 张）")
    bins = [f"{label} {n} 张" for label, n in p.get("未结案建单天数分档") or [] if n]
    if bins:
        parts.append("按建单天数，" + "、".join(bins))
    old = p.get("建单最久的未结案单") or {}
    if old:
        parts.append(f"最久的 {old.get('问题编号')} 已建单 {old.get('建单天数')} 天")
    return "；".join(parts)


def _severe(p: Mapping[str, Any]) -> str:
    items = [f"{k} {p[k]} 张" for k in ("A+ 级", "A 级", "停线中") if p.get(k)]
    text = "、".join(items)
    early = next((v for k, v in p.items() if k.startswith("国内 2024-04-17")), None)
    if early:
        text += f"（国内 2024-04-17 之前建的 {early} 张单没有问题等级）"
    return text


def _repeat(p: Mapping[str, Any]) -> str:
    return "；".join(f"{what} {_counted(p[what])}" for what in ("机型", "加工厂", "供应商") if p.get(what))


def _months(p: Mapping[str, Any]) -> str:
    lo, hi = (p.get("建单月份范围") or ["", ""])[:2]
    return f"建单跨 {p.get('跨几个月')} 个月（{lo} 至 {hi}），最多的是{_counted(p.get('建单最多的月份') or [])}"


def _close(p: Mapping[str, Any]) -> str:
    return "；".join(f"{x.get('域')}已结案的 {x.get('计入张数')} 张，结案周期中位数 {x.get('结案周期中位数（天）')} 天"
                    for x in p.get("各域已结案的单") or [])


def _sim_dates(p: Mapping[str, Any]) -> str:
    return f"最早一次建单 {p.get('最早一次建单')}，最近一次 {p.get('最近一次建单')}"


def _sim_recur(p: Mapping[str, Any]) -> str:
    return "；".join(f"{x.get('结案的单')} {x.get('结案日期')} 结案后，又建了 {x.get('张数')} 张相近的单"
                    f"（{'、'.join(str(n) for n in x.get('之后又建的相近单') or [])}）" for x in p.get("各域") or [])


def _sim_common(p: Mapping[str, Any]) -> str:
    total = p.get("列出的张数")
    parts = []
    for what in ("供应商", "机型", "加工厂", "原因分类"):
        for name, n in p.get(what) or []:
            parts.append(f"{what}是「{name}」的 {n} 张")
    return f"列出的 {total} 张里，" + "；".join(parts)


def _sim_open(p: Mapping[str, Any]) -> str:
    items = []
    for x in p.get("未结案的单") or []:
        stages = "」「".join(str(s) for s in x.get("停在的环节") or [])
        items.append(f"{x.get('问题编号')}" + (f"（停在「{stages}」）" if stages else ""))
    return "、".join(items)


_TEMPLATES = {"集中": _concentrate, "积压": _backlog, "严重": _severe, "重复": _repeat, "时间": _months, "时效": _close,
              # 类似问题的要点（G86）
              "相近时间": _sim_dates, "结案后又出现": _sim_recur, "共同点": _sim_common, "未结案": _sim_open}


def bullet(name: str, body: str) -> str:
    return f"- **{name}**：{body.strip().rstrip('。；')}"


def point_text(point: Mapping[str, Any]) -> str:
    """一条要点的模板句（数与名称原样取自沙箱）。"""
    fn = _TEMPLATES.get(str(point.get("发现")))
    return bullet(str(point.get("名称") or point.get("发现")), fn(point) if fn else "")


# ---------------------------------------------------------------------------- 需关注


def _from_tables(segs: Iterable[Mapping[str, Any]]) -> dict[tuple[str, int], str]:
    """表格里已经换好的问题描述摘要：(域, 单 ID) → 摘要。"""
    out: dict[tuple[str, int], str] = {}
    for seg in segs:
        dom = _BY_LABEL.get(str(seg.get("domain")))
        table = seg.get("table") or {}
        cols = list(table.get("columns") or [])
        if dom is None:
            continue
        title = columns.shown("desc", dom)
        if title not in cols:
            continue
        at = cols.index(title)
        for pid, row in zip(seg.get("ids_shown") or [], table.get("rows") or [], strict=False):
            out[(dom.label, int(pid))] = str(row[at] if at < len(row) else "")
    return out


async def describe(ctx: Any, focus: Sequence[Mapping[str, Any]], segs: Iterable[Mapping[str, Any]],
                   text_ok: Iterable[Domain]) -> dict[tuple[str, int], str]:
    """需关注的单的问题描述摘要：表格里有的直接用，没有的按单 ID 取（本域文字查找可用时，`summaries.cells`）。"""
    have = _from_tables(segs)
    ok = set(text_ok)
    want: dict[Domain, list[int]] = {}
    for f in focus:
        dom = _BY_LABEL.get(str(f.get("域")))
        key = (str(f.get("域")), int(f.get("id")))
        if dom is not None and dom in ok and key not in have:
            want.setdefault(dom, []).append(int(f["id"]))
    if want:
        doms = list(want)
        got = await asyncio.gather(*(summaries.cells(ctx, d, want[d]) for d in doms))
        for d, texts in zip(doms, got, strict=True):
            for pid, text in zip(want[d], texts, strict=True):
                have[(d.label, pid)] = text
    return have


def focus_block(focus: Sequence[Mapping[str, Any]], descs: Mapping[tuple[str, int], str], sites: Any) -> str:
    """「需关注」一小段；没有单时为空串。"""
    if not focus:
        return ""
    lines = [f"**{FOCUS_TITLE}**", ""]
    for f in focus:
        label = str(f.get("域"))
        number = links.issue(sites, _BY_LABEL.get(label), f.get("问题编号"), f.get("id"))
        desc = (descs.get((label, int(f.get("id")))) or "").strip()
        tail = f"：{desc}" if desc not in _NO_SUMMARY else ""
        lines.append(f"- {number}（{f.get('理由')}）{tail}")
    return "\n".join(lines)


def assemble(head: str, bullets: Sequence[str], focus: str) -> str:
    """加粗的结论句、要点、需关注，块之间空一行。"""
    blocks = [head.strip()]
    if bullets:
        blocks.append("\n".join(bullets))
    if focus:
        blocks.append(focus)
    return "\n\n".join(b for b in blocks if b)


def bold(sentence: str) -> str:
    core = sentence.replace("**", "").strip()
    return f"**{core}**" if core else ""
