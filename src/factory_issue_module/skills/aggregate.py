"""汇总统计（设计 §4.3 汇总一行、§6.3、§8.1、§8.2；总述「回答怎么组织」「排名、长清单与导出」「初步分析维度」
「跨域规则」）。

事件顺序（决策 2026-11-03「回答骨架与排版」）：提示行 → 结论（模型写，第一句点名第一或给总数；模板句是
`opening`）→ 每张表一节（小标题 `heading`、`table`、并列那句、`chart`）→ 统计口径（整轮合并，放最后）。分组、Top N、
并列、增减、平均与中位数、跨域合并都由沙箱算（`stats/tasks/aggregate.py`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from factory_issue_module.config.files import AnswerParams
from factory_issue_module.domains.base import DomainStep
from factory_issue_module.plan import schema
from factory_issue_module.present import columns

#: 总述「初步分析维度」：加工厂、跟进部门看单数与未结案数
_WITH_UNCLOSED = ("加工厂", "跟进部门")
#: 不看域都能算的指标；其余要看本域能不能算（各适配器的 `TRAITS`）
BASIC_METRICS = ("单数", "占比", "未结案数")
#: 巴西、海外按年季月周统计、该域不到这么多张时提示样本少（总述「统计口径说明」样本量一行的「单数很少」）
SMALL_SAMPLE = 10

#: 统计表的列名（沙箱直接用它们作列名）
COLS = {
    "count": columns.COUNT, "unclosed": columns.UNCLOSED, "share": columns.SHARE, "domain": columns.DOMAIN,
    "rate": columns.RATE, "close_mean": columns.CLOSE_MEAN, "close_median": columns.CLOSE_MEDIAN,
    "stop_mean": columns.STOP_MEAN, "stop_median": columns.STOP_MEDIAN, "stopped": columns.STOPPED,
    "diff": columns.DIFF, "change": columns.CHANGE, "close_days": columns.CLOSE_DAYS, "period": columns.PERIOD,
    "total": columns.TOTAL, "unclosed_share": columns.UNCLOSED_SHARE, "usd": columns.COST_USD,
    "brl": columns.COST_BRL, "debit": columns.DEBIT,
}


def metrics_for(step: dict) -> list[str]:
    """本步要的指标（总有单数；按加工厂、跟进部门分组时加未结案数）。本域能不能算由调用方按 `TRAITS` 看。"""
    p = step.get("params") or {}
    asked = [str(m) for m in schema.as_list(p.get("metrics")) if m]
    group_by = [str(g) for g in schema.as_list(p.get("group_by"))]
    out = list(dict.fromkeys(["单数", *asked]))
    if any(g in _WITH_UNCLOSED for g in group_by) and "未结案数" not in out:
        out.append("未结案数")
    return out


def unsupported(metrics: Sequence[str], traits: dict[str, Any]) -> list[str]:
    """本域算不了的指标（不良率另说：海外原文不汇总，由沙箱逐单列出）。"""
    have = set(traits.get("metrics") or [])
    return [m for m in metrics if m not in BASIC_METRICS and m not in have and m != "合计不良率"]


def basis_of(step: dict) -> str:
    for t in schema.as_list((step.get("params") or {}).get("time")):
        if isinstance(t, dict) and t.get("basis"):
            return str(t["basis"])
    return "建单"


def params(step: dict, dims_by_domain: dict[str, list[dict[str, Any]]], metrics: Sequence[str],
           dsteps: Sequence[DomainStep], answer: AnswerParams, bounds: Sequence[str | None] | None) -> tuple[
        dict[str, Any], dict[str, list[str | None]]]:
    p = step.get("params") or {}
    top = p.get("top") if isinstance(p.get("top"), int) and not isinstance(p.get("top"), bool) else None
    compare = {d.domain.label: d.compare for d in dsteps if d.compare} or None
    group_by = [str(g) for g in schema.as_list(p.get("group_by"))]
    return {"dims": dims_by_domain, "metrics": list(metrics), "top": top, "ranking": bool(p.get("ranking")),
            "top_n": answer.top_n, "table_rows": answer.table_rows, "compare": compare, "group_by": group_by,
            "small_sample": SMALL_SAMPLE}, \
        ({d.domain.label: list(bounds) for d in dsteps} if bounds else {})


def _counts(pairs: Sequence[Sequence[Any]]) -> str:
    return "、".join(f"{d} {n} 张" for d, n in pairs)


def heading(seg: dict[str, Any], label: str) -> str:
    """一张表一节的小标题：按什么统计、合计或总数（决策 2026-11-03「回答骨架与排版」；张数来自沙箱）。各域张数在表里。"""
    f = seg.get("facts") or {}
    what = f"{label}按{seg.get('title')}统计" if seg.get("kind") == "group" else f"{label}统计"
    if seg.get("kind") == "compare":
        return what
    return f"{what}（{'合计' if seg.get('cross') else '共'} {f.get('总单数', 0)} 张）"


def caption(seg: dict[str, Any]) -> str:
    """表格下面那句：第 N 名并列、都列出时写明（总述「排名、长清单与导出」）。"""
    f = seg.get("facts") or {}
    tied = [str(x) for x in f.get("并列") or []]
    first = {str(x) for x in f.get("第一") or []}
    if seg.get("kind") == "group" and tied and f.get("并列名次") and set(tied) != first:
        return f"第 {f['并列名次']} 名并列，{'、'.join(tied)}都列出"
    return ""


def opening(seg: dict[str, Any], label: str, scope: str, *, tie: bool = True) -> str:
    """一段的模板句：总数、第一名或增减（数都来自沙箱的 facts）。三域一起时先给各域小计再给合计。模型没写出合格的
    结论时用它；`tie=False` 时不写第 N 名并列那一句（那句另写在表格下面，`caption`）。"""
    f = seg.get("facts") or {}
    kind = seg.get("kind")
    if kind == "compare":
        cols = (seg.get("table") or {}).get("columns") or []
        if len(cols) >= 3:
            a, b = cols[1], cols[2]
            head = f"{label}，" if label else ""
            return f"{head}{a} {f.get(a, 0)} 张，{b} {f.get(b, 0)} 张，{f.get('变化', '')}"
        return f"{label}{scope}没有查到单"
    if seg.get("cross") and f.get("各域单数"):
        text = f"{label}{scope}合计 {f.get('总单数', 0)} 张（{_counts(f['各域单数'])}）"
    else:
        text = f"{label}{scope}共 {f.get('总单数', 0)} 张"
    if kind == "overview":
        text += f"，其中未结案 {f.get('未结案', 0)} 张、停线中 {f.get('停线中', 0)} 张"
        types = f.get("按问题类型") or []
        if types:
            text += "；问题类型分布：" + "、".join(f"{name} {n} 张" for name, n in types)
        text += distribution_blanks(f, "问题类型")
        if seg.get("cross"):
            return text + _cross_metrics(f)
        return text + _metrics_text(f)
    title = seg.get("title") or ""
    pairs = f.get("按" + title) or []
    first = f.get("第一") or []
    if pairs and first:
        top_n = next((n for k, n in pairs if k == first[0]), pairs[0][1])
        who = "、".join(str(x) for x in first)
        text += f"；按{title}统计，{'并列' if f.get('第一并列') else ''}最多的是{who}（{top_n} 张）"
        tied = [str(x) for x in f.get("并列") or []]
        # 第一名全体并列、又超过要的名次时，「第 N 名并列」点的是同一批名字，只说前一句（S2 复评留下的一处）
        if tie and tied and f.get("并列名次") and set(tied) != {str(x) for x in first}:
            text += f"；第 {f['并列名次']} 名并列，{'、'.join(tied)}都列出"
    elif _only_unranked(seg):  # 问题等级 A+、A、B、C 没有单也列出，所以先看这一条
        text += "；" + _only_text(seg)
    elif pairs:
        text += f"，按{title}分为 {f.get('按' + title + '（项数）', 0)} 组"
    return text


# ---------------------------------------------------------------------------- 不参加排名的「未填」（G87、G88）


def _only_unranked(seg: dict[str, Any]) -> bool:
    info = seg.get("unranked") or {}
    return seg.get("kind") == "group" and bool(info.get("rows")) and bool(info.get("only"))


def _blank_parts(info: dict[str, Any]) -> list[str]:
    """「3 张没填机型（其中物料单 2 张）」「1 张问题类型为『其他（未识别）』」；张数都来自沙箱。"""
    title = str(info.get("title") or "")
    out = []
    for value, n in info.get("rows") or []:
        if value == "未填":
            material = int(info.get("material") or 0)
            out.append(f"{n} 张没填{title}" + (f"（其中物料单 {material} 张）" if material else ""))
        elif title and title in str(value):  # 「未识别机型」：不写成「机型为『未识别机型』」
            out.append(f"{n} 张为「{value}」")
        else:
            out.append(f"{n} 张{title}为「{value}」")
    return out


def distribution_blanks(facts: dict[str, Any], title: str) -> str:
    """分布里不参加排名的那几项（沙箱放在「不参加排名的 X」）：「；另有 5 张没填问题类型」，没有时为空串。"""
    rows = facts.get("不参加排名的" + title) or []
    parts = _blank_parts({"title": title, "rows": rows})
    return ("；另有 " + "、".join(parts)) if parts else ""


def _only_text(seg: dict[str, Any]) -> str:
    """只有不参加排名的几组：不点名第一（总述「排名、长清单与导出」）。"""
    info = seg.get("unranked") or {}
    title = str(info.get("title") or "")
    rows = info.get("rows") or []
    found = int(seg.get("found") or 0)
    if len(rows) == 1 and rows[0][0] == "未填" and int(rows[0][1]) == found:
        material = int(info.get("material") or 0)
        head = f"这 {found} 张单都没填{title}" + (f"（其中物料单 {material} 张）" if material else "")
    else:
        head = "其中 " + "、".join(_blank_parts(info))
    return f"{head}，没有可以排名的{title}"


def unranked_note(seg: dict[str, Any], label: str, ranking: bool) -> str:
    """结论句后面那句（总述「排名、长清单与导出」）：「另有 N 张没填机型（其中物料单 M 张），不参加排名」，没填的比第一名
    还多时再加一句。只有这几组时已写在模板句里（`_only_text`），这里不写；`label` 是几张表共用一段结论时的域名。"""
    info = seg.get("unranked") or {}
    if seg.get("kind") != "group" or not info.get("rows") or info.get("only"):
        return ""
    title = str(info.get("title") or "")
    text = f"{label}另有 " + "、".join(_blank_parts(info)) + ("，不参加排名" if ranking else "") + "。"
    if info.get("over_first"):
        text += f"没填{title}的单比排第一的还多，排名只反映已填{title}的单。"
    return text


def _metrics_text(f: dict[str, Any]) -> str:
    text = ""
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
    if "涉及费用的单数" in f:
        text += f"；涉及费用的单 {f['涉及费用的单数']} 张"
    if "费用美元合计" in f:
        text += f"，费用合计 {f['费用美元合计']} 美元"
        if f.get("只产生雷亚尔费用的单数"):
            text += (f"；另有 {f['只产生雷亚尔费用的单数']} 张只产生了雷亚尔费用，"
                     f"合计 {f['这些单的雷亚尔合计']} 雷亚尔，未计入美元合计")
    if "费用雷亚尔合计" in f:
        text += f"；雷亚尔费用合计 {f['费用雷亚尔合计']} 雷亚尔"
    if "扣款费用（美元）合计" in f:
        text += f"；扣款 {f['扣款费用（美元）合计']} 美元（扣款单独列出，未计入费用）"
    return text


def _cross_metrics(f: dict[str, Any]) -> str:
    """三域一起的概况：不良率分域给（国内、巴西分母不同，不合成跨域的数），其余指标看表。"""
    per = f.get("各域") or {}
    rates = [f"{d} {x['合计不良率（%）']}%" for d, x in per.items()
             if isinstance(x, dict) and x.get("合计不良率（%）") is not None]
    return f"；合计不良率分域给出：{'、'.join(rates)}" if rates else ""


def fallback(seg: dict[str, Any]) -> str:
    return opening(seg, "", "") + "。"
