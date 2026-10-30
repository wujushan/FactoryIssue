"""答后建议（设计 §9.5）。

- 先放其他理解：计划的 `alternatives` 与代码给的另一种理解（第 13 条修一次仍不一致时的日期依据、「本月比上月」
  的按上月同期比），`query` 是本轮原话加这条理解（`plan/clarify.py::alternative_recommendations`）。
- 再放结果为空时的放宽选项、「最近」的另两个时间范围（`turn/execute.py` 预先查好张数）。
- 再按技能补模板按钮：清单后「按问题类型统计这些单」「导出全部」，汇总后「列出第一名的单」，详情、按号查单后
  「看完整处理过程」「看原因与措施」。`query` 同样是本轮原话加这一项，点了能单独发送、路由回本助手。
- 不带任何条件的清单：模板按钮换成能力介绍的 3 个按钮。
- 按钮总数不超过 4 个，同一个问句只留一个；每项是 `{id, name, label, query}` 对象，`label` 不超过 15 个字。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from factory_issue_module.plan import clarify, schema

MAX_BUTTONS = clarify.MAX_OPTIONS
TEMPLATE_NAME = "接着问"

STAT_BY_TYPE = "按问题类型统计这些单"
EXPORT_ALL = "导出全部"
LIST_TOP1 = "列出第一名的单"
FULL_PROCESS = "看完整处理过程"
REASONS = "看原因与措施"
SAME_PERIOD = "按上月同期比"

_PROCESS_ASPECTS = ("完整处理过程", "驳回")
_REASON_ASPECTS = ("原因", "措施", "处理结果")


def template(label: str, query: str) -> dict[str, str]:
    return {"id": "", "name": TEMPLATE_NAME, "label": label, "query": clarify.with_choice(query, label)}


def list_templates(step: Mapping[str, Any], query: str, *, found: bool, truncated: bool,
                   exported: bool) -> list[dict[str, str]]:
    """清单之后：按问题类型统计这些单（本步没按问题类型筛时）、导出全部（表格没列全又还没导出时）。"""
    if not found:
        return []
    out = []
    filters = schema.as_list((step.get("params") or {}).get("filters"))
    if not any(isinstance(f, dict) and f.get("field") == "问题类型" for f in filters):
        out.append(template(STAT_BY_TYPE, query))
    if truncated and not exported:
        out.append(template(EXPORT_ALL, query))
    return out


def aggregate_templates(step: Mapping[str, Any], query: str, *, top1: Sequence[Any]) -> list[dict[str, str]]:
    """汇总之后：分组统计、有第一名时「列出第一名的单」。"""
    p = step.get("params") or {}
    if not top1 or not p.get("group_by") or p.get("compare"):
        return []
    return [template(LIST_TOP1, query)]


def detail_templates(aspects: Sequence[str], query: str, *, found: bool) -> list[dict[str, str]]:
    """单张单详情、按号查单之后：还没看的完整处理过程、原因与措施。"""
    if not found:
        return []
    out = []
    if not any(a in _PROCESS_ASPECTS for a in aspects):
        out.append(template(FULL_PROCESS, query))
    if not any(a in _REASON_ASPECTS for a in aspects):
        out.append(template(REASONS, query))
    return out


def same_period(query: str, said: str) -> dict[str, str]:
    """「本月比上月」：本月按月初到今天，上个月按完整自然月比；选项把原话里的「上个月」「上月」换成「上月同期」
    （上月 1 日到上月的今天这一天，`plan/timespan.py`）。`said` 只会是这两种说法（调用方查过），写明了年月的
    不替换；原话里找不到那段说法时在句末加上。"""
    ask = query.replace(said, "上月同期", 1) if said and said in query else clarify.with_choice(query, SAME_PERIOD)
    return {"id": "", "name": clarify.ALTERNATIVE_NAME, "label": SAME_PERIOD, "query": ask}


def merge(*groups: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """按顺序合并，同一个问句只留第一个，至多 4 个，重新编号。"""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in groups:
        for rec in group:
            q = str(rec.get("query") or "").strip()
            if not q or q in seen:
                continue
            seen.add(q)
            out.append({**rec, "id": str(len(out) + 1)})
            if len(out) >= MAX_BUTTONS:
                return out
    return out
