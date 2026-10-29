"""汇总统计（设计 §4.3 汇总一行、§6.3、§8.1、§8.2；总述「回答怎么组织」「排名、长清单与导出」「初步分析维度」）。

事件顺序：`delta`（开头：点名第一或给总数）→ `table` → `chart`（分组 2 组及以上）→ `delta`（分析）→ 统计口径
（整轮合并，放最后）。分组、Top N、并列、增减、平均与中位数都由沙箱算（`stats/tasks/aggregate.py`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from factory_issue_module.config.files import AnswerParams
from factory_issue_module.domains import domestic
from factory_issue_module.domains.base import DomainStep
from factory_issue_module.plan import schema
from factory_issue_module.present import columns

#: 总述「初步分析维度」：加工厂、跟进部门看单数与未结案数
_WITH_UNCLOSED = ("加工厂", "跟进部门")

#: 统计表的列名（沙箱直接用它们作列名）
COLS = {
    "count": columns.COUNT, "unclosed": columns.UNCLOSED, "share": columns.SHARE, "domain": columns.DOMAIN,
    "rate": columns.RATE, "close_mean": columns.CLOSE_MEAN, "close_median": columns.CLOSE_MEDIAN,
    "stop_mean": columns.STOP_MEAN, "stop_median": columns.STOP_MEDIAN, "stopped": columns.STOPPED,
    "diff": columns.DIFF, "change": columns.CHANGE, "close_days": columns.CLOSE_DAYS, "period": columns.PERIOD,
}


def metrics_for(step: dict) -> tuple[list[str], list[str]]:
    """(指标, 国内没有的指标)。"""
    p = step.get("params") or {}
    asked = [str(m) for m in schema.as_list(p.get("metrics")) if m]
    group_by = [str(g) for g in schema.as_list(p.get("group_by"))]
    out = list(dict.fromkeys(["单数", *[m for m in asked if m not in domestic.METRICS_ELSEWHERE]]))
    if any(g in _WITH_UNCLOSED for g in group_by) and "未结案数" not in out:
        out.append("未结案数")
    return out, [m for m in asked if m in domestic.METRICS_ELSEWHERE]


def basis_of(step: dict) -> str:
    for t in schema.as_list((step.get("params") or {}).get("time")):
        if isinstance(t, dict) and t.get("basis"):
            return str(t["basis"])
    return "建单"


def params(step: dict, dims_by_domain: dict[str, list[dict[str, Any]]], metrics: Sequence[str],
           dsteps: Sequence[DomainStep], answer: AnswerParams, bounds: Sequence[str | None] | None) -> dict[str, Any]:
    p = step.get("params") or {}
    top = p.get("top") if isinstance(p.get("top"), int) and not isinstance(p.get("top"), bool) else None
    compare = {d.domain.label: d.compare for d in dsteps if d.compare} or None
    return {"dims": dims_by_domain, "metrics": list(metrics), "top": top, "ranking": bool(p.get("ranking")),
            "top_n": answer.top_n, "table_rows": answer.table_rows, "compare": compare}, \
        ({d.domain.label: list(bounds) for d in dsteps} if bounds else {})


def opening(seg: dict[str, Any], label: str, scope: str) -> str:
    """开头一句：总数、第一名或增减（数都来自沙箱的 facts）。"""
    f = seg.get("facts") or {}
    kind = seg.get("kind")
    if kind == "compare":
        cols = (seg.get("table") or {}).get("columns") or []
        if len(cols) >= 3:
            a, b = cols[1], cols[2]
            return f"{label}{a} {f.get(a, 0)} 张，{b} {f.get(b, 0)} 张，{f.get('变化', '')}"
        return f"{label}{scope}没有查到单"
    text = f"{label}{scope}共 {f.get('总单数', 0)} 张"
    if kind == "overview":
        text += f"，其中未结案 {f.get('未结案', 0)} 张、停线中 {f.get('停线中', 0)} 张"
        types = f.get("按问题类型") or []
        if types:
            text += "；问题类型分布：" + "、".join(f"{name} {n} 张" for name, n in types)
        if f.get("合计不良率（%）") is not None and "合计不良率（%）" in f:
            text += f"；合计不良率 {f['合计不良率（%）']}%"
        if f.get("结案周期平均（天）") is not None:
            text += (f"；已结案的单平均 {f['结案周期平均（天）']} 天结案，中位数 {f['结案周期中位数（天）']} 天"
                     f"（计入 {f.get('计入结案周期的单数', 0)} 张）")
        if "停线时长平均（天）" in f:
            if f.get("停线时长平均（天）") is not None:
                text += (f"；已重启的单平均停线 {f['停线时长平均（天）']} 天，中位数 {f['停线时长中位数（天）']} 天"
                         f"（计入 {f.get('计入停线时长的单数', 0)} 张）")
            text += f"；还没重启的 {f.get('还没重启的单数', 0)} 张"
        return text
    title = seg.get("title") or ""
    pairs = f.get("按" + title) or []
    first = f.get("第一") or []
    if pairs and first:
        top_n = pairs[0][1]
        who = "、".join(str(x) for x in first)
        text += f"；按{title}统计，{'并列' if f.get('第一并列') else ''}最多的是{who}（{top_n} 张）"
        if f.get("并列") and f.get("并列名次"):
            text += f"；第 {f['并列名次']} 名并列，{'、'.join(str(x) for x in f['并列'])}都列出"
    elif pairs:
        text += f"，按{title}分为 {f.get('按' + title + '（项数）', 0)} 组"
    return text


def fallback(seg: dict[str, Any]) -> str:
    return opening(seg, "", "") + "。"
